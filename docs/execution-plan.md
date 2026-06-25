# V2W — 分阶段执行计划

> 每个阶段独立可验证，完成后确认再进入下一阶段

## 阶段总览


| 阶段  | 主题          | 预计文件数 | 核心产出                                | 状态  |
| --- | ----------- | ----- | ----------------------------------- | --- |
| P0  | 环境准备        | 3     | 依赖安装、项目骨架、Flask 可启动                 | ✅  |
| P1  | 数据模型        | 2     | SQLite 建表、File/TranscriptSegment 模型 | ✅  |
| P2  | 文件上传与列表     | 4     | 上传路由、首页文件卡片展示                       | ✅  |
| P3  | 转写引擎        | 3     | Whisper 集成、后台线程、状态轮询                | ✅  |
| P4  | 详情页与播放器     | 3     | 播放器、转写文字列表、点击跳转                     | ✅  |
| P5  | UI 美化       | 2     | 淡蓝主题、动画、响应式                         | ✅  |
| P6  | 全文搜索（单文件内）  | 3     | 详情页内关键词搜索、高亮、导航、跳转播放                | ✅  |
| P7  | 全文搜索（全局）    | 2     | 首页跨文件搜索、结果页、深链定位                    | ✅  |
| P8  | 导出 Markdown | 2     | 详情页导出 .md（说话人 tag + 时间戳 + 文字）       | ✅  |
| P9  | 说话人分离       | 3     | pyannote 区分说话人，详情页/导出归属（开关按需）       | ✅（a/b 完成，c 待定） |
| P10 | AI 会议总结      | 3     | 摘要 + 行动项/待办 + 关键词（LLM，本地优先）          | 📋 规划中（[设计](summary-design.md)） |


---

## P0 — 环境准备 ✅ 优先级最高

**目标**：项目可以 `python app.py` 启动，浏览器看到 Hello World

### 任务清单

- [x] 安装 FFmpeg：`brew install ffmpeg`
- [x] 创建 `requirements.txt`（flask, flask-sqlalchemy, faster-whisper）
- [x] `pip install -r requirements.txt`
- [x] 创建 `config.py`（配置类：DB 路径、上传目录、模型参数）
- [x] 创建 `app.py`（Flask 最小应用，`/` 返回 Hello World）
- [x] 创建 `templates/base.html`（空骨架）
- [x] 启动验证：浏览器看到页面

### 验证标准

```bash
python app.py
# → Running on http://0.0.0.0:8080
# 浏览器打开 → 显示首页文件库
```

---

## P1 — 数据模型 ✅

**目标**：SQLite 数据库就绪，可直接在 Python 中 CRUD

### 任务清单

- [x] 创建 `models.py`：File 模型 + TranscriptSegment 模型
- [x] 在 `app.py` 中初始化 SQLAlchemy + 自动建表
- [x] 写一个测试脚本或路由验证数据库读写

### 验证标准

```python
# 启动应用 → 自动创建 instance/v2w.db
# 可通过 Python shell 添加/查询 File 记录
```

---

## P2 — 文件上传与文件库 ✅

**目标**：网页上传文件 → 首页看到文件卡片

### 任务清单

- [x] 创建 `utils.py`：文件校验（格式白名单、大小限制）
- [x] `app.py` 添加 `POST /upload` 路由
- [x] 创建 `templates/index.html`：文件卡片网格 + 空状态
- [x] `app.py` 添加 `GET /` 路由，查询所有文件渲染首页
- [x] `POST /file/<id>/delete` 删除路由

### 验证标准

- 上传 mp3 文件 → 首页出现卡片显示文件名 + "已上传" 状态
- 上传非白名单格式 → 返回错误提示
- 删除文件 → 文件从列表消失

---

## P3 — 转写引擎 ✅

**目标**：上传后自动后台转写，前端感知状态变化

### 任务清单

- [x] 创建 `transcriber.py`：封装 faster-whisper 加载与转写
- [x] 创建 `worker.py`：后台线程管理（队列 + 单任务处理）
- [x] `app.py` 添加 `GET /api/file/<id>/status` JSON 接口
- [x] `app.py` 添加 `GET /api/file/<id>/segments` JSON 接口
- [x] 首页 JS 轮询状态，自动刷新卡片

### 验证标准

- 上传音频 → 状态自动变为 "处理中" → 变为 "已完成"
- 数据库中有转写段落数据
- 转写过程中上传第二个文件 → 排队，等第一个完成

