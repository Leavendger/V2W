# V2W — AI 会议助手

> 面向产品经理的智能会议记录工具。上传音视频 → 自动语音转文字 → 点击文字跳转播放，本地处理，隐私安全。

[Python](https://python.org)
[Flask](https://flask.palletsprojects.com/)
[Whisper](https://github.com/SYSTRAN/faster-whisper)
[License](LICENSE)

---

## ✨ MVP 功能


| 功能    | 状态  | 说明                                           |
| ----- | --- | -------------------------------------------- |
| 文件上传  | ✅   | 支持 mp3 / mp4 / wav / mov / m4a 等常见格式，拖拽或点击上传 |
| 文件库   | ✅   | 首页卡片网格展示，文件名、大小、时长、状态一目了然                    |
| 音视频预览 | ✅   | HTML5 原生播放器，视频画面 + 音频波形播放                    |
| 语音转文字 | ✅   | faster-whisper 本地引擎，自动断句、带时间戳、支持中英混合         |
| 点击跳转  | ✅   | 点击任意文字段落 → 播放器自动跳转到对应时间                      |
| 播放高亮  | ✅   | 播放时当前段落自动高亮并滚动跟随                             |
| 文件管理  | ✅   | 删除文件（磁盘 + 数据库级联清理）、上传格式校验                    |
| 数据持久化 | ✅   | SQLite 存储，关闭浏览器后历史记录不丢失                      |
| 键盘快捷键 | ✅   | `Space` 播放/暂停 · `←` 后退 5s · `→` 前进 5s        |


## 🎯 核心体验

```
上传音视频 → 自动转写 → 点击文字定位播放
```

- **上传**：首页点击上传按钮，选择会议录音/视频
- **等待**：后台自动转写，状态实时显示（排队 → 转写中 → 完成）
- **查看**：进入详情页，上方播放器 + 下方转写文字
- **定位**：点击任意句子，播放器立即跳到对应位置

## 🛠 技术栈


| 层     | 技术                         | 说明                               |
| ----- | -------------------------- | -------------------------------- |
| 后端框架  | **Flask 3.1**              | 轻量 Python Web 框架                 |
| 数据库   | **SQLite** + SQLAlchemy    | 零配置，单文件存储                        |
| 语音识别  | **faster-whisper** (small) | CTranslate2 加速，本地运行，M4 芯片约 5× 实时 |
| 音频处理  | **FFmpeg 8.1**             | 格式转换、视频提取音频                      |
| 前端    | **Jinja2** + 原生 JS         | 服务端渲染，无前后端分离，零构建工具               |
| UI 主题 | 淡蓝色 (`#f2f7fc`)            | 简洁直观，响应式布局                       |


## 🚀 快速开始

### 环境要求

- macOS (Apple Silicon M 系列)
- Python 3.13+
- FFmpeg

### 安装与启动

```bash
# 1. 克隆项目
git clone git@github.com:Leavendger/V2W.git
cd V2W

# 2. 安装 FFmpeg（如未安装）
brew install ffmpeg

# 3. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. 启动服务（本地访问）
python app.py
# → http://127.0.0.1:8080
```

### 🌐 公网访问（无需公网 IP）

使用 Cloudflare Tunnel 免费内网穿透，任何设备都能访问：

```bash
# 安装 cloudflared
brew install cloudflared

# 一键启动（Flask + 公网隧道）
./start_public.sh
```

启动后会输出类似 `https://xxx.trycloudflare.com` 的公网地址，在手机、平板、其他电脑上打开即可使用。

> **注意**：免费隧道每次重启 URL 会变化。如需固定域名，可注册 Cloudflare 账号并创建命名隧道。

首次运行时，Whisper 会自动下载 `small` 模型（约 464MB），之后即可离线使用。

## 📁 项目结构

```
V2W/
├── app.py                # Flask 应用入口 + 路由
├── config.py             # 配置（模型、路径、格式白名单）
├── models.py             # 数据模型（File / TranscriptSegment）
├── transcriber.py        # Whisper 转写引擎封装
├── worker.py             # 后台任务线程（队列 + 单任务处理）
├── utils.py              # 工具函数（文件校验、格式化）
├── requirements.txt      # Python 依赖
├── uploads/              # 上传文件存储（gitignore）
├── instance/             # SQLite 数据库（gitignore）
├── static/
│   └── style.css         # 淡蓝主题样式
├── templates/
│   ├── base.html         # 公共布局
│   ├── index.html        # 首页 — 文件列表
│   └── detail.html       # 详情页 — 播放器 + 转写
├── docs/                 # 规范文档
│   ├── requirements.md   # 产品需求文档
│   ├── tech-spec.md      # 技术规范
│   ├── design-spec.md    # UI 设计规范
│   ├── execution-plan.md # 分阶段执行计划
│   └── search-design.md  # 全文搜索详细设计
├── dev_logs/             # 开发日志
└── README.md
```

## 📊 转写速度

> 测试环境：Apple M4 芯片


| 模型               | 大小    | 速度     | 1h 音频耗时    |
| ---------------- | ----- | ------ | ---------- |
| tiny             | 75MB  | 20× 实时 | ~3 分钟      |
| base             | 145MB | 10× 实时 | ~6 分钟      |
| **small** *(当前)* | 464MB | 5× 实时  | **~12 分钟** |
| medium           | 1.5GB | 2× 实时  | ~30 分钟     |


可在 `config.py` 中调整 `WHISPER_MODEL_SIZE` 切换模型。

## 🗺 路线图

### 下一阶段

- [ ] 说话人分离（pyannote.audio，区分发言人 A/B）
- [ ] AI 自动总结（生成会议摘要）
- [ ] 关键词与待办事项提取
- [x] 全文搜索（[设计](docs/search-design.md) · 单文件内 P6 + 全局 P7，含项目名检索与「全部/项目名/转文字」三类 Tab）
- [ ] 导出功能（Word / SRT / Markdown）

### 远期规划

- [ ] 实时录音转写
- [ ] 多语言翻译
- [ ] 章节自动划分
- [ ] 协作功能

## 📄 许可证

MIT License