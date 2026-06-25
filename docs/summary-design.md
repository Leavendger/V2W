# V2W — AI 会议总结详细设计

> 把逐字稿变成「会议纪要」：摘要 + 行动项/待办 + 关键词。
>
> 对应执行计划：**P10（AI 会议总结）**，详见 [execution-plan.md](execution-plan.md)。
>
> 前置依赖：转写已完成（P3）。说话人分离（P9）非必需，但能让总结更准（「谁要做什么」）。

## 1. 背景与目标

当前详情页/导出只有**逐字稿**（全文 + 时间戳 + 说话人）。PM 开完会没有时间通读 1 小时的逐字稿，真正要的是三件事：**结论是什么、谁要做什么、关键词**。

### 1.1 核心痛点（产品经理视角）

- 「这场会聊了啥？给我 3 分钟看完。」
- 「会后要跟进的事项有哪些？分别是谁的？」
- 「老板拍板的结论在哪？直接定位原话。」

### 1.2 核心价值

AI 总结 = **消化**。完成后 V2W 从「转写器」升级为真正的「会议助手」，直接命中目标人群（产品经理）的核心场景。技术上输入现成（逐字稿 + 说话人 + 时间戳），只需加一次 LLM 调用即可同时产出摘要 / 待办 / 关键词三项。

## 2. 现状与难点

### 2.1 现有产物已是优质输入

`TranscriptSegment`（`text` + `speaker` + `start_time/end_time`）天然适合喂给 LLM——带说话人归属、可按时间分段。无需改造转写管线。

### 2.2 难点一：长文本超上下文

1 小时会议逐字稿中文约 **8000–15000 字（≈ 1.5 万–2.5 万 token）**。多数本地模型单次可吞，但保险起见需**分段 map-reduce**，避免超长会议被截断或质量下降。

### 2.3 难点二：LLM 来源选择

| 维度 | 本地 Ollama | 云端 API |
|------|------------|----------|
| 隐私 | ✅ 全程本地，符合项目调性 | ⚠️ 文本出域 |
| 质量 | 中（7B/14B） | 高 |
| 成本 | 零（电费） | 按量计费 |
| 部署 | 需本地跑 Ollama + 拉模型 | 一个 API key |

### 2.4 难点三：结构化输出

摘要 / 待办 / 关键词要稳定 schema（前端要分别渲染），不能让模型自由发挥。需用 **JSON 约束 prompt + 容错解析**。

### 2.5 难点四：耗时

LLM 推理几秒到几十秒，**不能阻塞请求**。复用现有 `worker.py` 单线程队列（与转写同一套机制），新增 `('summarize', file_id)` 任务类型。

## 3. 技术选型

| 方案 | 做法 | 隐私 | 质量 | 依赖 | 决策 |
|------|------|------|------|------|------|
| **A · 本地 Ollama** | `summarizer.py` 调本地 Ollama HTTP API | ✅ 全本地 | 中 | 装 Ollama + 拉模型 | ✅ **默认** |
| **B · 云端 API** | OpenAI / Claude / 通义 / 智谱 兼容接口 | ⚠️ 出域 | 高 | API key + 联网 | ✅ **可选 provider** |
| C · 规则提取 | 正则 + TF-IDF 关键词，无 LLM | ✅ | 低 | 无 | ✗（质量不达标） |

**决策：抽象 LLM provider 接口，默认 Ollama（贴合 README「本地处理、隐私安全」定位），云端 API 作为可切换 provider。** 两者共用同一套 prompt 与解析逻辑，`config.LLM_PROVIDER` 切换。

## 4. 数据模型

新增 `Summary` 表（一文件一份总结，重新生成覆盖）：

```python
class Summary(db.Model):
    __tablename__ = 'summaries'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False, unique=True)
    summary_text = db.Column(db.Text, nullable=True)          # 会议摘要（几句话）
    action_items = db.Column(db.Text, nullable=True)          # JSON: [{text, owner?, due?}, ...]
    keywords = db.Column(db.Text, nullable=True)              # JSON: ["关键词1", "关键词2", ...]
    provider = db.Column(db.String(32), nullable=True)        # ollama / openai / ...
    model_name = db.Column(db.String(64), nullable=True)      # qwen2.5:7b / gpt-4o-mini / ...
    created_at = db.Column(db.DateTime, default=datetime.now)
    error_message = db.Column(db.Text, nullable=True)         # 生成失败原因
```

