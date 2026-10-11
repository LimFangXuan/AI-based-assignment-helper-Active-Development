import secrets
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


class User(db.Model):
    """账号。密码登录和 Google 登录可以同时存在；只用 Google 注册的账号没有可用的密码（has_password=False）。

    email / google_sub 的唯一性用唯一索引实现（SQLite 的 ALTER TABLE 不能直接加 UNIQUE 列），
    索引在 schema.py 里对旧数据库同样会补上。email 一律存小写。
    """

    __table_args__ = (
        db.Index("ix_user_email", "email", unique=True),
        db.Index("ix_user_google_sub", "google_sub", unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    has_password = db.Column(db.Boolean, nullable=False, default=True)
    email = db.Column(db.String(254))
    google_sub = db.Column(db.String(64))  # Google 账号的固定 ID（不会随邮箱改变）
    created_at = db.Column(db.DateTime, default=datetime.now)

    projects = db.relationship("Project", backref="owner", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.has_password = True

    def set_unusable_password(self):
        """只用 Google 注册的账号：存一个没人知道的随机密码，直到用户自己在 Settings 里设置密码。"""
        self.password_hash = generate_password_hash(secrets.token_urlsafe(32))
        self.has_password = False

    def check_password(self, password):
        return bool(self.has_password) and check_password_hash(self.password_hash, password)
