# V2W — 技术规范文档

> MVP 版本技术选型与架构设计

## 1. 技术栈

| 层 | 技术 | 版本 | 选型理由 |
|---|------|------|---------|
| 语言 | Python | 3.11 | 说话人分离 pyannote.audio 3.1.1 需 3.11 + 黄金依赖组合，统一版本 |
| Web 框架 | Flask | 3.1 | 轻量成熟，适合 MVP |
| ORM | Flask-SQLAlchemy | 3.x | 数据库操作便捷 |
| 数据库 | SQLite | — | 零配置，单文件，无需安装服务（启用 WAL 提升并发写入） |
| ASR 引擎 | faster-whisper | 1.x | 基于 CTranslate2，比 openai-whisper 快 4 倍 |
| 说话人分离 | pyannote.audio | 3.1.1 | 工业级 diarization（迭代 P9，需 HF token） |
| 音频处理 | FFmpeg | 8.x | 业界标准，视频提取音频 / 损坏头容错转 wav |
| 前端 | Jinja2 + 原生 JS | — | 无构建工具，直接渲染 |
| 异步任务 | Python threading | — | 单用户 MVP 足够（队列 + 单任务处理） |

> **黄金依赖组合**（pyannote 3.1.1 兼容性要求）：torch 2.0.1 / torchaudio 2.0.2 / numpy<2 / huggingface_hub<0.20 / setuptools<70。详见 `requirements.txt`。

## 2. 架构图

```
浏览器 (HTML5 / 原生 JS)
    │
    ├── GET  /                              → 首页（文件卡片库 + 全局搜索框）
    ├── POST /upload                        → 上传文件（diarize 开关：识别说话人 / 快速转写）
    ├── GET  /file/<id>                     → 详情页（播放器 + 转写 + 单文件搜索）
    ├── GET  /search                        → 全局搜索（项目名 + 转写文字，三类 Tab）
    ├── GET  /file/<id>/export              → 导出 Markdown
    ├── POST /file/<id>/speaker/<key>/rename → 说话人重命名 SPEAKER_00 → 张总（P9b）
    ├── POST /segment/<seg_id>/speaker      → 单段说话人勘误（P9b）
    ├── POST /file/<id>/rediarize           → 历史文件重新识别说话人（P9b）
    ├── POST /file/<id>/summarize           → AI 会议总结（手动触发，P10）
    ├── GET  /api/file/<id>/summary         → 取总结结果（轮询，P10）
    ├── GET  /api/file/<id>/status          → JSON 文件状态查询
    ├── GET  /api/worker/status             → JSON worker 队列状态（终止反馈轮询）
    └── GET  /uploads/<path>                → 静态文件服务
         │
    Flask (app.py)
         │
    ┌────┴────┐
    │         │
  models.py  worker.py            ← 单任务队列 + 后台线程
  (SQLite)      │
                ├── transcriber.py   (faster-whisper 转写，开 word_timestamps)
                ├── diarizer.py      (pyannote 分离 + assign_speakers 对齐，token 缺失优雅降级)
                ├── summarizer.py    (AI 总结，统一 OpenAI 兼容客户端 + map-reduce，P10)
                └── utils.py         (文件校验 / ffmpeg 提取音频 / speaker_label / 导出 md)
```

## 3. 项目文件结构

```
V2W/
├── app.py                # Flask 应用入口 + 路由注册
├── config.py             # 配置（DB路径、上传目录、模型参数）
├── models.py             # SQLAlchemy 数据模型
├── transcriber.py        # Whisper 转写封装（word 级时间戳）
├── diarizer.py           # pyannote 说话人分离 + 对齐（P9）
├── worker.py             # 后台转写任务线程管理（队列 + 单任务串行）
├── utils.py              # 工具函数（文件校验、音频提取、speaker_label、导出 md）
├── requirements.txt      # Python 依赖清单
├── uploads/              # 上传文件存储目录
├── static/
│   └── style.css         # 全局样式
├── templates/
│   ├── base.html         # 公共布局骨架（含全局搜索框）
│   ├── index.html        # 首页：文件卡片库
│   ├── detail.html       # 详情页：播放器 + 转写 + 单文件搜索
│   └── search.html       # 全局搜索结果页（P7）
├── docs/                 # 项目规范文档
├── dev_logs/             # 开发日志
└── README.md             # 项目说明
```

## 4. 数据模型

### File 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER (PK) | 自增主键 |
| filename | VARCHAR(256) | 原始文件名 |
| stored_path | VARCHAR(512) | 服务器上相对路径 |
| file_type | VARCHAR(16) | audio / video |
| file_size | INTEGER | 字节数 |
| status | VARCHAR(32) | uploaded / processing / completed / failed |
| duration | FLOAT | 时长（秒），转写完成后填充 |
| error_message | TEXT | 失败时的错误信息 |
| created_at | DATETIME | 上传时间 |
| transcribed_at | DATETIME | 转写完成时间（P3，可空） |
| diarize | BOOLEAN | 是否对该文件做说话人分离（P9，默认 False） |

> `files.id` 启用 SQLite `AUTOINCREMENT`，删除后 id 不复用（规避旧取消标记误杀新文件的 bug，见 dev_logs/2026-06-24）。

### TranscriptSegment 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER (PK) | 自增主键 |
| file_id | INTEGER (FK) | 关联 File |
| start_time | FLOAT | 开始时间（秒） |
| end_time | FLOAT | 结束时间（秒） |
| text | TEXT | 转写文字 |
| segment_index | INTEGER | 段落排序索引 |
| speaker | VARCHAR(32) | 说话人标签（P9，如 SPEAKER_00；NULL 未识别） |

