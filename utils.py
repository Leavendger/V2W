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
    """格式化时长（秒 → mm:ss 或 hh:mm:ss）"""
    if not seconds:
        return '--:--'
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m:02d}:{s:02d}'
