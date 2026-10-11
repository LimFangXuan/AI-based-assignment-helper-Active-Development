"""Flask 扩展对象。单独放一个文件，models 和 blueprints 都从这里导入，避免循环导入。"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
