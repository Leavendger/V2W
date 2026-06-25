"""V2W 数据模型 — File + TranscriptSegment"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class File(db.Model):
    """上传的音视频文件"""
    __tablename__ = 'files'
    __table_args__ = {'sqlite_autoincrement': True}  # id 严格自增，删除后不复用

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename = db.Column(db.String(256), nullable=False)
    stored_path = db.Column(db.String(512), nullable=False)
    file_type = db.Column(db.String(16), nullable=False)    # 'audio' | 'video'
    file_size = db.Column(db.Integer, nullable=False)       # 字节数
    status = db.Column(db.String(32), default='uploaded')    # uploaded / processing / completed / failed
    duration = db.Column(db.Float, nullable=True)            # 秒，转写完填充
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)       # 上传完成时间
    transcribed_at = db.Column(db.DateTime, nullable=True)             # 转写完成时间
    diarize = db.Column(db.Boolean, default=False)                     # 是否对该文件做说话人分离（P9）

    # 关联
    segments = db.relationship(
        'TranscriptSegment',
        backref='file',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='TranscriptSegment.segment_index'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'file_type': self.file_type,
            'file_size': self.file_size,
            'status': self.status,
            'duration': self.duration,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'transcribed_at': self.transcribed_at.isoformat() if self.transcribed_at else None,
        }

    @property
    def formatted_created_at(self):
        """上传时间格式化"""
        if not self.created_at:
            return '-'
        return self.created_at.strftime('%m-%d %H:%M')

    @property
    def formatted_transcribed_at(self):
        """转写完成时间格式化"""
        if not self.transcribed_at:
            return '-'
        return self.transcribed_at.strftime('%m-%d %H:%M')

    @property
    def status_label(self):
        """中文状态标签"""
        labels = {
            'uploaded': '排队中',
            'processing': '转写中',
            'completed': '已完成',
            'failed': '失败',
        }
        return labels.get(self.status, self.status)

    def __repr__(self):
        return f'<File {self.id}: {self.filename} [{self.status}]>'


class TranscriptSegment(db.Model):
    """转写段落 — 带时间戳的文字片段"""
    __tablename__ = 'transcript_segments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False)
    start_time = db.Column(db.Float, nullable=False)     # 开始时间（秒）
    end_time = db.Column(db.Float, nullable=False)       # 结束时间（秒）
    text = db.Column(db.Text, nullable=False)             # 转写文字
    segment_index = db.Column(db.Integer, nullable=False) # 排序索引
    speaker = db.Column(db.String(32), nullable=True)     # 说话人标签（P9，如 SPEAKER_00；NULL 未识别）

    def to_dict(self):
        return {
            'id': self.id,
            'file_id': self.file_id,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'text': self.text,
            'segment_index': self.segment_index,
            'speaker': self.speaker,
        }

    @property
    def speaker_display(self):
        """说话人友好标签。未识别返回空串；优先 FileSpeaker 重命名，回退「说话人 N」。"""
        if not self.speaker:
            return ''
        # 优先查该文件对该 speaker_key 的重命名
        fs = FileSpeaker.query.filter_by(file_id=self.file_id, speaker_key=self.speaker).first()
        if fs:
            return fs.display_name
        try:
            return f'说话人 {int(self.speaker.split("_")[-1]) + 1}'
        except (ValueError, AttributeError):
            return self.speaker

    @property
    def formatted_time(self):
        """格式化为 mm:ss"""
        minutes = int(self.start_time // 60)
        seconds = int(self.start_time % 60)
        return f'{minutes:02d}:{seconds:02d}'

    def __repr__(self):
        return f'<Segment {self.id}: [{self.formatted_time}] {self.text[:30]}...>'


class FileSpeaker(db.Model):
    """说话人重命名（P9b，按文件维度）—— SPEAKER_00 → 张总"""
    __tablename__ = 'file_speakers'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False)
    speaker_key = db.Column(db.String(32), nullable=False)    # SPEAKER_00
    display_name = db.Column(db.String(64), nullable=False)   # 张总

    __table_args__ = (db.UniqueConstraint('file_id', 'speaker_key', name='uq_file_speaker'),)

    def __repr__(self):
        return f'<FileSpeaker {self.file_id}/{self.speaker_key} = {self.display_name}>'


class Summary(db.Model):
    """AI 会议总结（P10，一文件一份，手动触发后生成）

    status：summarizing（生成中）/ done（完成）/ failed（失败）
    action_items / keywords 以 JSON 字符串存储，读取时解析。
    """
    __tablename__ = 'summaries'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_id = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False, unique=True)
    status = db.Column(db.String(16), default='summarizing')   # summarizing / done / failed
    summary_text = db.Column(db.Text, nullable=True)           # 会议摘要
    action_items = db.Column(db.Text, nullable=True)           # JSON: ["待办1", ...] 或 [{"text","owner","due"}]
    keywords = db.Column(db.Text, nullable=True)               # JSON: ["关键词1", ...]
    provider = db.Column(db.String(32), nullable=True)         # deepseek / glm / ...
    model_name = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    @staticmethod
    def _loads_json(s, default):
        import json as _json
        if not s:
            return default
        try:
            return _json.loads(s)
        except (ValueError, TypeError):
            return default

    def to_dict(self):
        return {
            'status': self.status,
            'summary_text': self.summary_text or '',
            'action_items': self._loads_json(self.action_items, []),
            'keywords': self._loads_json(self.keywords, []),
            'provider': self.provider,
            'model_name': self.model_name,
            'error_message': self.error_message,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
        }

    def __repr__(self):
        return f'<Summary file={self.file_id} [{self.status}]>'
