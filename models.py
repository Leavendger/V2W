"""V2W 数据模型 — File + TranscriptSegment"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class File(db.Model):
    """上传的音视频文件"""
    __tablename__ = 'files'

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
        """说话人友好标签（说话人 N）。未识别返回空串。"""
        if not self.speaker:
            return ''
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
