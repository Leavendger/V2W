# V2W — 说话人分离详细设计

> 区分「谁在说话」，把每段转写文字归属到具体说话人。
>
> 对应执行计划：**P9a（新文件按需分离）→ P9b（历史重识别 + 重命名）→ P9c（按说话人筛选）**，详见 [execution-plan.md](execution-plan.md)。
>
> 前置依赖：HuggingFace token，配置见 [hf-token-setup.md](hf-token-setup.md)。

## 1. 背景与目标

导出与详情页当前所有段落都是 `[发言人]` 占位（`utils.speaker_label()` 写死返回占位）。本功能接入说话人分离（diarization），让每段文字带上真实说话人。

### 1.1 核心痛点（产品经理视角）

- 「这段是客户说的还是我方说的？」
- 「老板的结论在第几分钟？直接听原话。」
- 导出会议纪要时，需要区分发言归属。

### 1.2 核心价值

说话人分离 = **归属**。完成后，详情页、导出 Markdown 自动显示「说话人 1 / 2 / 3」，无需改导出逻辑（`speaker_label()` 已预留扩展点）。

## 2. 现状与难点

### 2.1 faster-whisper 不做 diarization

现有转写引擎 `faster-whisper` 只负责 **ASR**（语音 → 文字），**不输出**「谁在说」。需引入独立的说话人分离模型。

### 2.2 对齐问题（核心难点）

- **ASR 输出**：文字句段时间块 `[start, end, text]`
- **diarization 输出**：说话人时间块 `[start, end, speaker]`（如 `SPEAKER_00`）

两者时间轴相同但粒度不同，必须按**时间重叠**把文字分配给说话人。一段文字可能跨多个说话人块 → 需按词级时间戳细分。

### 2.3 性能

pyannote.audio 在 CPU 上比实时慢（M4 芯片 1h 音频约 10–30 分钟）。因此采用**开关按需启用**，不强制每次都跑。

## 3. 技术选型

| 方案 | 做法 | 依赖 | 准确度 | 改动 | 决策 |
|------|------|------|--------|------|------|
| **B · pyannote 手动集成** | 保留 faster-whisper，新增 `diarizer.py` + 对齐函数 | HF token + pyannote 模型 | 高（工业标准） | 中 | ✅ **采用** |
| A · whisperX | 用 whisperX 替换转写封装（内置 ASR+对齐+diarization） | HF token | 高 | 大（替换 transcriber） | ✗ |
| C · 手动标注 | 详情页手动标说话人，不接 ML | 无 | 取决于人工 | 小 | ✗ |

**决策：方案 B。** 保留现有 `faster-whisper` 单例与转写逻辑，新增独立的 `diarizer.py`，改动可控、与现有架构解耦。`pyannote.audio` 的 `speaker-diarization-3.1` pipeline 是当前开源最佳开箱方案。

## 4. 数据模型

### 4.1 TranscriptSegment 加字段

```python
speaker = db.Column(db.String(32), nullable=True)   # 'SPEAKER_00' 等，NULL 表示未识别
```

### 4.2 数据库迁移（无痛升级，不丢数据）

SQLAlchemy `db.create_all()` 只建新表、不补已有表的列。启动时自动迁移：

```python
# app.py 启动时检查并加列
with app.app_context():
    from sqlalchemy import text, inspect
    inspector = inspect(db.engine)
    columns = [c['name'] for c in inspector.get_columns('transcript_segments')]
    if 'speaker' not in columns:
        db.session.execute(text('ALTER TABLE transcript_segments ADD COLUMN speaker VARCHAR(32)'))
        db.session.commit()
```

- 现有段落 `speaker` 为 NULL → `speaker_label()` 返回占位 `发言人`，行为同升级前；
- 新识别的段落填充 `SPEAKER_00` 等。

## 5. 转写管线改造

`worker.py` 在 ASR 后新增两步（仅当开关开启）：

```
提取音频（已有）
   → ASR（faster-whisper，开 word_timestamps=True 提升对齐精度）
   → [新] diarization（pyannote，输出说话人时间线）
   → [新] assign_speakers（时间重叠对齐，给每段文字分配 speaker）
   → 写入 TranscriptSegment（含 speaker）
```

开关关闭时，跳过 diarization 与对齐，行为与现在完全一致。

## 6. diarizer.py 设计

```python
# diarizer.py（新增）
from pyannote.audio import Pipeline

_pipeline = None

def get_pipeline(hf_token):
    """加载 pyannote speaker-diarization-3.1 单例（首次自动下载模型）"""
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline.from_pretrained(
            'pyannote/speaker-diarization-3.1', use_auth_token=hf_token)
    return _pipeline

def diarize(audio_path, hf_token):
    """返回说话人时间线：[(start, end, speaker), ...]，speaker 形如 'SPEAKER_00'"""
    pipeline = get_pipeline(hf_token)
    diarization = pipeline(audio_path)
    return [(turn.start, turn.end, speaker)
            for turn, _, speaker in diarization.itertracks(yield_label=True)]

def assign_speakers(segments, timeline):
    """把 ASR 段落按时间重叠分配给说话人。

    segments: [{'start','end','text', 'words'?(可选)}, ...]
    timeline: [(start, end, speaker), ...]
    返回：每段附带 'speaker' 字段（取重叠最多的说话人）。
    """
    for seg in segments:
        best, best_overlap = None, 0.0
        for t_start, t_end, speaker in timeline:
            overlap = min(seg['end'], t_end) - max(seg['start'], t_start)
            if overlap > best_overlap:
                best_overlap, best = overlap, speaker
        seg['speaker'] = best          # 可能 None（无重叠）
    return segments
```

