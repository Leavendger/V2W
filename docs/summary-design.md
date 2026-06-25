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

| 方案 | 做法 | 隐私 | 质量 | 部署 | 决策 |
|------|------|------|------|------|------|
| **A · 云端 API（多厂商）** | OpenAI 兼容协议，配置驱动切换 DeepSeek / GLM / MiMo / 通义 / OpenAI | ⚠️ 出域 | 高 | 服务器零负担 | ✅ **默认** |
| B · 本地 Ollama | 同走 OpenAI 兼容端点（Ollama `/v1`） | ✅ 本地 | 中 | 需 GPU/大内存 | ✅ **可选 provider** |
| C · 规则提取 | 正则 + TF-IDF 关键词，无 LLM | ✅ | 低 | — | ✗（质量不达标） |

**决策：云端 API 为主（后期部署到服务器，无需本地算力），provider 抽象 + 多厂商预设，配置文件一键切换。** 关键简化——主流厂商（DeepSeek / 智谱 GLM / MiMo / 通义 / Kimi / OpenAI）乃至本地 Ollama **全都提供 OpenAI 兼容的 `/chat/completions`**，因此 `summarizer.py` 只需**一套** HTTP 客户端，provider 只是 `{base_url, model, api_key}` 三元组，靠预设表驱动，换厂商零代码改动。

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
# summarizer.py（新增）—— 一套 OpenAI 兼容客户端，provider 靠预设表驱动
def summarize_segments(segments, file_record):
    """主入口：逐字稿 → {summary, action_items, keywords}。"""
    text = build_transcript_text(segments)          # 复用 utils.speaker_label
    if estimate_tokens(text) > CHUNK_THRESHOLD:
        text = map_reduce_summarize(text)           # 分段总结再合并
    raw = chat_complete(SUMMARY_PROMPT, text)       # 统一走 OpenAI 兼容协议
    return parse_summary_json(raw)                  # 容错：JSON 修复 / 正则兜底

def chat_complete(prompt, text):
    """唯一的 LLM 调用入口。从 config 取当前 provider 预设，POST /chat/completions。
    DeepSeek / GLM / MiMo / 通义 / OpenAI / Ollama(/v1) 全走这一条。"""
    p = current_llm_provider()                      # {base_url, model, api_key}
    resp = requests.post(
        f"{p['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {p['api_key']}"},
        json={"model": p["model"],
              "messages": [{"role": "user", "content": f"{prompt}\n\n{text}"}],
              "response_format": {"type": "json_object"},  # 支持 JSON 模式更稳
              "temperature": 0.3},
        timeout=120)
    return resp.json()["choices"][0]["message"]["content"]