---

## P4 — 详情页与播放 ✅

**目标**：详情页播放音视频 + 转写文字 + 点击跳转

### 任务清单

- [x] 创建 `templates/detail.html`：播放器 + 转写文字区
- [x] `app.py` 添加 `GET /file/<id>` 路由
- [x] 播放器支持 video/audio 类型切换
- [x] JS：点击文字段落 → 播放器 `currentTime` 跳转
- [x] JS：播放中自动高亮当前段落

### 验证标准

- 点击首页卡片 → 进入详情页
- 视频文件看到画面，音频文件看到播放器
- 点击某段文字 → 播放器跳到对应时间开始播放
- 播放中 → 对应段落高亮

---

## P5 — UI 美化 ✅

**目标**：淡蓝主题，良好视觉体验

### 任务清单

- [x] 创建 `static/style.css`：完整样式（按设计规范）
- [x] `base.html` 加入导航栏
- [x] 首页卡片动画（悬停、状态脉冲）
- [x] 详情页段落交互优化
- [x] 空状态、错误状态友好提示

### 验证标准

- 页面以淡蓝白为主色调
- 卡片悬停有动效
- 处理中状态有脉冲动画
- 整体整洁、专业感

---

## P6 — 全文搜索（单文件内） ✅

> 对应 [search-design.md](search-design.md) 阶段一，**优先实现**

**目标**：在详情页内输入关键词，快速定位转写内容并跳转播放

### 任务清单

- [x] `utils.py` 新增 `escape_like()` 工具函数（转义 SQL LIKE 通配符）
- [x] `app.py` 新增 `GET /api/file/<id>/search` 路由
- [x] `templates/detail.html` 增加搜索栏 + JS（请求、高亮、`↑/↓` 导航、清除）
- [x] `static/style.css` 增加 `.search-hit` / `.search-current` / `mark` 样式
- [x] 协调现有 `timeupdate` 自动滚动：搜索激活期间暂停跟随

### 验证标准

- 输入中 / 英文关键词 → 所有命中段落高亮，右侧显示「当前 / 总数」
- `↑ / ↓` 循环切换命中项，当前项滚动入视图
- 点击命中段 → 播放器跳转并能听到原话
- 播放跟随高亮（蓝）与搜索高亮（黄）共存不闪烁
- `Esc` / `✕` 清除高亮并恢复播放跟随
- 搜索含 `%` `_` 不报错、不误匹配

---

## P7 — 全文搜索（全局） ✅

> 对应 [search-design.md](search-design.md) 阶段二

**目标**：跨文件搜索「某句话是哪场会议说的」，结果直达对应位置

### 任务清单

- [x] `app.py` 新增 `GET /search` 路由：文件名查询 + 转写查询（join，按文件分组）+ `tab` 参数 + 三类计数 + `highlight` 过滤器
- [x] `templates/search.html` 结果页：Tab 栏（全部/项目名/转文字）+ 项目名命中块 + 内容命中块 + 空态
- [x] `templates/base.html` 导航栏全局搜索框
- [x] `templates/detail.html` 支持 `?q=&seg=` 深链：进入即填入关键词并定位

### 验证标准

- 项目名命中：文件名含关键词的文件列出（含未转写完成），文件名高亮
- 转写命中：跨文件列出命中片段，按文件分组
- Tab 切换（全部/项目名/转文字）计数正确、当前高亮
- 「全部」分两块（项目名命中 + 内容命中）
- 点击转写结果 → 跳转详情页并自动定位高亮关键词
- 全无命中 / 某分类无结果 两种空状态正确

---

## P8 — 导出 Markdown ✅

> 对应需求：导出已转写内容为 Markdown 文档

**目标**：详情页一键导出当前文件的转写文字为 .md

### 任务清单

- [x] `utils.py` 新增 `speaker_label()`（统一占位「发言人」，预留 speaker 扩展点）+ `segments_to_markdown()`
- [x] `app.py` 新增 `GET /file/<id>/export`：生成 md + 中文文件名 RFC 5987 编码下载
- [x] `templates/detail.html` 已完成文件显示「导出 Markdown」按钮
- [x] `static/style.css` 导出按钮（描边样式）

### 验证标准

- 已完成文件 → 下载 .md，含标题 / 元信息 / 每段（发言人 tag + 时间戳 + 文字）
- 未完成文件 → 提示并重定向，不导出
- 中文文件名下载不乱码
- 说话人 tag 统一占位，预留 speaker 字段扩展

