# V2W — 全文搜索详细设计

> 在转写文本中快速定位关键内容，并跳转播放。本文档为后续迭代的实现依据。
>
> 对应执行计划：**P6（单文件内搜索）→ P7（全局搜索）**，详见 [execution-plan.md](execution-plan.md)。

## 1. 背景与目标

「全文搜索」在 [requirements.md](requirements.md) 中原属 MVP 之外的功能，现立项进入下一阶段迭代。

### 1.1 核心痛点（产品经理视角）

最高频的需求不是「全局搜」，而是**「在一篇长转写里快速找到某句话」**：

- 「客户提到预算的那个地方在几分几秒？」
- 「上次说的『排期』相关讨论有哪些？」
- 「结论那句话在哪，我想再听一遍原话。」

### 1.2 核心价值

搜索 = **定位 + 可跳转播放**。这天然复用现有的「点击段落 → 跳转播放」交互（见 `detail.html` 的点击处理器与 `timeupdate` 高亮）。

## 2. 范围与分期

| 阶段 | 范围 | 入口 | 执行计划 | 价值 |
|------|------|------|---------|------|
| **阶段一** | 单文件内搜索 | 详情页 `/file/<id>` | **P6** | 解决最高频痛点，改动集中在一个页面 |
| **阶段二** | 全局跨文件搜索 | 首页 `/` 顶部 | **P7** | 「这句话是哪场会议说的」 |

> **优先做阶段一（P6）。** 原因：P6 在一个页面内闭环，能完整跑通「搜词 → 高亮 → 导航 → 跳转播放」；P7 只是把范式横向扩展到多文件 + 一个结果列表页。先定下交互范式，避免返工。

## 3. 技术选型

| 维度 | 方案 A：`LIKE '%kw%'` | 方案 B：SQLite FTS5 |
|------|----------------------|-------------------|
| 实现成本 | 零新表、零同步逻辑 | 需建 FTS 虚拟表 + 触发器/手动同步 |
| 中文支持 | ✅ 子串匹配天然友好 | ⚠️ 默认 tokenizer 不分词，需 trigram / jieba |
| 大小写 | `LOWER()` / `COLLATE NOCASE` | 内置不区分 |
| 相关性排序 | ❌ 按时间序 | ✅ bm25 |
| 性能（本项目量级） | 几千~几万段落，毫秒级 | 同样毫秒级 |

**决策：采用方案 A（LIKE）。** 理由：

1. **单用户、单文件几百段、总文件几十~几百**，LIKE 完全够用；
2. **中文用 LIKE 做子串匹配最省心**——FTS5 反而要纠结中文 tokenizer，得不偿失；
3. 不引入 schema 复杂度，符合项目「每阶段独立可验证」的原则。

