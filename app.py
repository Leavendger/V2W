"""V2W — AI 会议助手 Flask 应用入口"""
import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from config import Config
from models import db, File
from utils import allowed_file, generate_stored_filename

# 日志配置
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = app.config['SECRET_KEY']

    # 确保必要目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)

    # 初始化数据库
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # 轻量迁移：为已有表补新列（create_all 不改已存在表，P9）
        from sqlalchemy import inspect as sa_inspect, text as sa_text
        _inspector = sa_inspect(db.engine)
        if 'speaker' not in [c['name'] for c in _inspector.get_columns('transcript_segments')]:
            db.session.execute(sa_text(
                'ALTER TABLE transcript_segments ADD COLUMN speaker VARCHAR(32)'))
            logger.info('Migrated: added transcript_segments.speaker')
        if 'diarize' not in [c['name'] for c in _inspector.get_columns('files')]:
            db.session.execute(sa_text(
                'ALTER TABLE files ADD COLUMN diarize BOOLEAN DEFAULT 0'))
            logger.info('Migrated: added files.diarize')
        db.session.commit()

        # 迁移：files.id 改为 AUTOINCREMENT（删除后 id 不复用，避免 worker 误判取消）
        _files_sql = db.session.execute(sa_text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='files'"
        )).scalar()
        if _files_sql and 'AUTOINCREMENT' not in _files_sql:
            logger.info('Migrating files table: add AUTOINCREMENT (id 不复用)')
            db.session.execute(sa_text(
                'CREATE TABLE files_new ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'filename VARCHAR(256) NOT NULL, '
                'stored_path VARCHAR(512) NOT NULL, '
                'file_type VARCHAR(16) NOT NULL, '
                'file_size INTEGER NOT NULL, '
                "status VARCHAR(32) DEFAULT 'uploaded', "
                'duration FLOAT, '
                'error_message TEXT, '
                'created_at DATETIME, '
                'transcribed_at DATETIME, '
                'diarize BOOLEAN DEFAULT 0)'
            ))
            db.session.execute(sa_text(
                'INSERT INTO files_new (id, filename, stored_path, file_type, file_size, '
                'status, duration, error_message, created_at, transcribed_at, diarize) '
                'SELECT id, filename, stored_path, file_type, file_size, '
                'status, duration, error_message, created_at, transcribed_at, diarize FROM files'
            ))
            db.session.execute(sa_text('DROP TABLE files'))
            db.session.execute(sa_text('ALTER TABLE files_new RENAME TO files'))
            db.session.commit()
            logger.info('Migrated: files.id now AUTOINCREMENT (id 不再复用)')
        # 启用 WAL 模式（提高并发性能）
        from sqlalchemy import text
        db.session.execute(text('PRAGMA journal_mode=WAL'))
        db.session.execute(text('PRAGMA synchronous=NORMAL'))
        db.session.commit()

    # ============================================================
    # 路由：首页 — 展示所有文件
    # ============================================================
    @app.route('/')
    def index():
        files = File.query.order_by(File.created_at.desc()).all()
        return render_template('index.html', files=files)

    # ============================================================
    # 路由：上传文件
    # ============================================================
    @app.route('/upload', methods=['POST'])
    def upload():
        if 'file' not in request.files:
            flash('未选择文件', 'error')
            return redirect(url_for('index'))

        file = request.files['file']
        if file.filename == '':
            flash('未选择文件', 'error')
            return redirect(url_for('index'))

        # 校验格式
        is_allowed, file_type = allowed_file(file.filename, app.config)
        if not is_allowed:
            flash('不支持的格式，请上传常见音视频文件', 'error')
            return redirect(url_for('index'))

        # 生成唯一文件名并保存
        stored_name = generate_stored_filename(file.filename)
        stored_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
        file.save(stored_path)

        # 写入数据库
        diarize_requested = (request.form.get('diarize') == '1'
                             and app.config.get('DIARIZATION_ENABLED'))
        file_record = File(
            filename=file.filename,
            stored_path=stored_name,
            file_type=file_type,
            file_size=os.path.getsize(stored_path),
            status='uploaded',
            diarize=diarize_requested,
        )
        db.session.add(file_record)
        db.session.commit()

        # 加入转写队列
        from worker import enqueue_file
        enqueue_file(file_record.id)

        msg = f'「{file.filename}」上传成功，已加入转写队列'
        if diarize_requested:
            msg += '（含说话人识别，耗时较长）'
        flash(msg, 'success')
        return redirect(url_for('index'))

    # ============================================================
    # 路由：删除文件
    # ============================================================
    @app.route('/file/<int:file_id>/delete', methods=['POST'])
    def delete_file(file_id):
        file_record = File.query.get_or_404(file_id)

        # 删除 DB 记录后，worker 各检查点（转写前/diarize 前/写库前）会检测到
        # File 已不存在而跳过，无需额外取消标记（避免 id 复用误杀新文件）

        disk_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.stored_path)
        if os.path.exists(disk_path):
            os.remove(disk_path)

        db.session.delete(file_record)
        db.session.commit()

        flash(f'「{file_record.filename}」已删除', 'info')
        return redirect(url_for('index'))

    # ============================================================
    # 路由：文件详情（P4 完善播放器交互）
    # ============================================================
    @app.route('/file/<int:file_id>')
    def file_detail(file_id):
        file_record = File.query.get_or_404(file_id)
        segments = file_record.segments.all()
        return render_template('detail.html', file=file_record, segments=segments)

    # ============================================================
    # API：转写状态查询（前端轮询用）
    # ============================================================
    @app.route('/api/file/<int:file_id>/status')
    def api_file_status(file_id):
        file_record = File.query.get_or_404(file_id)
        return jsonify({
            'id': file_record.id,
            'status': file_record.status,
            'status_label': file_record.status_label,
            'error_message': file_record.error_message,
            'duration': file_record.duration,
            'segment_count': file_record.segments.count(),
            'created_at': file_record.formatted_created_at,
            'transcribed_at': file_record.formatted_transcribed_at,
        })

    # ============================================================
    # API：转写段落数据
    # ============================================================
    @app.route('/api/file/<int:file_id>/segments')
    def api_file_segments(file_id):
        file_record = File.query.get_or_404(file_id)
        segments = file_record.segments.all()
        return jsonify([s.to_dict() for s in segments])

    # ============================================================
    # API：单文件内全文搜索（迭代 P6）
    # ============================================================
    @app.route('/api/file/<int:file_id>/search')
    def api_file_search(file_id):
        from models import TranscriptSegment
        from utils import escape_like
        from sqlalchemy import func

        q = (request.args.get('q') or '').strip()
        if not q:
            return jsonify({'query': '', 'total': 0, 'hits': []})

        file_record = File.query.get_or_404(file_id)
        if file_record.status != 'completed':
            return jsonify({'query': q, 'total': 0, 'hits': []})

        # 大小写不敏感的子串匹配；escape_like 转义通配符，按字面匹配
        kw = '%' + escape_like(q.lower()) + '%'
        results = (TranscriptSegment.query
                   .filter(TranscriptSegment.file_id == file_id)
                   .filter(func.lower(TranscriptSegment.text).like(kw, escape='\\'))
                   .order_by(TranscriptSegment.segment_index)
                   .all())

        hits = [{
            'segment_index': r.segment_index,
            'start_time': r.start_time,
            'end_time': r.end_time,
            'text': r.text,
        } for r in results]
        return jsonify({'query': q, 'total': len(hits), 'hits': hits})

    # ============================================================
    # 路由：上传文件访问
    # ============================================================
    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # ============================================================
    # 路由：导出转写内容为 Markdown
    # ============================================================
    @app.route('/file/<int:file_id>/export')
    def export_file(file_id):
        from flask import Response
        from urllib.parse import quote
        from utils import segments_to_markdown

        file_record = File.query.get_or_404(file_id)
        if file_record.status != 'completed':
            flash('文件尚未转写完成，暂无法导出', 'error')
            return redirect(url_for('file_detail', file_id=file_id))

        md_content = segments_to_markdown(file_record, file_record.segments.all())

        # 下载文件名：原文件名去扩展名 + .md；中文按 RFC 5987 编码
        base = os.path.splitext(file_record.filename)[0]
        encoded = quote(f"{base}.md")

        response = Response(md_content, mimetype='text/markdown')
        response.headers['Content-Disposition'] = (
            f"attachment; filename=\"export.md\"; filename*=UTF-8''{encoded}"
        )
        return response

    # ============================================================
    # 路由：全局搜索（项目名 + 转写文字，三类 Tab）
    # ============================================================
    @app.route('/search')
    def search():
        from models import TranscriptSegment
        from utils import escape_like
        from sqlalchemy import func

        q = (request.args.get('q') or '').strip()
        tab = request.args.get('tab', 'all')
        if tab not in ('all', 'name', 'content'):
            tab = 'all'

        if not q:
            return render_template('search.html', q='', tab=tab,
                                   name_files=[], content_groups=[],
                                   name_count=0, content_count=0, total_count=0)

        kw = '%' + escape_like(q.lower()) + '%'

        # 1) 项目名命中：文件名 LIKE（所有状态文件，含未转写完成的）
        name_files = (File.query
                      .filter(func.lower(File.filename).like(kw, escape='\\'))
                      .order_by(File.created_at.desc()).all())

        # 2) 转写命中：仅 completed，一次 join 避免 N+1，按文件分组
        results = (db.session.query(TranscriptSegment, File)
                   .join(File, TranscriptSegment.file_id == File.id)
                   .filter(File.status == 'completed')
                   .filter(func.lower(TranscriptSegment.text).like(kw, escape='\\'))
                   .order_by(File.created_at.desc(), TranscriptSegment.segment_index)
                   .all())
        content_groups = []
        file_pos = {}
        for seg, file in results:
            pos = file_pos.get(file.id)
            if pos is None:
                file_pos[file.id] = len(content_groups)
                content_groups.append({'file': file, 'hits': [seg]})
            else:
                content_groups[pos]['hits'].append(seg)

        name_count = len(name_files)
        content_count = len(content_groups)
        # 全部 = 项目名与转写命中的文件去重并集
        all_file_ids = set(f.id for f in name_files)
        all_file_ids |= set(g['file'].id for g in content_groups)
        total_count = len(all_file_ids)

        return render_template('search.html', q=q, tab=tab,
                               name_files=name_files, content_groups=content_groups,
                               name_count=name_count, content_count=content_count,
                               total_count=total_count)

    # ============================================================
    # 上下文注入
    # ============================================================
    @app.context_processor
    def utility_processor():
        from utils import get_file_type_emoji, format_file_size
        return dict(
            file_emoji=get_file_type_emoji,
            format_size=format_file_size,
        )

    # ============================================================
    # Jinja 过滤器：服务端关键词高亮（迭代 P7）
    # ============================================================
    @app.template_filter('highlight')
    def highlight_filter(text, q):
        from markupsafe import Markup, escape
        text = text or ''
        if not q:
            return Markup(str(escape(text)))
        ql = q.lower()
        tl = text.lower()
        out = []
        last = 0
        idx = tl.find(ql)
        while idx != -1:
            out.append(str(escape(text[last:idx])))
            out.append('<mark>')
            out.append(str(escape(text[idx:idx + len(q)])))
            out.append('</mark>')
            last = idx + len(q)
            idx = tl.find(ql, last)
        out.append(str(escape(text[last:])))
        return Markup(''.join(out))

    # ============================================================
    # 启动后台 worker
    # 注意：Flask debug 模式会启动 reloader，父进程创建 app 后 spawn 子进程。
    # WERKZEUG_RUN_MAIN 只在子进程中被设为 'true'，需在此处才启动 worker。
    # ============================================================
    if os.environ.get('WERKZEUG_RUN_MAIN') is None:
        # 非 reloader 模式（直接 python app.py 或生产环境），直接启动
        from worker import start_worker
        start_worker(app)
        logger.info('Worker started (no reloader)')
    elif os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        # Flask reloader 子进程，启动 worker
        from worker import start_worker
        start_worker(app)
        logger.info('Worker started (reloader child)')
    # 否则是 reloader 父进程，跳过

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8080)