---

## P9 — 说话人分离（pyannote · 开关按需） ✅

> 对应 [speaker-diarization-design.md](speaker-diarization-design.md)；前置 HF token 见 [hf-token-setup.md](hf-token-setup.md)。

**目标**：区分「谁在说话」，段落归属到说话人；导出从 `[发言人]` 自动变为「说话人 N」。

### 任务清单（P9a）

- [x] `config.py` 加 `DIARIZATION_ENABLED` + `HF_TOKEN`
- [x] `models.py` `TranscriptSegment` 加 `speaker` 字段 + 启动自动迁移加列
- [x] 新建 `diarizer.py`（pyannote 加载 + diarize + assign_speakers 对齐）
- [x] `transcriber.py` 开 `word_timestamps=True`
- [x] `worker.py` 开关分支：diarize + 对齐，写 speaker；token 缺失优雅降级
- [x] `utils.py` `speaker_label()` 读 `seg.speaker` + 友好映射（说话人 1/2/3）
- [x] `detail.html` 段落显示说话人；`index.html` 上传勾选「识别说话人」
- [x] `app.py` 上传接 `diarize` 参数

### 验证标准

- 勾选上传 → 段落带 speaker，详情页显示「说话人 N」
- 导出 md 显示「**说话人 N**」（衔接 speaker_label 预留点）
- 不勾选 → 行为不变，全 `[发言人]`
- 现有库升级不丢数据（speaker 为 NULL，显示占位）
- token 缺失时优雅降级，转写正常

### P9b — 说话人重命名 + 单段勘误 + 重新识别 ✅

- [x] 详情页说话人重命名（SPEAKER_00 → 张总），按文件维度存 `FileSpeaker`
- [x] 单段说话人勘误（`POST /segment/<seg_id>/speaker`）
- [x] 历史文件「重新识别说话人」按钮（`POST /file/<id>/rediarize`，重置 segments 后入队）
- [x] `speaker_display` 优先读 `FileSpeaker`，回退「说话人 N」

### 后续（待定）

- P9c：按说话人筛选 / 统计

---

## P10 — AI 会议总结 📋

> 对应 [summary-design.md](summary-design.md)；把逐字稿升级为「会议纪要」（摘要 + 行动项 + 关键词）。

**目标**：已完成转写的文件，一键生成会议摘要、待办事项、关键词，定位产品经理核心场景。

**技术路线**：复用 worker 队列新增 `('summarize', id)` 任务；LLM provider 抽象，默认本地 Ollama（隐私优先），云端 API 可选。

### 任务清单（P10a）

- [ ] `models.py` 新增 `Summary` 表（摘要 / action_items / keywords / provider / model）
- [ ] 新建 `summarizer.py`（拼接逐字稿 / 长文本 map-reduce / provider 抽象 / 容错 JSON 解析）
- [ ] `config.py` 加总结配置（`LLM_PROVIDER` / `OLLAMA_*` / `OPENAI_*`，环境变量 + .env）
- [ ] `worker.py` 新增 `('summarize', id)` 任务 + `enqueue_summarize()`
- [ ] `app.py` 加 `POST /file/<id>/summarize`（入队）+ `GET /api/file/<id>/summary`（取结果）
- [ ] `detail.html` 总结面板（摘要 / 待办 / 关键词）+ 生成按钮 + 状态轮询

### 验证标准

- 已完成文件 → 点「生成总结」→ 显示摘要 + 待办 + 关键词
- 长会议（>1h）map-reduce 不截断
- Ollama 未运行 → 按钮提示，不报错、不影响转写/搜索/导出

### 后续

- P10b：行动项勾选标记 + 关键词联动搜索 + 导出 md 并入总结区块
- P10c（可选）：云端 API provider + 转写完成自动总结 + SSE 流式

---

## 各阶段依赖关系

```
P0 ──→ P1 ──→ P2 ──→ P3 ──→ P4 ──→ P5
                                  └── P2+P3 都完成即可开始
P4 ──→ P6（单文件内搜索）──→ P7（全局搜索）
P4 ──→ P8（导出 Markdown）
P3 ──→ P9（说话人分离，依赖 ASR 管线）
P3 ──→ P10（AI 总结，依赖逐字稿；P9 让待办归属到人更准）
```

