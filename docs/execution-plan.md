# V2W — 分阶段执行计划

> 每个阶段独立可验证，完成后确认再进入下一阶段

## 阶段总览

| 阶段 | 主题 | 预计文件数 | 核心产出 |
|------|------|-----------|---------|
| P0 | 环境准备 | 3 | 依赖安装、项目骨架、Flask 可启动 |
| P1 | 数据模型 | 2 | SQLite 建表、File/TranscriptSegment 模型 |
| P2 | 文件上传与列表 | 4 | 上传路由、首页文件卡片展示 |
| P3 | 转写引擎 | 3 | Whisper 集成、后台线程、状态轮询 |
| P4 | 详情页与播放器 | 3 | 播放器、转写文字列表、点击跳转 |
| P5 | UI 美化 | 2 | 淡蓝主题、动画、响应式 |

---

## P0 — 环境准备 ✅ 优先级最高

**目标**：项目可以 `python app.py` 启动，浏览器看到 Hello World

### 任务清单
- [ ] 安装 FFmpeg：`brew install ffmpeg`
- [ ] 创建 `requirements.txt`（flask, flask-sqlalchemy, faster-whisper）
- [ ] `pip install -r requirements.txt`
- [ ] 创建 `config.py`（配置类：DB 路径、上传目录、模型参数）
- [ ] 创建 `app.py`（Flask 最小应用，`/` 返回 Hello World）
- [ ] 创建 `templates/base.html`（空骨架）
- [ ] 启动验证：浏览器看到页面

### 验证标准
```bash
python app.py
# → Running on http://127.0.0.1:5000
# 浏览器打开 → 显示 "V2W 已启动"
```

---

## P1 — 数据模型

**目标**：SQLite 数据库就绪，可直接在 Python 中 CRUD

### 任务清单
- [ ] 创建 `models.py`：File 模型 + TranscriptSegment 模型
- [ ] 在 `app.py` 中初始化 SQLAlchemy + 自动建表
- [ ] 写一个测试脚本或路由验证数据库读写

### 验证标准
```python
# 启动应用 → 自动创建 instance/v2w.db
# 可通过 Python shell 添加/查询 File 记录
```

---

## P2 — 文件上传与文件库

**目标**：网页上传文件 → 首页看到文件卡片

### 任务清单
- [ ] 创建 `utils.py`：文件校验（格式白名单、大小限制）
- [ ] `app.py` 添加 `POST /upload` 路由
- [ ] 创建 `templates/index.html`：文件卡片网格 + 空状态
- [ ] `app.py` 添加 `GET /` 路由，查询所有文件渲染首页
- [ ] `POST /file/<id>/delete` 删除路由

### 验证标准
- 上传 mp3 文件 → 首页出现卡片显示文件名 + "已上传" 状态
- 上传非白名单格式 → 返回错误提示
- 删除文件 → 文件从列表消失

---

## P3 — 转写引擎

**目标**：上传后自动后台转写，前端感知状态变化

### 任务清单
- [ ] 创建 `transcriber.py`：封装 faster-whisper 加载与转写
- [ ] 创建 `worker.py`：后台线程管理（队列 + 单任务处理）
- [ ] `app.py` 添加 `GET /api/file/<id>/status` JSON 接口
- [ ] `app.py` 添加 `GET /api/file/<id>/segments` JSON 接口
- [ ] 首页 JS 轮询状态，自动刷新卡片

### 验证标准
- 上传音频 → 状态自动变为 "处理中" → 变为 "已完成"
- 数据库中有转写段落数据
- 转写过程中上传第二个文件 → 排队，等第一个完成

---

## P4 — 详情页与播放

**目标**：详情页播放音视频 + 转写文字 + 点击跳转

### 任务清单
- [ ] 创建 `templates/detail.html`：播放器 + 转写文字区
- [ ] `app.py` 添加 `GET /file/<id>` 路由
- [ ] 播放器支持 video/audio 类型切换
- [ ] JS：点击文字段落 → 播放器 `currentTime` 跳转
- [ ] JS：播放中自动高亮当前段落

### 验证标准
- 点击首页卡片 → 进入详情页
- 视频文件看到画面，音频文件看到播放器
- 点击某段文字 → 播放器跳到对应时间开始播放
- 播放中 → 对应段落高亮

---

## P5 — UI 美化

**目标**：淡蓝主题，良好视觉体验

### 任务清单
- [ ] 创建 `static/style.css`：完整样式（按设计规范）
- [ ] `base.html` 加入导航栏
- [ ] 首页卡片动画（悬停、状态脉冲）
- [ ] 详情页段落交互优化
- [ ] 空状态、错误状态友好提示

### 验证标准
- 页面以淡蓝白为主色调
- 卡片悬停有动效
- 处理中状态有脉冲动画
- 整体整洁、专业感

---

## 各阶段依赖关系

```
P0 ──→ P1 ──→ P2 ──→ P3 ──→ P4 ──→ P5
                                  └── P2+P3 都完成即可开始
```
