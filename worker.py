"""V2W 后台转写任务 — 单线程队列处理"""
import os
import json
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


def _is_file_deleted(session, file_id):
    """直接查 DB 判断文件是否已删除。

    绕过 SQLAlchemy session 缓存：worker 开头的 File.query.get(file_id) 会把
    file 对象缓存进本 session，之后即使别处（删除路由）删了记录，本 session 的
    File.query.get 仍返回缓存对象 → 永不为 None。用原始 SQL 直查才实时。
    """
    from sqlalchemy import text
    return session.execute(
        text('SELECT 1 FROM files WHERE id = :id'), {'id': file_id}
    ).first() is None


def enqueue_file(file_id):
    """将文件加入转写队列（转写任务）"""
    _queue.put(('transcribe', file_id))
    logger.info(f'File {file_id} enqueued (queue size={_queue.qsize()})')


def enqueue_rediarize(file_id):
    """将文件加入队列做「重新识别说话人」（复用已转写文字，只补 diarization）"""
    _queue.put(('rediarize', file_id))
    logger.info(f'File {file_id} enqueued for rediarize (queue size={_queue.qsize()})')


def enqueue_summarize(file_id):
    """将文件加入队列做「AI 会议总结」（P10，手动触发）"""
    _queue.put(('summarize', file_id))
    logger.info(f'File {file_id} enqueued for summarize (queue size={_queue.qsize()})')


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
    from transcriber import transcribe_iter

    while True:
        task = _queue.get()  # 阻塞等待新任务 (kind, file_id)
        if isinstance(task, tuple):
            kind, file_id = task
        else:
            kind, file_id = 'transcribe', task

        with _lock:
            _current_task = file_id

        # 重新识别说话人：复用已转写文字，只补 diarization
        if kind == 'rediarize':
            _do_rediarize(app, file_id)
            with _lock:
                _current_task = None
            continue

        # AI 会议总结：手动触发，调 LLM 生成摘要/行动项/关键词（P10）
        if kind == 'summarize':
            _do_summarize(app, file_id)
            with _lock:
                _current_task = None
            continue

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

                # 检查点 B：转写前检查文件是否已被删除（跳过最耗时的 Whisper 推理）
                if _is_file_deleted(db.session, file_id):
                    logger.info(f'File {file_id} deleted before transcription, skipping')
                    if file_record.file_type == 'video' and os.path.exists(audio_path):
                        os.remove(audio_path)
                    continue

                # 3. 转写（逐段消费，每段检查文件是否被删 → 可中断推理）
                logger.info(f'Starting transcription: {audio_path}')
                seg_gen, language = transcribe_iter(
                    audio_path,
                    model_size=app.config.get('WHISPER_MODEL_SIZE', 'medium'),
                    device=app.config.get('WHISPER_DEVICE', 'auto'),
                    compute_type=app.config.get('WHISPER_COMPUTE_TYPE', 'auto'),
                )
                segments = []
                aborted = False
                for seg in seg_gen:
                    if _is_file_deleted(db.session, file_id):
                        logger.info(f'File {file_id} deleted during transcription, aborting')
                        aborted = True
                        break
                    segments.append(seg)
                if aborted:
                    if file_record.file_type == 'video' and os.path.exists(audio_path):
                        os.remove(audio_path)
                    continue

                # 3.5 说话人分离（按需：文件勾选 + 全局开关 + token）
                speakers_assigned = False
                if file_record.diarize and app.config.get('DIARIZATION_ENABLED'):
                    # 检查点 C：diarize 前检查文件是否已被删除（跳过较慢的分离）
                    if _is_file_deleted(db.session, file_id):
                        logger.info(f'File {file_id} deleted before diarization')
                    else:
                        try:
                            from diarizer import diarize, assign_speakers
                            hf_token = app.config.get('HF_TOKEN')
                            # pyannote 用 mpg123 解码 mp3，损坏的 MPEG 头会失败；
                            # 统一转 16k mono wav（ffmpeg 解码容错）再喂给 diarize
                            diarize_audio = audio_path
                            temp_wav = None
                            if not audio_path.endswith('.wav'):
                                diarize_audio = audio_path + '.diarize.wav'
                                temp_wav = diarize_audio
                                extract_audio(audio_path, diarize_audio)
                            timeline = diarize(diarize_audio, hf_token)
                            if temp_wav and os.path.exists(temp_wav):
                                os.remove(temp_wav)
                            assign_speakers(segments, timeline)
                            speakers_assigned = True
                            logger.info(f'Speaker diarization applied to file {file_id} '
                                        f'({len(timeline)} turns)')
                        except Exception as de:
                            # 优雅降级：分离失败不影响转写，段落 speaker 留空
                            logger.warning(f'Diarization failed for file {file_id}, skipping: {de}')

                # 检查点 D：写库前检查文件是否已被删除（不写入幽灵段落）
                if _is_file_deleted(db.session, file_id):
                    logger.info(f'File {file_id} deleted before writing, skipping')
                    if file_record.file_type == 'video' and os.path.exists(audio_path):
                        os.remove(audio_path)
                    continue

                # 4. 写入段落
                for i, seg in enumerate(segments):
                    segment = TranscriptSegment(
                        file_id=file_id,
                        start_time=seg['start'],
                        end_time=seg['end'],
                        text=seg['text'],
                        segment_index=i,
                        speaker=seg.get('speaker') if speakers_assigned else None,
                    )
                    db.session.add(segment)

                # 5. 更新文件信息
                file_record.status = 'completed'
                file_record.transcribed_at = datetime.now()
                if segments:
                    file_record.duration = segments[-1]['end']
                _db_commit_with_retry(db.session)

                # 6. 清理临时音频
                if file_record.file_type == 'video' and os.path.exists(audio_path):
                    os.remove(audio_path)

                logger.info(f'File {file_id} completed: {len(segments)} segments')

            except Exception as e:
                logger.error(f'File {file_id} failed: {e}', exc_info=True)
                # 文件可能已被删除（用户删除时 worker 正在处理）：file_record 已不在 DB，
                # 再 commit 会抛 StaleDataError 且无法被本 except 捕获 → worker 线程崩溃 →
                # 队列永久卡死。因此先检查文件是否还在 DB，不在则跳过状态更新，保证 worker 存活。
                if not _is_file_deleted(db.session, file_id):
                    try:
                        file_record.status = 'failed'
                        file_record.error_message = str(e)[:500]
                        _db_commit_with_retry(db.session)
                    except Exception as ce:
                        logger.warning(f'Failed to mark file {file_id} as failed: {ce}')
                        db.session.rollback()
                else:
                    logger.info(f'File {file_id} deleted during processing, skip marking failed')
                    db.session.rollback()

                # 清理可能的临时文件
                if file_record.file_type == 'video':
                    temp_wav = os.path.join(app.config['UPLOAD_FOLDER'], file_record.stored_path + '.wav')
                    if os.path.exists(temp_wav):
                        os.remove(temp_wav)

            finally:
                with _lock:
                    _current_task = None