- `db.create_all()` 自动建表，**不改任何旧表**，零迁移风险；
- `File` 加 `summary_status` 软状态（`none / summarizing / done / failed`），或直接以「`Summary` 是否存在 + `error_message`」判断，避免给 `files` 加列。

## 5. 总结管线（复用 worker 队列）

`worker.py` 已有 `('transcribe', id)` / `('rediarize', id)` 任务元组与单线程队列，**新增 `('summarize', id)` 同构任务**：

```
转写完成（已有）
   → [新] 拼接逐字稿（按说话人合并相邻段，带时间，压成喂 LLM 的纯文本）
   → [新] 长文本分段（超阈值走 map-reduce：分段总结 → 合并）
   → [新] LLM 调用（provider 抽象，结构化 JSON prompt）
   → [新] 容错解析 → 写 Summary 表
   → 状态 summarizing → done（失败 → failed + error_message）
```

### 5.1 触发时机

- **手动**（MVP）：详情页「生成总结」按钮，已完成转写的文件可点；
- **自动**（可选，P10c）：转写完成后自动入队（`SUMMARY_AUTO` 开关，默认关，避免无谓消耗）。

### 5.2 文本拼接（复用现有能力）

直接用 `TranscriptSegment` 查询 + `utils.speaker_label()` 拼接，复用 P9 的友好说话人标签：

```
[说话人 1 · 00:12] 我们下个版本优先做搜索功能……
[说话人 2 · 01:05] 那我来排期，周五前给到……
```

## 6. summarizer.py 设计

```python
# summarizer.py（新增）
def summarize_segments(segments, file_record, provider, model):
    """主入口：逐字稿 → {summary, action_items, keywords}。
    1. 拼接文本（带说话人 + 时间）
    2. 超阈值 → map-reduce 分段总结再合并
    3. 调 provider 生成结构化 JSON
    4. 容错解析返回 dict
    """
    text = build_transcript_text(segments)          # 复用 speaker_label
    if estimate_tokens(text) > CHUNK_THRESHOLD:
        text = map_reduce_summarize(text, provider, model)
    raw = call_llm(SUMMARY_PROMPT, text, provider, model)
    return parse_summary_json(raw)                  # 容错：JSON 修复 / 正则兜底

# provider 抽象（两个实现共用 prompt）
def call_llm(prompt, text, provider, model):
    if provider == 'ollama':
        return _call_ollama(prompt, text, model)    # POST http://localhost:11434/api/generate
    if provider == 'openai':
        return _call_openai(prompt, text, model)    # 兼容 OpenAI / 通义 / 智谱的 /chat/completions
    raise ValueError(f'unknown provider: {provider}')
```

### 6.1 结构化 prompt（示例）

```
你是会议纪要助手。基于以下带说话人的逐字稿，输出严格 JSON：
{
  "summary": "3-5 句话概括会议结论与讨论",
  "action_items": [{"text": "待办事项", "owner": "负责人（无则空）", "due": "截止（无则空）"}],
  "keywords": ["3-8 个关键词"]
}
只输出 JSON，不要多余解释。

逐字稿：
{text}
```

### 6.2 长文本 map-reduce

按 ~15 分钟 / ~4000 字切块 → 每块单独总结 → 把各块总结再合并成最终摘要。待办/关键词则去重合并。

## 7. 配置项

`config.py` 新增（风格对齐 `HF_TOKEN`，环境变量优先 + 本地 `.env` 回退）：

```python
# AI 总结（迭代 P10）
SUMMARY_ENABLED = os.environ.get('SUMMARY_ENABLED', 'true').lower() == 'true'
LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'ollama')   # ollama / openai
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b')   # 中文友好
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') or _LOCAL_ENV.get('OPENAI_API_KEY')
OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')  # 可指向通义/智谱
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
SUMMARY_AUTO = False       # 转写完成后是否自动总结（默认关）
```

