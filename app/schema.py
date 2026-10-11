"""数据库升级。db.create_all() 只会建新表，不会给已有的表加列，所以缺的列在这里手动补上。

规则（spec §4.5）：只加不删。旧数据库升级后，原有的用户、项目和记录都要保留。
"""
from sqlalchemy import text

from .extensions import db

# (表名, 列名, 列定义)。表名和列名只能是这里的常量，绝不能来自用户输入
COLUMNS = [
    ("prompt_session", "diagnosis_json", "TEXT"),
    ("prompt_session", "requirements_check_id", "INTEGER REFERENCES requirements_check(id)"),
    ("prompt_session", "framework_json", "TEXT"),
    ("prompt_session", "content_fingerprint", "VARCHAR(64)"),
    ("project", "type", "VARCHAR(40) NOT NULL DEFAULT 'other'"),
    ("project", "work_mode", "VARCHAR(20) NOT NULL DEFAULT 'individual'"),
    ("project", "citation_style", "VARCHAR(30)"),
    ("project", "guideline", "TEXT NOT NULL DEFAULT ''"),
    ("task", "detail", "TEXT"),
    ("requirements_check", "conflicts_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("requirements_check", "questions_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("task", "based_on_assumption", "BOOLEAN NOT NULL DEFAULT 0"),
    ("task", "content_fingerprint", "VARCHAR(64)"),
    ("report_section", "assumptions_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("user", "has_password", "BOOLEAN NOT NULL DEFAULT 1"),
    ("user", "email", "VARCHAR(254)"),
    ("user", "google_sub", "VARCHAR(64)"),
    ("user", "created_at", "DATETIME"),
    ("user", "email_verified", "BOOLEAN NOT NULL DEFAULT 0"),
    ("user", "timezone", "VARCHAR(64) NOT NULL DEFAULT 'UTC'"),
    ("user", "digest_hour", "INTEGER NOT NULL DEFAULT 8"),
    ("user", "notify_email_digest", "BOOLEAN NOT NULL DEFAULT 0"),
    ("user", "notify_email_deadlines", "BOOLEAN NOT NULL DEFAULT 0"),
    ("user", "notify_push_digest", "BOOLEAN NOT NULL DEFAULT 0"),
    ("user", "notify_push_deadlines", "BOOLEAN NOT NULL DEFAULT 0"),
]
INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_project_user_deadline ON project (user_id, deadline)",
    # 多个 NULL 不算重复，所以没填邮箱 / 没连 Google 的账号不受影响
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_email ON user (email)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_google_sub ON user (google_sub)",
]


def _add_column_if_missing(table, column, ddl):
    """表里没有这一列就补上，返回是否新加。"""
    columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
    if column in columns:
        return False
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    return True


def ensure_schema():
    """建新表 + 给旧表补新列 + 补索引。可以重复运行。"""
    from . import models  # noqa: F401  导入后 create_all 才知道有哪些表

    db.create_all()
    for table, column, ddl in COLUMNS:
        _add_column_if_missing(table, column, ddl)
    for statement in INDEXES:
        db.session.execute(text(statement))
    db.session.commit()