### FileSpeaker 表（P9b）

说话人重命名，按文件维度：`SPEAKER_00 → 张总`。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER (PK) | 自增主键 |
| file_id | INTEGER (FK) | 关联 File |
| speaker_key | VARCHAR(32) | 原始标签（SPEAKER_00） |
| display_name | VARCHAR(64) | 自定义显示名（张总） |

> `(file_id, speaker_key)` 唯一约束。详情页 `speaker_display` 优先读 FileSpeaker，回退「说话人 N」。

### Summary 表（P10）

AI 会议总结，一文件一份，手动触发后生成。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER (PK) | 自增主键 |
| file_id | INTEGER (FK, UNIQUE) | 关联 File，一文件一份 |
| status | VARCHAR(16) | summarizing / done / failed |
| summary_text | TEXT | 会议摘要 |
| action_items | TEXT | JSON 字符串：待办事项数组 |
| keywords | TEXT | JSON 字符串：关键词数组 |
| provider | VARCHAR(32) | 用的 LLM provider（deepseek/glm/...） |
| model_name | VARCHAR(64) | 模型名 |
| error_message | TEXT | 失败原因 |
| created_at | DATETIME | 生成时间 |

> provider 由 `llm_providers.json` 预设表 + `config.current_llm_provider()` 驱动，换厂商改配置零代码改动。

## 5. API 路由

| 方法 | 路径 | Content-Type | 说明 |
|------|------|-------------|------|
| GET | `/` | text/html | 首页，渲染文件列表 |
| POST | `/upload` | multipart/form-data | 上传文件（带 `diarize` 开关），重定向到首页 |
| GET | `/file/<int:id>` | text/html | 文件详情页 |
| GET | `/api/file/<int:id>/status` | application/json | 返回 `{status, progress}` |
| GET | `/api/worker/status` | application/json | worker 队列状态（删除转写中文件的终止反馈轮询） |
| GET | `/api/file/<int:id>/segments` | application/json | 返回转写段落数组 |
| POST | `/file/<int:id>/delete` | — | 删除文件及转写数据（级联清理） |
| GET | `/uploads/<path>` | — | 静态文件服务 |
| GET | `/api/file/<int:id>/search` | application/json | 单文件内搜索转写段落（迭代 P6） |
| GET | `/search` | text/html | 全局搜索（项目名 + 转写文字），支持 `?tab=all\|name\|content`（迭代 P7） |
| GET | `/file/<int:id>/export` | text/markdown | 导出转写内容为 Markdown（迭代 P8） |
| POST | `/file/<int:id>/speaker/<key>/rename` | application/json | 说话人重命名 SPEAKER_00 → 张总（迭代 P9b） |
| POST | `/segment/<int:seg_id>/speaker` | application/json | 单段说话人勘误（迭代 P9b） |
| POST | `/file/<int:id>/rediarize` | — | 历史文件重新识别说话人并入队（迭代 P9b） |
| POST | `/file/<int:id>/summarize` | application/json | 手动触发 AI 会议总结，入队（迭代 P10） |
| GET | `/api/file/<int:id>/summary` | application/json | 取总结结果与状态（轮询，迭代 P10） |
| POST | `/api/file/<int:id>/summary/action/<int:idx>` | application/json | 切换某条行动项完成状态（迭代 P10b） |

> **全文搜索**基于现有 `transcript_segments`（转写文字）与 `files.filename`（项目名）用 `LIKE` 子串匹配实现（中文友好、零额外 schema），结果分「全部 / 项目名 / 转文字」三类 Tab。数据量增长后可平滑升级至 SQLite FTS5。详见 [docs/search-design.md](search-design.md)。

## 6. 转写处理流程

```
1. worker 线程从队列取出 file_id（单任务串行，后续排队）
2. 更新 File.status = 'processing'
3. 如果 file_type == 'video' → ffmpeg 提取音频为 WAV
4. 加载 faster-whisper 模型（首次加载，后续复用），开 word_timestamps=True
5. 逐段转写（生成器可中断，每段检查文件是否已删 → 删除则 break 中断推理）
6. 写入 TranscriptSegment 表
7. 若 file.diarize 且 DIARIZATION_ENABLED：
   - ffmpeg 转 16k mono wav（规避损坏 MPEG 头导致 pyannote 解码失败）
   - pyannote 分离 → assign_speakers 按时间戳对齐，回填 segment.speaker
   - HF token 缺失 → 优雅降级，speaker 留空，转写照常
8. 更新 File.status = 'completed', File.duration, transcribed_at
9. 出错 → File.status = 'failed', File.error_message
   （except 内先 SQL 查文件是否仍在 DB，避免删除场景下 commit 抛错致 worker 线程崩溃）
```

## 7. 关键依赖

```
# requirements.txt（说话人分离需 py3.11 + 黄金依赖组合）
flask>=3.0
flask-sqlalchemy>=3.0
faster-whisper>=1.0
numpy<2                       # pyannote 3.1.1 兼容
huggingface_hub<0.20          # pyannote 3.1.1 兼容
torch==2.0.1
torchaudio==2.0.2
pyannote.audio==3.1.1
setuptools<70                 # lightning_fabric 依赖 pkg_resources（setuptools 80+ 已移除）

# 系统依赖
# brew install ffmpeg         # 音频提取 / 损坏头容错转 wav
# 说话人分离还需 HF token，配置见 docs/hf-token-setup.md
```
