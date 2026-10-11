"""应用工厂：读取配置、注册扩展和所有 blueprint。"""
import os

from dotenv import load_dotenv
from flask import Flask

from .extensions import db


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    # DATABASE_URL 默认指向本地 SQLite 文件（instance/app.db）；测试时可以换成临时数据库
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///app.db")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY not found. Check your .env file.")

    db.init_app(app)

    from . import security, template_helpers
    from .blueprints import auth, calendar, overview, projects
    from .blueprints.tools import papers, planner, prompt, report, requirements

    app.before_request(security.check_csrf)
    template_helpers.register(app)
    for module in (auth, overview, calendar, projects, requirements, prompt, planner, papers, report):
        app.register_blueprint(module.bp)

    # 创建应用时就建表 / 升级：无论用 python run.py、flask run 还是 WSGI 服务器启动，数据库都已经准备好
    from .schema import ensure_schema

    with app.app_context():
        ensure_schema()
    return app
