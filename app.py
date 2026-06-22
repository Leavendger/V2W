"""V2W — AI 会议助手 Flask 应用入口"""
import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from config import Config
from models import db, File
from utils import allowed_file, generate_stored_filename


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
        # 检查是否有文件
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
            flash(f'不支持的格式，请上传常见音视频文件', 'error')
            return redirect(url_for('index'))

        # 生成唯一文件名并保存
        stored_name = generate_stored_filename(file.filename)
        stored_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
        file.save(stored_path)

        # 写入数据库
        file_record = File(
            filename=file.filename,
            stored_path=stored_name,  # 只存相对名，方便迁移
            file_type=file_type,
            file_size=os.path.getsize(stored_path),
            status='uploaded',
        )
        db.session.add(file_record)
        db.session.commit()

        flash(f'「{file.filename}」上传成功，等待转写', 'success')
        return redirect(url_for('index'))

    # ============================================================
    # 路由：删除文件
    # ============================================================
    @app.route('/file/<int:file_id>/delete', methods=['POST'])
    def delete_file(file_id):
        file_record = File.query.get_or_404(file_id)

        # 删除磁盘文件
        disk_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.stored_path)
        if os.path.exists(disk_path):
            os.remove(disk_path)

        # 删除数据库记录（级联删除 segments）
        db.session.delete(file_record)
        db.session.commit()

        flash(f'「{file_record.filename}」已删除', 'info')
        return redirect(url_for('index'))

    # ============================================================
    # 路由：文件详情占位（完整实现见 P4）
    # ============================================================
    @app.route('/file/<int:file_id>')
    def file_detail(file_id):
        from flask import render_template as rt
        file_record = File.query.get_or_404(file_id)
        segments = file_record.segments.all()
        return rt('detail.html', file=file_record, segments=segments)

    # ============================================================
    # 路由：上传文件访问
    # ============================================================
    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # ============================================================
    # 上下文注入 — 模板可用函数
    # ============================================================
    @app.context_processor
    def utility_processor():
        from utils import get_file_type_emoji, format_file_size
        return dict(
            file_emoji=get_file_type_emoji,
            format_size=format_file_size,
        )

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8080)
