"""V2W 应用配置"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """基础配置"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'v2w-dev-secret-key-change-in-prod'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'v2w.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 上传文件配置
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB

    # 允许的文件扩展名
    ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'm4a', 'flac', 'aac', 'ogg', 'wma'}
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'wmv', 'webm', 'mkv', 'flv'}

    # Whisper 模型配置
    WHISPER_MODEL_SIZE = 'medium'  # tiny / base / small / medium / large
    WHISPER_DEVICE = 'auto'        # auto / cpu / cuda
    WHISPER_COMPUTE_TYPE = 'auto'  # auto / float16 / int8