FTS5 作为「数据量真的大了再上」的升级路径保留（见 [第 11 节](#11-风险与升级路径)）。搜索逻辑收拢到单一函数，将来切换无感。

## 4. 数据层

**不改动 schema。** 直接查现有 `transcript_segments` 表（`file_id` / `start_time` / `end_time` / `text` / `segment_index`）。

### 4.1 查询 SQL（单文件内搜索）

```sql
SELECT id, segment_index, start_time, end_time, text
FROM transcript_segments
WHERE file_id = :file_id
  AND LOWER(text) LIKE :kw ESCAPE '\'
ORDER BY segment_index;
```

- `:kw` 在 Python 侧构造为 `'%' + escape_like(q.lower()) + '%'`；
- 用 `ESCAPE '\'` 转义用户输入的 `%` `_` `\`，避免被当作通配符；
- 中文走 `LOWER()` 无副作用；英文大小写归一。

### 4.2 工具函数（新增到 `utils.py`）

```python
def escape_like(keyword: str) -> str:
    """转义 SQL LIKE 的通配符，使其按字面匹配。

    用于全文搜索：用户输入的 % _ \ 不会被当作通配符。
    """
    return (keyword
            .replace('\\', '\\\\')
            .replace('%', '\\%')
            .replace('_', '\\_'))
```

### 4.3 大小写归一的局限（已知，可接受）

SQLite 内置 `LOWER()` 默认只对 **ASCII** 字符生效。对会议转写以中英为主的场景无影响：

- 中文无大小写，不受影响；
- 英文字母正常归一。

若将来需对带重音的 Unicode 字母（如 `É` → `é`）归一，需启用 SQLite ICU 扩展，超出 MVP 范围。

### 4.4 索引（为 P7 全局搜预留）

```sql
CREATE INDEX ix_segments_file_id ON transcript_segments(file_id);
```

主要服务于 P7 的 `WHERE file_id IN (...)` 与「按文件分组」。P6 单文件查询即使无索引也已是毫秒级，但顺手建好可一并覆盖。

## 5. API 设计

遵循项目「先 GET 后 POST、每个路由手动测试」的规范。

### 5.1 阶段一 — 单文件内搜索

```
GET /api/file/<int:id>/search?q=<关键词>
```

**响应**（200，`application/json`）：

```json
{
  "query": "排期",
  "total": 3,
  "hits": [
    { "segment_index": 12, "start_time": 145.2, "end_time": 150.1,
      "text": "我们这周的排期需要调整" },
    { "segment_index": 28, "start_time": 612.0, "end_time": 618.5,
      "text": "排期能不能往后推一周" }
  ]
}
```

- 后端**只返回命中段落**，**不返回高亮偏移**——高亮由前端完成（理由见 [第 7.3 节](#73-高亮策略由前端完成)）；
- `q` 为空、仅空格、或长度 < 1 → 返回 `{ "query": "", "total": 0, "hits": [] }`，**不报错**；
- 只返回该文件 `status == 'completed'` 的段落（未完成则 `hits` 为空）。

### 5.2 阶段二 — 全局搜索

```
GET /search?q=<关键词>
```

返回 HTML 结果页（按文件分组，每条命中显示 文件名 + 时间戳 + 带高亮的片段 + 跳转链接）。

> 是否提供 JSON 变体 `GET /api/search?q=...` 取决于首页是否做成「即时搜索框」。MVP 先做整页结果页更简单。

## 6. 阶段一交互设计（详情页内搜索栏）

### 6.1 位置与组件

放在转写区标题「📝 转写内容」右侧（参考 [design-spec.md](design-spec.md) 转写段落规范）：

```
🔍 [ 输入框____________ ] [↑ 上一个] [↓ 下一个]   3/12 处命中     [✕ 清除]
```

### 6.2 交互流（对标浏览器 Ctrl+F，产品经理零学习成本）

1. 输入关键词（回车，或防抖 300ms 触发）→ 请求 `GET /api/file/<id>/search`；
2. 所有命中段落加 `.search-hit`（淡黄底）；右侧显示「当前 / 总数」；
3. 自动定位到**第一个**命中 → `.search-current`（深黄底 + 滚动入视图）；
4. `↑ / ↓` 在命中间循环切换（到头回绕）；`Esc` 或 `✕` 清除高亮、恢复原状；
5. **点击任意命中段落** → 复用现有逻辑：`player.currentTime = start; player.play()`，听到原话。

### 6.3 CSS 高亮

沿用设计规范的淡蓝色调；搜索用**黄系**做语义区分，与播放高亮（蓝）共存不冲突：

```css
/* 命中段落 */
.segment-item.search-hit     .segment-text { background: #fff3cd; }
/* 当前定位的命中段 */
.segment-item.search-current .segment-text { background: #ffe082;
                                            box-shadow: 0 0 0 2px #1976d2; }
/* 关键词本身（由前端 <mark> 包裹） */
mark { background: #fff3cd; padding: 0 2px; border-radius: 2px; }
```

## 7. 与现有播放器交互的整合（关键难点）

`detail.html` 现有 JS 在 `player.timeupdate` 里给当前播放段加 `.active` 并 `scrollIntoView`。搜索高亮是**另一层独立视觉**，不冲突，但需协调以下几点。

### 7.1 视觉共存

| 现状 | 搜索加入后 | 处理 |
|------|-----------|------|
| `.active` 跟随播放位置（蓝色竖线） | 新增 `.search-hit` / `.search-current`（黄底） | 两者并存，互不覆盖 |

### 7.2 滚动控制（避免打架）

`timeupdate` 现在会在播放时 `scrollIntoView` 跟随当前段。搜索激活期间若仍跟随，会与「定位到命中段」的滚动互相抢占。

**处理**：给现有 IIFE 加一个 `searchActive` 标志，搜索激活时跳过 `timeupdate` 里的 `scrollIntoView`（**只保留 `.active` 高亮，不滚动**）：

```javascript
player.addEventListener('timeupdate', function() {
    // ... 计算 found ...
    if (found !== currentActive) {
        if (currentActive) currentActive.classList.remove('active');
        if (found) {
            found.classList.add('active');
            if (!searchActive) {                       // ← 搜索激活时不抢滚动
                found.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }
        currentActive = found;
    }
});
```

改动极小（一行条件），不破坏现有播放跟随体验。

### 7.3 高亮策略（由前端完成）

后端不返回偏移量，**前端用大小写不敏感的 `indexOf` 自行高亮**：

```javascript
function highlight(text, q) {
    var ql = q.toLowerCase(), tl = text.toLowerCase();
    var idx = tl.indexOf(ql), out = '', last = 0;
    while (idx !== -1) {
        out += esc(text.slice(last, idx))
            + '<mark>' + esc(text.slice(idx, idx + q.length)) + '</mark>';
        last = idx + q.length;
        idx = tl.indexOf(ql, last);
    }
    return out + esc(text.slice(last));
}
```

**为什么不依赖后端的 `match_offsets`**：Python `str` 按 Unicode 码点索引，JS 字符串按 UTF-16 码元索引。对 BMP 字符（含所有常用中文）两者一致；但对补充平面字符（emoji 等）会错位。让前端独立完成高亮，前后端用同一套 JS 语义，彻底回避这个坑，实现也更简单。

> `esc()` 必须对 `q` 做 HTML 转义防 XSS（关键词来自用户输入）。段落文本本身已是服务端渲染的安全内容，但高亮重建时务必转义。

## 8. 阶段二交互设计（全局搜索结果页）

```
🔎 搜索 "排期" — 共 3 个文件、7 处命中

📁 周度产品评审.mp4                              3 处
   02:25  ...这周的【排期】需要调整...              →跳转
   15:10  ...【排期】能不能往后推一周...             →跳转

📁 客户访谈_张总.m4a                              2 处
   08:42  ...关于【排期】客户希望...                 →跳转
```

- 「→跳转」链接到 `/file/<id>?q=排期&seg=12`；
- **详情页读取 query 参数 `q` / `seg`**：进入即自动填入搜索框、定位到指定命中段，复用阶段一全部逻辑。

## 9. 边界情况清单

| 场景 | 处理 |
|------|------|
| 空查询 / 仅空格 | 不发请求，清除高亮 |
| 无命中 | 显示「未找到「kw」」，高亮清空 |
| 文件未转写完成 | 搜索栏隐藏（与现有 `processing` 占位一致） |
| 英文大小写 | `LOWER()` 归一，显示原文 |
| 含 `%` `_` `\` | `ESCAPE '\'` 转义，按字面匹配 |
| 切换 / 删除文件 | 搜索状态随页面卸载自然清除 |
| 超长转写（几千段） | 单文件 LIKE 仍毫秒级；前端用事件委托，不为每段绑监听 |

## 10. 分阶段任务与验收

### 10.1 P6 — 单文件内搜索

1. `utils.py` 新增 `escape_like()` 工具函数（+ 手动测试）；
2. `app.py` 新增 `GET /api/file/<id>/search` 路由；
3. `templates/detail.html` 增加搜索栏 HTML + JS（请求、高亮、`↑/↓` 导航、清除）；
4. `static/style.css` 增加 `.search-hit` / `.search-current` / `mark` 样式；
5. 协调现有 `timeupdate` 自动滚动（搜索激活期间暂停跟随）。

**验收：**

- [ ] 输入中文 / 英文关键词，所有命中段落高亮；
- [ ] `↑ / ↓` 正确循环切换，当前项滚动入视图且计数正确；
- [ ] 点击命中段跳转播放并能听到原话；
- [ ] 播放时当前段蓝色高亮与搜索黄底共存不闪烁；
- [ ] `Esc` / `✕` 清除高亮，恢复播放跟随滚动；
- [ ] 搜 `50%` 不报错、不误匹配。

### 10.2 P7 — 全局搜索

1. `app.py` 新增 `GET /search`（HTML）路由，按文件分组聚合命中；
2. `templates/search.html` 结果页；
3. `templates/index.html` 导航栏增加搜索框；
4. `templates/detail.html` 支持 `?q=&seg=` 深链定位。

**验收：**

- [ ] 全局搜列出所有命中文件及片段，按文件分组；
- [ ] 点击结果跳到详情页对应位置并自动高亮关键词。

## 11. 风险与升级路径

| 风险 / 触发条件 | 应对 |
|----------------|------|
| 数据量增长到十万级段落、LIKE 变慢 | 切换到 **SQLite FTS5**：建虚拟表 + 触发器同步；中文用 `unicode61` + trigram 或挂 jieba |
| 需要相关性排序（最相关在前） | FTS5 自带 `bm25()` 排序 |
| 需要「错别字 / 同义词」容错 | 引入拼音 / 同义词扩展，或接入向量检索，属更远期 |

切换 FTS5 时，仅需替换第 4.1 节的查询与 `escape_like` 的调用点，前端 API 契约（第 5 节）保持不变——**搜索逻辑收拢在单一函数 / 路由内，切换对外无感**。
