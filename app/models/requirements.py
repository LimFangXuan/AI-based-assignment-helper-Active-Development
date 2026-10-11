import json
from datetime import datetime

from ..extensions import db


class RequirementsCheck(db.Model):
    """Requirements Checklist 的一次记录。每个项目可以有多次，最新的一次生效（spec §7.1）。"""

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="in_progress")  # in_progress / complete / complete_with_assumptions
    round_number = db.Column(db.Integer, nullable=False, default=0)          # 当前等待回答的是第几轮（内部上限，不显示）
    aspects_json = db.Column(db.Text, nullable=False, default="[]")
    history_json = db.Column(db.Text, nullable=False, default="[]")          # 每轮：问了什么、学生怎么答
    conflicts_json = db.Column(db.Text, nullable=False, default="[]")
    questions_json = db.Column(db.Text, nullable=False, default="[]")        # 当前这一轮等待回答的问题
    content_fingerprint = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    @property
    def aspects(self):
        return json.loads(self.aspects_json or "[]")

    @property
    def conflicts(self):
        return json.loads(self.conflicts_json or "[]")

    @property
    def questions(self):
        return json.loads(self.questions_json or "[]")

    @property
    def history(self):
        return json.loads(self.history_json or "[]")

    @property
    def finished(self):
        return self.status in ("complete", "complete_with_assumptions")

    @property
    def open_conflicts(self):
        return [c for c in self.conflicts if c["status"] == "open"]

    def counts(self):
        """各状态的方面数量，页面上的进度用。"""
        result = {"clear": 0, "unclear": 0, "na": 0, "assumed": 0}
        for a in self.aspects:
            result[a["state"]] = result.get(a["state"], 0) + 1
        return result

    def set_state(self, aspects=None, conflicts=None, questions=None):
        if aspects is not None:
            self.aspects_json = json.dumps(aspects, ensure_ascii=False)
        if conflicts is not None:
            self.conflicts_json = json.dumps(conflicts, ensure_ascii=False)
        if questions is not None:
            self.questions_json = json.dumps(questions, ensure_ascii=False)
