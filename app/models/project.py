import hashlib
from datetime import date, datetime

from ..constants import DEFAULT_TYPE, DEFAULT_WORK_MODE
from ..extensions import db


class Project(db.Model):
    __table_args__ = (db.Index("ix_project_user_deadline", "user_id", "deadline"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")  # 任务本身：题目、想法、老师的讲解。AI 的主要输入
    guideline = db.Column(db.Text, nullable=False, default="")    # 评分标准、格式要求、字数和各种限制
    type = db.Column(db.String(40), nullable=False, default=DEFAULT_TYPE)
    work_mode = db.Column(db.String(20), nullable=False, default=DEFAULT_WORK_MODE)
    citation_style = db.Column(db.String(30))
    deadline = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="not_started")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    prompt_sessions = db.relationship(
        "PromptSession", backref="project", cascade="all, delete-orphan",
        order_by="PromptSession.created_at.desc()",
    )
    paper_searches = db.relationship(
        "PaperSearch", backref="project", cascade="all, delete-orphan",
        order_by="PaperSearch.created_at.desc()",
    )
    tasks = db.relationship(
        "Task", backref="project", cascade="all, delete-orphan", order_by="(Task.position, Task.id)",
    )
    requirements_checks = db.relationship(
        "RequirementsCheck", backref="project", cascade="all, delete-orphan",
        order_by="RequirementsCheck.created_at.desc()",
    )
    report_drafts = db.relationship(
        "ReportDraft", backref="project", cascade="all, delete-orphan",
        order_by="ReportDraft.created_at.desc()",
    )

    @property
    def fingerprint(self):
        """描述 + guideline 的指纹。下游记录保存生成时的指纹，对不上就提示“内容已修改”（见 spec §4.6）。"""
        text = (self.description or "") + "\n---\n" + (self.guideline or "")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def progress(self):
        """(已完成步骤数, 总步骤数, 百分比)。"""
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t.done)
        return done, total, round(done * 100 / total) if total else 0

    @property
    def days_left(self):
        return (self.deadline.date() - date.today()).days

    @property
    def is_overdue(self):
        return self.deadline < datetime.now() and self.status in ("not_started", "in_progress")

