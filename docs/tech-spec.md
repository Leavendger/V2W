# V2W — 技术规范文档

> MVP 版本技术选型与架构设计

## 1. 技术栈

| 层 | 技术 | 版本 | 选型理由 |
|---|------|------|---------|
| 语言 | Python | 3.13+ | 开发效率高，生态丰富 |
| Web 框架 | Flask | 3.x | 轻量成熟，适合 MVP |
| ORM | Flask-SQLAlchemy | 3.x | 数据库操作便捷 |
| 数据库 | SQLite | — | 零配置，单文件，无需安装服务 |
| ASR 引擎 | faster-whisper | 1.x | 基于 CTranslate2，比 openai-whisper 快 4 倍 |
| 音频处理 | FFmpeg | 7.x | 业界标准，视频提取音频 |
| 前端 | Jinja2 + 原生 JS | — | 无构建工具，直接渲染 |
| 异步任务 | Python threading | — | 单用户 MVP 足够 |

## 2. 架构图

```
浏览器 (HTML5)
    │
    ├── GET  /                    → 首页（文件列表）
    ├── POST /upload              → 上传文件
    ├── GET  /file/<id>           → 详情页（播放器 + 转写）
    ├── GET  /api/file/<id>/status → JSON 状态查询
    └── GET  /uploads/<path>      → 静态文件服务
         │
    Flask (app.py)
         │
    ┌────┴────┐
    │         │
  models.py  worker.py
  (SQLite)   (后台线程)
       │         │
       │    transcriber.py
       │    (faster-whisper)
       │         │
       └────┬────┘
          utils.py
          (ffmpeg 音频提取)
```

## 3. 项目文件结构

```
V2W/
├── app.py                # Flask 应用入口 + 路由注册
├── config.py             # 配置（DB路径、上传目录、模型参数）
├── models.py             # SQLAlchemy 数据模型
├── transcriber.py        # Whisper 转写封装
├── worker.py             # 后台转写任务线程管理
├── utils.py              # 工具函数（文件校验、音频提取）
├── requirements.txt      # Python 依赖清单
├── uploads/              # 上传文件存储目录
├── static/
│   └── style.css         # 全局样式
├── templates/
│   ├── base.html         # 公共布局骨架
│   ├── index.html        # 首页：文件列表
│   └── detail.html       # 详情页：播放器 + 转写文字
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

### TranscriptSegment 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER (PK) | 自增主键 |
| file_id | INTEGER (FK) | 关联 File |
| start_time | FLOAT | 开始时间（秒） |
| end_time | FLOAT | 结束时间（秒） |
| text | TEXT | 转写文字 |
| segment_index | INTEGER | 段落排序索引 |

## 5. API 路由

| 方法 | 路径 | Content-Type | 说明 |
|------|------|-------------|------|
| GET | `/` | text/html | 首页，渲染文件列表 |
| POST | `/upload` | multipart/form-data | 上传文件，重定向到首页 |
| GET | `/file/<int:id>` | text/html | 文件详情页 |
| GET | `/api/file/<int:id>/status` | application/json | 返回 `{status, progress}` |
| GET | `/api/file/<int:id>/segments` | application/json | 返回转写段落数组 |
| POST | `/file/<int:id>/delete` | — | 删除文件及转写数据 |
| GET | `/uploads/<path>` | — | 静态文件服务 |
| GET | `/api/file/<int:id>/search` | application/json | 单文件内搜索转写段落（迭代 P6） |
| GET | `/search` | text/html | 全局搜索（项目名 + 转写文字），支持 `?tab=all\|name\|content`（迭代 P7） |
| GET | `/file/<int:id>/export` | text/markdown | 导出转写内容为 Markdown（迭代 P8） |

> **全文搜索**基于现有 `transcript_segments`（转写文字）与 `files.filename`（项目名）用 `LIKE` 子串匹配实现（中文友好、零额外 schema），结果分「全部 / 项目名 / 转文字」三类 Tab。数据量增长后可平滑升级至 SQLite FTS5。详见 [docs/search-design.md](search-design.md)。

## 6. 转写处理流程

```
1. worker 线程从队列取出 file_id
2. 更新 File.status = 'processing'
3. 如果 file_type == 'video' → ffmpeg 提取音频为 WAV
4. 加载 faster-whisper 模型（首次加载，后续复用）
5. 执行转写，获取 (start, end, text) 列表
6. 写入 TranscriptSegment 表
7. 更新 File.status = 'completed', File.duration
8. 如果出错 → File.status = 'failed', File.error_message
```

## 7. 关键依赖

```
# requirements.txt
flask>=3.0
flask-sqlalchemy>=3.0
faster-whisper>=1.0

# 系统依赖
# brew install ffmpeg
```