```

> **不为每家厂商写单独实现。** `response_format: json_object` 在 DeepSeek / GLM / 通义 / OpenAI 上均支持；不支持的厂商靠 prompt 约束 + 容错解析兜底。Ollama 也开 `/v1/chat/completions` 兼容端点，作为零出域备选 provider 接进来无需额外代码。

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

## 7. 配置项（多 provider 预设，配置文件驱动切换）

两层配置：**预设表**（可入 git 的示例，用户可自由编辑增删厂商）+ **当前选择与密钥**（环境变量 / `.env`，不入 git）。

### 7.1 预设表 `llm_providers.json`（项目根，入 git 作示例）

```json
{
  "deepseek": { "display": "DeepSeek",   "base_url": "https://api.deepseek.com/v1",            "model": "deepseek-chat",  "api_key_env": "DEEPSEEK_API_KEY" },
  "glm":      { "display": "智谱 GLM",   "base_url": "https://open.bigmodel.cn/api/paas/v4",  "model": "glm-4-flash",    "api_key_env": "GLM_API_KEY" },
  "mimo":     { "display": "MiMo",       "base_url": "https://api.mimo.example/v1",            "model": "mimo-xxx",       "api_key_env": "MIMO_API_KEY" },
  "qwen":     { "display": "通义千问",   "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "api_key_env": "DASHSCOPE_API_KEY" },
  "openai":   { "display": "OpenAI",     "base_url": "https://api.openai.com/v1",              "model": "gpt-4o-mini",    "api_key_env": "OPENAI_API_KEY" },
  "ollama":   { "display": "本地 Ollama", "base_url": "http://localhost:11434/v1",             "model": "qwen2.5:7b",     "api_key_env": "" }
}
```

### 7.2 config.py（读预设 + 当前选择）

```python
# AI 总结（迭代 P10）
SUMMARY_ENABLED = os.environ.get('SUMMARY_ENABLED', 'true').lower() == 'true'
LLM_PROVIDER    = os.environ.get('LLM_PROVIDER', 'deepseek')   # 预设表里的 key
LLM_PROVIDERS   = _load_providers('llm_providers.json')         # 读预设表
SUMMARY_AUTO    = False       # 转写完成后是否自动总结（默认关）

def current_llm_provider():
    """解析当前 provider：预设 + 对应环境变量的 api_key。"""
    p = LLM_PROVIDERS[LLM_PROVIDER]
    key = os.environ.get(p['api_key_env']) or _LOCAL_ENV.get(p['api_key_env'])
    return {**p, 'api_key': key or 'ollama'}   # Ollama 无需 key
```

**切换厂商**：`.env` 改 `LLM_PROVIDER=glm` + 配 `GLM_API_KEY`，重启即可，**零代码改动**。
**加新厂商**：在 `llm_providers.json` 加一行预设 + 配对应 key 环境变量。
**默认 DeepSeek**：国内直连、便宜（约 ¥1/百万 token）、中文强、JSON 模式稳。

## 8. 前置条件

### 8.1 云端 API key（默认路径）

选定一家，在 `.env` 配 `LLM_PROVIDER` + 对应 key（预设表 `api_key_env` 指定的变量名）：

```bash
# .env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx
```

> 国内服务器部署：DeepSeek / GLM / 通义 均国内直连，无需代理。OpenAI 需代理或把 `base_url` 指向中转。

### 8.2 本地 Ollama（可选，零出域备选）

```bash
brew install ollama && ollama serve
ollama pull qwen2.5:7b
# .env: LLM_PROVIDER=ollama
```

> **隐私提示**：云端 provider 会把逐字稿文本发送到外部服务，UI 切换时明确告知；需要全程不出域时用 Ollama。

## 9. 前端交互

- 详情页已完成转写 → 显示「✨ 生成总结」按钮；
- 总结面板：**摘要**（段落）+ **行动项**（checklist，可勾选标记完成）+ **关键词**（chips，点击联动全文搜索 P6）；
- 「重新生成」按钮（覆盖 `Summary`）；生成中显示 loading / 轮询状态；
- MVP 先**非流式**（等整段返回）；P10c 再考虑 SSE 流式。

## 10. 风险与降级

| 风险 | 应对 |
|------|------|
| provider 不可用（key 缺失 / 欠费 / 限流 / 超时） | 按钮前置检测可用性，不可用置灰 + 提示；失败记 `error_message` 可重试；不影响转写/搜索/导出 |
| 超长会议超时 | map-reduce 分段 + 单段超时重试 |
| 输出非合法 JSON / 各家稳定性不一 | 优先 `response_format: json_object`；不支持则强约束 prompt + 容错解析（提取 `{...}`、修复尾逗号、正则兜底） |
| 隐私（逐字稿出域） | UI 切云端 provider 时明确提示；本地 Ollama 为零出域备选 |
| 成本（云端计费） | `SUMMARY_AUTO` 默认关，手动触发为主；UI 可显示所用 provider/模型 |

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
2. 新建 `summarizer.py`（拼接 / map-reduce / 统一 OpenAI 兼容客户端 / 容错解析）；
3. `config.py` 加总结配置 + `llm_providers.json` 多厂商预设表 + `current_llm_provider()`；
4. `worker.py` 新增 `('summarize', id)` 任务 + `enqueue_summarize()`；
5. `app.py` 加 `POST /file/<id>/summarize`（入队）+ `GET /api/file/<id>/summary`（取结果）；
6. `detail.html` 总结面板（摘要 / 待办 / 关键词）+ 生成按钮 + 状态轮询。

**验收：**

- [ ] 已完成文件 → 点「生成总结」→ 面板显示摘要 + 待办 + 关键词；
- [ ] 长会议（>1h）也能完整总结（map-reduce 生效，不截断）；
- [ ] Ollama 未运行 → 按钮提示，不报错、不影响其他功能；
- [ ] 重新生成覆盖旧结果。

### 12.2 P10b — 待办勾选 + 导出并入 ✅

- [x] 行动项 checklist 可勾选（就地切换，乐观更新 + 失败回滚，存 `Summary.action_items` 的 `done` 字段）
- [x] 关键词 chips 点击 → 联动详情页全文搜索（复用 P6，dispatchEvent input）
- [x] 导出 Markdown 在标题下追加「总结区块」（摘要 + 行动项 `[ ]/[x]` + 关键词）
- [x] action_items 存储升级为 `[{text, done}]`，`_normalize_actions` 兼容旧字符串数据

### 12.3 P10c（可选）— 自动 + 流式 + provider 管理页

- `SUMMARY_AUTO` 转写完成自动总结；
- SSE 流式输出，边生成边显示；
- 设置页可视化编辑 `llm_providers.json`（增删厂商）、切换默认 provider。

---

## 附录：与现有阶段的依赖

```
P3（转写）──→ P10a（总结，依赖逐字稿）
P9（说话人，可选）──→ 让 P10 的「待办归属到人」更准
```

> 远期可演进：章节自动划分（基于关键词/话题转折分段）、实时录音总结、多语言翻译。
