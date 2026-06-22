"""V2W 后台转写任务 — 单线程队列处理"""
import os
import time
import subprocess
import threading
import logging
from datetime import datetime
from queue import Queue
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

# 任务队列 + 处理状态
_queue = Queue()
_current_task = None  # 当前正在处理的 file_id
_lock = threading.Lock()


def _db_commit_with_retry(session, max_retries=5, delay=1.0):
    """提交 DB 事务，遇到锁时自动重试"""
    for attempt in range(max_retries):
        try:
            session.commit()
            return True
        except OperationalError as e:
            if 'database is locked' in str(e).lower() and attempt < max_retries - 1:
                logger.warning(f'DB locked, retrying ({attempt + 1}/{max_retries})...')
                time.sleep(delay * (attempt + 1))  # 递增等待
                session.rollback()
            else:
                raise
    return False


def extract_audio(video_path, output_path):
    """
    从视频文件提取音频为 WAV (16kHz, mono)
    如果是纯音频文件则直接转换为 WAV
    """
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vn',                    # 不要视频流
        '-acodec', 'pcm_s16le',   # 16-bit PCM
        '-ar', '16000',           # 16kHz 采样率（Whisper 要求）
        '-ac', '1',               # 单声道
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def get_current_progress():
    """返回当前任务的 file_id 和粗略进度（供轮询使用）"""
    with _lock:
        if _current_task is None:
            return None, None
        # faster-whisper 不提供实时进度，这里返回占位值
        return _current_task, 0


def enqueue_file(file_id):
    """将文件加入转写队列"""
    _queue.put(file_id)
    logger.info(f'File {file_id} enqueued (queue size={_queue.qsize()})')


def start_worker(app):
    """
    启动后台转写线程。
    需要在 Flask app 创建后调用。
    """
    if _queue is None:
        return  # 避免重复启动

    thread = threading.Thread(
        target=_worker_loop,
        args=(app,),
        daemon=True,
        name='whisper-worker',
    )
    thread.start()
    logger.info('Worker thread started')
    return thread


def _worker_loop(app):
    """后台线程主循环"""
    from models import db, File, TranscriptSegment
    from transcriber import transcribe

    while True:
        file_id = _queue.get()  # 阻塞等待新任务

        with _lock:
            _current_task = file_id

        logger.info(f'Worker: processing file {file_id}')

        with app.app_context():
            db.session.remove()  # 清理旧会话
            file_record = File.query.get(file_id)
            if file_record is None:
                logger.warning(f'File {file_id} not found in DB, skipping')
                with _lock:
                    _current_task = None
                continue

            try:
                # 1. 更新状态为处理中
                file_record.status = 'processing'
                _db_commit_with_retry(db.session)

                # 2. 确定输入音频路径
                stored_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.stored_path)
                audio_path = stored_path

                if file_record.file_type == 'video':
                    # 从视频中提取音频
                    audio_path = stored_path + '.wav'
                    logger.info(f'Extracting audio from video: {stored_path}')
                    extract_audio(stored_path, audio_path)

                # 3. 转写
                logger.info(f'Starting transcription: {audio_path}')
                segments, language = transcribe(
                    audio_path,
                    model_size=app.config.get('WHISPER_MODEL_SIZE', 'medium'),
                    device=app.config.get('WHISPER_DEVICE', 'auto'),
                    compute_type=app.config.get('WHISPER_COMPUTE_TYPE', 'auto'),
                )

                # 4. 写入段落
                for i, seg in enumerate(segments):
                    segment = TranscriptSegment(
                        file_id=file_id,
                        start_time=seg['start'],
                        end_time=seg['end'],
                        text=seg['text'],
                        segment_index=i,
                    )
                    db.session.add(segment)

                # 5. 更新文件信息
                file_record.status = 'completed'
                file_record.transcribed_at = datetime.utcnow()
                if segments:
                    file_record.duration = segments[-1]['end']
                _db_commit_with_retry(db.session)

                # 6. 清理临时音频
                if file_record.file_type == 'video' and os.path.exists(audio_path):
                    os.remove(audio_path)

                logger.info(f'File {file_id} completed: {len(segments)} segments')

            except Exception as e:
                logger.error(f'File {file_id} failed: {e}', exc_info=True)
                file_record.status = 'failed'
                file_record.error_message = str(e)[:500]
                _db_commit_with_retry(db.session)

                # 清理可能的临时文件
                if file_record.file_type == 'video':
                    temp_wav = os.path.join(app.config['UPLOAD_FOLDER'], file_record.stored_path + '.wav')
                    if os.path.exists(temp_wav):
                        os.remove(temp_wav)

            finally:
                with _lock:
                    _current_task = None