## 8. 前置条件

### 8.1 本地 Ollama（默认）

```bash
brew install ollama && ollama serve
ollama pull qwen2.5:7b     # 中文好、~4.7GB；显存够可上 qwen2.5:14b
```

### 8.2 云端 API（可选）

`.env` 配 `OPENAI_API_KEY`，或把 `OPENAI_BASE_URL` 指向通义/智谱的兼容端点。**注意告知用户：开启云端 provider 会把逐字稿文本发送到外部服务。**

## 9. 前端交互

- 详情页已完成转写 → 显示「✨ 生成总结」按钮；
- 总结面板：**摘要**（段落）+ **行动项**（checklist，可勾选标记完成）+ **关键词**（chips，点击联动全文搜索 P6）；
- 「重新生成」按钮（覆盖 `Summary`）；生成中显示 loading / 轮询状态；
- MVP 先**非流式**（等整段返回）；P10c 再考虑 SSE 流式。

## 10. 风险与降级

| 风险 | 应对 |
|------|------|
| Ollama 未运行 / 模型未拉 | 按钮前置检测，不可用时置灰 + 提示安装，不影响转写/搜索/导出 |
| 云端 API key 缺失 / 失败 | 同上降级；记录 `error_message`，可重试 |
| 超长会议超时 | map-reduce 分段 + 单段超时重试 |
| 输出非合法 JSON | 容错解析（提取首个 `{...}`、修复尾逗号、正则兜底）；仍失败则记 `error_message` |
| 隐私（云端出域） | 默认本地；切云端时 UI 明确提示 |
| 成本（云端计费） | `SUMMARY_AUTO` 默认关，手动触发为主 |

## 11. 对现有功能的影响

| 功能 | 影响 |
|------|------|
| 转写 / 搜索 / 导出 | **零影响**（独立表 + 独立任务，不碰现有管线） |
| 导出 Markdown | 可选：在逐字稿前追加「总结区块」（摘要 + 待办 + 关键词） |
| 详情页 | 新增总结面板（与播放器/转写并列） |
| worker 队列 | 复用，新增一种任务类型，不影响转写调度 |

## 12. 分期任务与验收

### 12.1 P10a — 本地总结 + 详情页展示

1. `models.py` 新增 `Summary` 表；
2. 新建 `summarizer.py`（拼接 / map-reduce / provider 抽象 / Ollama 实现 / 容错解析）；
3. `config.py` 加总结配置项；
4. `worker.py` 新增 `('summarize', id)` 任务 + `enqueue_summarize()`；
5. `app.py` 加 `POST /file/<id>/summarize`（入队）+ `GET /api/file/<id>/summary`（取结果）；
6. `detail.html` 总结面板（摘要 / 待办 / 关键词）+ 生成按钮 + 状态轮询。

**验收：**

- [ ] 已完成文件 → 点「生成总结」→ 面板显示摘要 + 待办 + 关键词；
- [ ] 长会议（>1h）也能完整总结（map-reduce 生效，不截断）；
- [ ] Ollama 未运行 → 按钮提示，不报错、不影响其他功能；
- [ ] 重新生成覆盖旧结果。

### 12.2 P10b — 待办勾选 + 导出并入

- 行动项 checklist 可勾选（本地标记完成状态，存 `Summary.action_items` 的 `done` 字段）；
- 关键词 chips 点击 → 联动详情页全文搜索（复用 P6）；
- 导出 Markdown 在标题下追加「总结区块」。

### 12.3 P10c（可选）— 云端 API + 自动 + 流式

- 接 OpenAI / 通义 / 智谱兼容 API（`provider='openai'`）；
- `SUMMARY_AUTO` 转写完成自动总结；
- SSE 流式输出，边生成边显示。

---

## 附录：与现有阶段的依赖

```
P3（转写）──→ P10a（总结，依赖逐字稿）
P9（说话人，可选）──→ 让 P10 的「待办归属到人」更准
```

> 远期可演进：章节自动划分（基于关键词/话题转折分段）、实时录音总结、多语言翻译。