def _do_rediarize(app, file_id):
    """重新识别说话人：复用已转写文字段落，只补 diarization + 对齐。"""
    from models import db, File
    with app.app_context():
        db.session.remove()
        file_record = File.query.get(file_id)
        if file_record is None:
            logger.warning(f'Rediarize {file_id}: file not found, skip')
            return
        try:
            file_record.status = 'processing'
            _db_commit_with_retry(db.session)

            stored_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.stored_path)
            audio_path = stored_path
            if file_record.file_type == 'video':
                audio_path = stored_path + '.wav'
                extract_audio(stored_path, audio_path)
            # diarize 前 转 wav（规避损坏 mp3）
            diarize_audio = audio_path
            temp_wav = None
            if not audio_path.endswith('.wav'):
                diarize_audio = audio_path + '.diarize.wav'
                temp_wav = diarize_audio
                extract_audio(audio_path, diarize_audio)

            from diarizer import diarize, assign_speakers
            timeline = diarize(diarize_audio, app.config.get('HF_TOKEN'))
            if temp_wav and os.path.exists(temp_wav):
                os.remove(temp_wav)

            segs = file_record.segments.all()
            seg_dicts = [{'start': s.start_time, 'end': s.end_time} for s in segs]
            assign_speakers(seg_dicts, timeline)
            for s, d in zip(segs, seg_dicts):
                s.speaker = d.get('speaker')
            file_record.diarize = True
            file_record.status = 'completed'
            _db_commit_with_retry(db.session)

            if file_record.file_type == 'video' and os.path.exists(audio_path):
                os.remove(audio_path)
            logger.info(f'Rediarize {file_id} done: {len(timeline)} turns')
        except Exception as e:
            logger.error(f'Rediarize {file_id} failed: {e}', exc_info=True)
            if not _is_file_deleted(db.session, file_id):
                try:
                    file_record.status = 'completed'  # 回退（原本 completed）
                    _db_commit_with_retry(db.session)
                except Exception:
                    db.session.rollback()
            else:
                db.session.rollback()
            if file_record.file_type == 'video':
                temp_wav_v = os.path.join(app.config['UPLOAD_FOLDER'], file_record.stored_path + '.wav')
                if os.path.exists(temp_wav_v):
                    os.remove(temp_wav_v)


def _do_summarize(app, file_id):
    """AI 会议总结：调 LLM 生成摘要/行动项/关键词，写入 Summary 表（P10）。

    summary 行由 POST /file/<id>/summarize 路由预先创建（status=summarizing），
    这里接力执行；若不存在则补建。失败置 status=failed + error_message。
    """
    from models import db, File, Summary
    with app.app_context():
        db.session.remove()
        file_record = File.query.get(file_id)
        if file_record is None:
            logger.warning(f'Summarize {file_id}: file not found, skip')
            return

        summary = Summary.query.filter_by(file_id=file_id).first()
        if summary is None:
            summary = Summary(file_id=file_id, status='summarizing')
            db.session.add(summary)

        try:
            from config import Config
            from summarizer import summarize_segments

            if file_record.status != 'completed':
                raise RuntimeError('文件尚未完成转写，无法总结')

            provider = Config.current_llm_provider()
            if provider is None:
                raise RuntimeError('未配置 LLM API key，请在 .env 设置（如 DEEPSEEK_API_KEY）并选 LLM_PROVIDER')

            segments = file_record.segments.all()
            if not segments:
                raise RuntimeError('转写内容为空')

            chunk_chars = app.config.get('SUMMARY_CHUNK_CHARS', 6000)
            result = summarize_segments(segments, provider, chunk_chars)

            summary.summary_text = result['summary']
            summary.action_items = json.dumps(result['action_items'], ensure_ascii=False)
            summary.keywords = json.dumps(result['keywords'], ensure_ascii=False)
            summary.provider = provider['name']
            summary.model_name = provider['model']
            summary.status = 'done'
            summary.error_message = None
            _db_commit_with_retry(db.session)
            logger.info(f'Summarize {file_id} done (provider={provider["name"]}/{provider["model"]})')

        except Exception as e:
            logger.error(f'Summarize {file_id} failed: {e}', exc_info=True)
            if not _is_file_deleted(db.session, file_id):
                try:
                    summary.status = 'failed'
                    summary.error_message = str(e)[:500]
                    _db_commit_with_retry(db.session)
                except Exception:
                    db.session.rollback()
            else:
                db.session.rollback()
