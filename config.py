"""V2W 应用配置"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _load_env_file():
    """从本地 .env 文件加载键值对（.env 不入 git，存放 HF_TOKEN 等本地密钥）"""
    env_path = os.path.join(BASE_DIR, '.env')
    if not os.path.exists(env_path):
        return {}
    result = {}
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


_LOCAL_ENV = _load_env_file()


class Config:
    """基础配置"""
    # 开发环境使用默认值；生产环境请设置环境变量 SECRET_KEY
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'v2w-dev-secret-key-change-in-prod'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'v2w.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {
            'timeout': 30,           # 等待锁的超时（秒）
        },
        'pool_pre_ping': True,
    }

    # SQLite WAL 模式（提高并发写入性能）
    @staticmethod
    def init_db_wal(db_uri):
        """在连接后启用 WAL 模式"""
        if db_uri.startswith('sqlite:///'):
            import sqlite3
            db_path = db_uri.replace('sqlite:///', '')
            conn = sqlite3.connect(db_path)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.close()

    # 上传文件配置
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB

    # 允许的文件扩展名
    ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'm4a', 'flac', 'aac', 'ogg', 'wma'}
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'wmv', 'webm', 'mkv', 'flv'}

    # Whisper 模型配置
    # small: 490MB，中文识别良好，转写速度约 1:3（1 小时音频 ≈ 20 分钟处理）
    # medium: 1.5GB，中文最佳，速度约 1:8
    WHISPER_MODEL_SIZE = 'medium'      # tiny / base / small / medium / large
    WHISPER_DEVICE = 'auto'           # auto / cpu / cuda
    WHISPER_COMPUTE_TYPE = 'auto'     # auto 自动选最优（CPU=int8, GPU=float16）

    # 说话人分离（迭代 P9）
    # 全局总开关：是否允许「识别说话人」。False 时即使上传勾选也不跑。
    DIARIZATION_ENABLED = os.environ.get('DIARIZATION_ENABLED', 'true').lower() == 'true'
    # HuggingFace token：环境变量优先，回退本地 .env（配置见 docs/hf-token-setup.md）
    HF_TOKEN = os.environ.get('HF_TOKEN') or _LOCAL_ENV.get('HF_TOKEN')
