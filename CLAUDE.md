# CLAUDE.md — V2W 项目工作指引

## 项目简介

V2W (Voice to Words) — 面向产品经理的 AI 会议助手 Web 应用。上传音视频 → 自动语音转文字 → 带时间戳预览 → 点击跳转播放。

## 标准文件路径

| 文档 | 路径 | 说明 |
|------|------|------|
| 产品需求 | `docs/requirements.md` | MVP 功能范围、用户故事、验收标准 |
| 技术规范 | `docs/tech-spec.md` | 技术栈、架构、数据模型、API 路由 |
| 设计规范 | `docs/design-spec.md` | 色彩系统、布局、组件、交互规范 |
| 执行计划 | `docs/execution-plan.md` | P0~P10 分阶段任务、验证标准、依赖关系 |
| 搜索设计 | `docs/search-design.md` | 全文搜索详细设计（阶段一/二、API、交互） |
| 说话人分离设计 | `docs/speaker-diarization-design.md` | pyannote 方案、对齐、开关、分期（P9） |
| HF Token 指南 | `docs/hf-token-setup.md` | 说话人分离前置：HF 账号注册与 token 配置 |
| AI 总结设计 | `docs/summary-design.md` | LLM provider、map-reduce、结构化输出、分期（P10） |
| 开发日志 | `dev_logs/` | 每日开发记录，按日期命名 `YYYY-MM-DD.md` |
| 项目说明 | `README.md` | 面向用户的简要说明 + 功能清单 |

## 开发工作流

### 日常规范

1. **开始工作前**：查看 `dev_logs/` 最新日志，了解上次进度和待办
2. **执行阶段任务**：按照 `docs/execution-plan.md` 的 P0→P5 顺序推进
3. **每个阶段完成后**：
   - 按验证标准确认功能正常
   - 更新 `dev_logs/` 记录当日完成事项
   - 用户确认后再进入下一阶段
4. **提交代码**：每个阶段完成后做一次 git commit

### 技术约束

- **Flask 开发模式**：`app.py` 中 `debug=True` 开启热重载
- **数据库**：SQLite 文件在 `instance/v2w.db`，通过 Flask-SQLAlchemy 操作
- **上传文件**：保存在 `uploads/` 目录，已加入 `.gitignore`
- **模型文件**：Whisper 模型缓存在 `~/.cache/huggingface/`，不纳入项目
- **单任务处理**：同一时间只转写一个文件，后续文件排队
- **Python 环境**：py3.11（`conda create -p venv python=3.11`）。说话人分离 pyannote.audio 3.1.1 需 py3.11 + 黄金依赖组合（torch 2.0.1 / torchaudio 2.0.2 / numpy<2 / hf_hub<0.20 / setuptools<70，见 `requirements.txt`）。py3.13 下 3.1.1 多处不兼容、4.x 需 community-1 受限访问，故统一用 py3.11

### 质量要求

- 每个阶段独立可验证，不过度超前开发
- 路由先写 GET 再写 POST，每个路由完成后手动测试
- UI 改动优先用浏览器 DevTools 调试，确认后再改 CSS 文件
- 遇到 Whisper 模型下载、FFmpeg 路径等环境问题优先排查

### 提交规范

```
git add -A
git commit -m "P0: 环境准备 - 项目骨架 + Flask 启动"
git commit -m "P1: 数据模型 - SQLite File/TranscriptSegment"
...
```

## 常用命令

```bash
# 启动开发服务器
python app.py

# 安装依赖
pip install -r requirements.txt

# 查看数据库
python -c "from app import db; db.create_all()"

# 清理并重建数据库
rm instance/v2w.db && python -c "from app import app; from models import *; db.create_all()"
```
