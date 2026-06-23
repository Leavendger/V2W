"""V2W 说话人分离 — pyannote.audio 封装（迭代 P9）

保留现有 faster-whisper 做 ASR，本模块负责：
  1. 加载 pyannote speaker-diarization-3.1（需 HF token，首次自动下载模型）
  2. diarize()：返回说话人时间线 [(start, end, speaker), ...]
  3. assign_speakers()：把 ASR 段落按时间重叠分配给说话人

设计见 docs/speaker-diarization-design.md；token 配置见 docs/hf-token-setup.md。
"""
import logging
import numpy as np
import torchaudio

# 兼容性 patch：pyannote.audio 3.1.1 依赖的旧 API 在新环境（numpy 2 / torchaudio 2）已移除
if not hasattr(np, 'NaN'):                          # numpy 2.0 移除了 np.NaN
    np.NaN = np.nan
if not hasattr(torchaudio, 'set_audio_backend'):   # torchaudio 2.x 移除了 set_audio_backend
    torchaudio.set_audio_backend = lambda *a, **kw: None
if not hasattr(torchaudio, 'get_audio_backend'):   # torchaudio 2.x 移除了 get_audio_backend
    torchaudio.get_audio_backend = lambda *a, **kw: 'soundfile'

from pyannote.audio import Pipeline

logger = logging.getLogger(__name__)

# 全局单例：只加载一次 pipeline
_pipeline = None


def get_pipeline(hf_token):
    """加载 pyannote speaker-diarization-3.1 单例（首次自动下载模型）"""
    global _pipeline
    if _pipeline is None:
        if not hf_token:
            raise RuntimeError('HF_TOKEN 未配置，无法加载 pyannote 模型')
        logger.info('Loading pyannote speaker-diarization-3.1 ...')
        _pipeline = Pipeline.from_pretrained(
            'pyannote/speaker-diarization-3.1', use_auth_token=hf_token)
        logger.info('pyannote pipeline loaded')
    return _pipeline


def diarize(audio_path, hf_token):
    """对音频做说话人分离，返回时间线 [(start, end, speaker), ...]，speaker 形如 'SPEAKER_00'"""
    pipeline = get_pipeline(hf_token)
    logger.info(f'Diarizing: {audio_path}')
    diarization = pipeline(audio_path)
    timeline = [(turn.start, turn.end, speaker)
                for turn, _, speaker in diarization.itertracks(yield_label=True)]
    logger.info(f'Diarization complete: {len(timeline)} turns')
    return timeline


def assign_speakers(segments, timeline):
    """把 ASR 段落按时间重叠分配给说话人（原地给每段加 'speaker' 字段）。

    segments: [{'start', 'end', 'text', ...}, ...]
    timeline: [(start, end, speaker), ...]
    规则：取与段落 [start,end] 时间重叠最多的说话人；无重叠则为 None。
    """
    for seg in segments:
        best, best_overlap = None, 0.0
        for t_start, t_end, speaker in timeline:
            overlap = min(seg['end'], t_end) - max(seg['start'], t_start)
            if overlap > best_overlap:
                best_overlap, best = overlap, speaker
        seg['speaker'] = best if best_overlap > 0 else None
    return segments
