import json
from datetime import datetime

from ..extensions import db
from ..services import prompt_builder


class PromptSession(db.Model):
    """一次"生成 prompt"的完整记录。

    旧流程：AI 提的问题 → 学生的回答 → 摘要 → 最终 prompt。
    新流程（阶段 5）：以 RequirementsCheck 为输入，直接生成 framework_json 和最终 prompt，没有单独的提问阶段。
    旧列一律保留，旧记录仍能读取。
    """

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    requirements_check_id = db.Column(db.Integer, db.ForeignKey("requirements_check.id"))
    diagnosis_json = db.Column(db.Text)
    # 新流程没有提问阶段，所以允许为空。注意：旧数据库里这一列仍是 NOT NULL（SQLite 不能直接改约束），
    # 所以默认写 "[]"，新旧数据库都能插入
    questions_json = db.Column(db.Text, default="[]")
    answers_json = db.Column(db.Text)
    summary_json = db.Column(db.Text)
    framework_json = db.Column(db.Text)
    final_prompt = db.Column(db.Text)
    content_fingerprint = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    @property
    def questions(self):
        return json.loads(self.questions_json or "[]")

    @property
    def summary(self):
        return json.loads(self.summary_json) if self.summary_json else None

    @property
    def answers(self):
        return json.loads(self.answers_json) if self.answers_json else []

    @property
    def diagnosis(self):
        return json.loads(self.diagnosis_json) if self.diagnosis_json else None

    @property
    def blocked(self):
        return prompt_builder.is_blocked(self.summary)
