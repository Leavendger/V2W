"""V2W 转写引擎 — faster-whisper 封装"""
import logging
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# 全局单例：只加载一次模型
_model = None
_model_size = None


def get_model(model_size='medium', device='auto', compute_type='auto'):
    """获取 WhisperModel 单例，首次调用时自动下载模型"""
    global _model, _model_size

    if _model is None or _model_size != model_size:
        logger.info(f'Loading Whisper model: {model_size} (device={device}, compute={compute_type})')
        _model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _model_size = model_size
        logger.info(f'Model loaded: {model_size}')

    return _model


def transcribe(audio_path, model_size='medium', device='auto', compute_type='auto', language=None):
    """
    转写音频文件，返回带时间戳的句子段落列表。

    参数:
        audio_path: 音频文件路径（WAV 格式最佳）
        model_size: tiny/base/small/medium/large
        language: 语言代码，None 为自动检测

    返回:
        list[dict]: [{'start': float, 'end': float, 'text': str}, ...]
    """
    model = get_model(model_size, device, compute_type)

    logger.info(f'Transcribing: {audio_path}')

    # faster-whisper 转写（速度优先参数）
    segments, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=1,               # 贪婪搜索，最快
        best_of=1,                 # 单候选
        vad_filter=True,           # 过滤静音（跳过无效计算）
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
        condition_on_previous_text=False,  # 减少上下文依赖
    )

    logger.info(f'Detected language: {info.language} (probability={info.language_probability:.2f})')

    # 收集段落
    results = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            results.append({
                'start': round(segment.start, 2),
                'end': round(segment.end, 2),
                'text': text,
            })

    logger.info(f'Transcription complete: {len(results)} segments, '
                f'duration={results[-1]["end"] if results else 0:.1f}s')

    return results, info.language
