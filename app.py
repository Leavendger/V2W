"""V2W — AI 会议助手 Flask 应用入口"""
import os
from flask import Flask, render_template
from config import Config
from models import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 确保必要目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)

    # 初始化数据库
    db.init_app(app)
    with app.app_context():
        db.create_all()

    # 首页
    @app.route('/')
    def index():
        return render_template('index.html')

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8080)
