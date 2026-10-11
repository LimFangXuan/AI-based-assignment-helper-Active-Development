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
]
INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_project_user_deadline ON project (user_id, deadline)",
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
