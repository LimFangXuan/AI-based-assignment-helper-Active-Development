from datetime import datetime

from ..extensions import db


class RequirementsCheck(db.Model):
    """Requirements Checklist 的一次记录（每个项目可以有多次，最新的一次生效）。阶段 5 才开始写入。"""

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="in_progress")  # in_progress / complete / complete_with_assumptions
    round_number = db.Column(db.Integer, nullable=False, default=0)
    aspects_json = db.Column(db.Text, nullable=False, default="[]")
    history_json = db.Column(db.Text, nullable=False, default="[]")
    content_fingerprint = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