> 跨说话人的长段（一段含多人）：MVP 取重叠最多的单一说话人；后续可基于词级时间戳 `words` 细分到词，再聚合成段。当前句子级粒度（VAD 断句）多数段落在单说话人块内，足够用。

## 7. 开关策略（按需启用）

| 配置 | 含义 | 默认 |
|------|------|------|
| `DIARIZATION_ENABLED` | 全局开关（config / 环境变量） | `False` |
| 上传参数 `diarize` | 单文件开关（上传时勾选「识别说话人」） | 跟随全局 |

- 上传时勾选 → 该文件入队时带 `diarize=True`，worker 走 diarization 分支；
- 未勾选 → 维持现状（`[发言人]`）；
- HF token 缺失时优雅降级：跳过 diarization + 日志告警，不阻断转写（详见 [第 10 节](#10-风险与降级)）。

## 8. 友好标签

pyannote 输出 `SPEAKER_00 / SPEAKER_01 / ...`。前端显示与导出统一映射为 **「说话人 1 / 2 / 3」**：

```python
# utils.py
def speaker_label(seg):
    """返回段落说话人友好标签。未识别返回占位。"""
    if not seg.speaker:
        return '发言人'
    # SPEAKER_00 → 说话人 1
    try:
        idx = int(seg.speaker.split('_')[-1]) + 1
        return f'说话人 {idx}'
    except (ValueError, AttributeError):
        return seg.speaker
```

> 重命名（`说话人 1 → 张总`）留到 P9b：新增 `FileSpeaker` 表存 `{file_id, speaker_key, display_name}`，`speaker_label` 优先查重命名。

## 9. 前置条件

### 9.1 Python 环境（py3.11，关键）

**必须用 Python 3.11 + 黄金依赖组合**，不要用 py3.13：

- py3.13 下 **pyannote 4.x** 引入 `speaker-diarization-community-1` 子模型，需 request access（不可靠）；
- py3.13 下 **3.1.1** 与新 numpy 2 / torchaudio 2 / huggingface_hub / setuptools 多处不兼容（无底洞）；
- **py3.11 + 3.1.1 + torch 2.0.1 / torchaudio 2.0.2 / numpy<2 / hf_hub<0.20 / setuptools<70** 是验证可用的组合（见 `requirements.txt`）。

环境创建：`conda create -p venv python=3.11`（推荐 conda/miniforge）。

### 9.2 HuggingFace token

依赖 **HuggingFace token**（pyannote 模型 gated，需登录 + 接受 `speaker-diarization-3.1` 与 `segmentation-3.0` 条款）。完整步骤见 **[hf-token-setup.md](hf-token-setup.md)**。

- `config.py` 已加 `HF_TOKEN = os.environ.get('HF_TOKEN') or 本地 .env`；
- 模型首次下载约 90s（~30MB，含 speaker embedding 子模型），缓存到 `~/.cache/huggingface/`；
- gated 模型权重需走 **官方源 huggingface.co（经代理）**，hf-mirror 镜像只能下 metadata 不能下 gated 权重。

## 10. 风险与降级

| 风险 | 应对 |
|------|------|
| HF token 缺失 / 无效 | worker 捕获异常 → 跳过 diarization，段落 `speaker=None`，日志告警；转写本身不受影响 |
| 模型未下载 / 下载失败 | 同上，降级为不分离；hf-token-setup 文档提供排查 |
| diarization 很慢 | 开关默认关；用户按需勾选；长文件提示预计耗时 |
| 跨说话人长段 | MVP 取重叠最多者；后续词级细分 |
| token 泄露 | token 只存本地 config / 环境变量，**不写入 git**（`.gitignore` 已忽略 instance；token 走环境变量） |

## 11. 对现有功能的影响

| 功能 | 影响 |
|------|------|
| 导出 Markdown | **零改动**自动生效：`speaker_label()` 读 `seg.speaker`，从 `[发言人]` 变为 `说话人 N` |
| 详情页 | 段落段首显示说话人标签；转写中状态提示「正在识别说话人…」 |
| 全文搜索 | 不受影响；P9c 再考虑「按说话人筛选」 |
| 数据库 | 启动时自动加 `speaker` 列，历史数据 NULL |

## 12. 分期任务与验收

### 12.1 P9a — 新文件按需分离

1. `config.py` 加 `DIARIZATION_ENABLED` + `HF_TOKEN`；
2. `models.py` `TranscriptSegment` 加 `speaker` 字段；
3. 新建 `diarizer.py`（`get_pipeline` / `diarize` / `assign_speakers`）；
4. `transcriber.py` 开 `word_timestamps=True`；
5. `worker.py` 开关分支：diarize + assign_speakers，写 `speaker`；
6. `utils.py` `speaker_label()` 读 `seg.speaker` + 友好映射；
7. `detail.html` 段落显示说话人；`index.html` 上传勾选「识别说话人」；
8. `app.py` 上传接 `diarize` 参数；启动时自动迁移加列。

**验收：**

- [ ] 勾选上传 → 段落带 `speaker`，详情页显示「说话人 N」；
- [ ] 导出 md 显示「**说话人 1**」（衔接预留点）；
- [ ] 不勾选 → 行为不变，全 `[发言人]`；
- [ ] 现有库升级不丢数据（`speaker` 为 NULL，显示占位）；
- [ ] token 缺失时优雅降级，转写正常。

### 12.2 P9b — 历史重识别 + 重命名

1. 详情页「重新识别说话人」按钮（复用已有 ASR 结果，只补 diarization + 对齐）；
2. `FileSpeaker` 表 + 详情页说话人重命名（`说话人 1 → 张总`）。

### 12.3 P9c（可选）— 按说话人筛选

全局/详情页按说话人筛选段落；说话人数量统计。
