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
        file_record = File(
            filename=file.filename,
            stored_path=stored_name,
            file_type=file_type,
            file_size=os.path.getsize(stored_path),
            status='uploaded',
        )
        db.session.add(file_record)
        db.session.commit()

        # 加入转写队列
        from worker import enqueue_file
        enqueue_file(file_record.id)

        flash(f'「{file.filename}」上传成功，已加入转写队列', 'success')
        return redirect(url_for('index'))

    # ============================================================
    # 路由：删除文件
    # ============================================================
    @app.route('/file/<int:file_id>/delete', methods=['POST'])
    def delete_file(file_id):
        file_record = File.query.get_or_404(file_id)

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
    # 路由：上传文件访问
    # ============================================================
    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

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
