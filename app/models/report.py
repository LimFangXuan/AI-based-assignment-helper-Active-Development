from datetime import datetime

from ..extensions import db


class ReportDraft(db.Model):
    """Report Drafter 的一份草稿。阶段 5 才开始写入。"""

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    template_key = db.Column(db.String(40), nullable=False)
    outline_json = db.Column(db.Text, nullable=False, default="[]")
    content_fingerprint = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    sections = db.relationship("ReportSection", backref="draft", cascade="all, delete-orphan",
                               order_by="ReportSection.position")


class ReportSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    draft_id = db.Column(db.Integer, db.ForeignKey("report_draft.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending / draft / approved
    student_notes = db.Column(db.Text, nullable=False, default="")
    cited_paper_ids_json = db.Column(db.Text, nullable=False, default="[]")
