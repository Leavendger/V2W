"""V2W 工具函数 — 文件校验、路径生成"""
import os
import uuid
from werkzeug.utils import secure_filename


def allowed_file(filename, config):
    """检查文件扩展名是否在白名单中
    返回 (is_allowed, file_type) 或 (False, None)
    """
    if '.' not in filename:
        return False, None

    ext = filename.rsplit('.', 1)[1].lower()

    if ext in config.get('ALLOWED_AUDIO_EXTENSIONS', set()):
        return True, 'audio'
    if ext in config.get('ALLOWED_VIDEO_EXTENSIONS', set()):
        return True, 'video'

    return False, None


def generate_stored_filename(original_filename):
    """生成唯一存储文件名：UUID + 原扩展名"""
    ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    secure_name = secure_filename(original_filename)
    unique_id = uuid.uuid4().hex[:12]
    if ext:
        return f'{unique_id}_{secure_name}'
    return f'{unique_id}_{secure_name}'


def get_file_type_emoji(file_type):
    """返回文件类型对应的 emoji"""
    return '🎬' if file_type == 'video' else '🎵'


def format_file_size(bytes_size):
    """格式化文件大小（人类可读）"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f'{bytes_size:.1f} {unit}' if unit != 'B' else f'{bytes_size} B'
        bytes_size /= 1024
    return f'{bytes_size:.1f} GB'


def format_duration(seconds):
    """格式化时长（秒 → mm:ss 或 hh:mm:ss）。None 返回占位 '--:--'。"""
    if seconds is None:
        return '--:--'
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m:02d}:{s:02d}'


def escape_like(keyword):
    """转义 SQL LIKE 的通配符，使其按字面匹配。

    用于全文搜索：用户输入的 % _ \\ 不会被当作通配符。
    """
    return (keyword
            .replace('\\', '\\\\')
            .replace('%', '\\%')
            .replace('_', '\\_'))


def speaker_label(seg):
    """返回段落说话人友好标签。未识别返回占位「发言人」。

    P9：接入说话人分离后读取 seg.speaker（如 SPEAKER_00 → 说话人 1）。
    P9b：优先查该文件的重命名（FileSpeaker.display_name）。
    """
    speaker = getattr(seg, 'speaker', None)
    if not speaker:
        return '发言人'
    # 优先查重命名
    try:
        from models import FileSpeaker
        fs = FileSpeaker.query.filter_by(file_id=seg.file_id, speaker_key=speaker).first()
        if fs:
            return fs.display_name
    except Exception:
        pass
    try:
        return f'说话人 {int(speaker.split("_")[-1]) + 1}'
    except (ValueError, AttributeError):
        return speaker


def segments_to_markdown(file_record, segments):
    """将转写段落导出为 Markdown 文本。

    结构：# 文件名标题 + 元信息（时长/转写时间）+ 每段「说话人 tag · 时间戳 + 文字」。
    """
    lines = []
    lines.append(f"# {file_record.filename}")
    lines.append("")

    meta = []
    if file_record.duration:
        meta.append(f"⏱ 时长 {format_duration(file_record.duration)}")
    if file_record.transcribed_at:
        meta.append(f"✅ 转写完成 {file_record.transcribed_at.strftime('%Y-%m-%d %H:%M')}")
    if meta:
        lines.append("> " + " · ".join(meta))
        lines.append("")

    lines.append("---")
    lines.append("")

    for seg in segments:
        lines.append(f"**[{speaker_label(seg)}]** `{format_duration(seg.start_time)}`")
        lines.append("")
        lines.append(seg.text)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
