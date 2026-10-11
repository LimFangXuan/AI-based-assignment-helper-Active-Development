import json
from datetime import datetime

from ..extensions import db
from ..services.citations import format_citation


class PaperSearch(db.Model):
    """一次论文检索：记录检索词、候选数量和依据的摘要，让每篇推荐都能追溯来源。"""

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("prompt_session.id"))  # 检索依据的那次已确认摘要
    queries_json = db.Column(db.Text, nullable=False)
    requested_count = db.Column(db.Integer, nullable=False, default=5)
    oa_only = db.Column(db.Boolean, nullable=False, default=True)
    candidate_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    papers = db.relationship("Paper", backref="search", cascade="all, delete-orphan", order_by="Paper.rank")

    @property
    def queries(self):
        return json.loads(self.queries_json)


class Paper(db.Model):
    """AI 从候选中选出的一篇论文。除了 reason 和 relevance，所有字段都来自 OpenAlex。"""

    id = db.Column(db.Integer, primary_key=True)
    search_id = db.Column(db.Integer, db.ForeignKey("paper_search.id"), nullable=False)
    openalex_id = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    authors = db.Column(db.String(500), nullable=False, default="")
    author_list_json = db.Column(db.Text, nullable=False, default="[]")
    year = db.Column(db.Integer)
    venue = db.Column(db.String(300))
    doi = db.Column(db.String(200))
    url = db.Column(db.String(500))       # 只允许 http/https，在 openalex_client 里检查过
    oa_url = db.Column(db.String(500))
    is_oa = db.Column(db.Boolean, nullable=False, default=False)
    cited_by_count = db.Column(db.Integer, nullable=False, default=0)
    work_type = db.Column(db.String(40))
    volume = db.Column(db.String(20))
    issue = db.Column(db.String(20))
    pages = db.Column(db.String(40))
    abstract_snippet = db.Column(db.Text, nullable=False, default="")
    reason = db.Column(db.Text, nullable=False)  # AI 的推荐理由（只依据标题和摘要）
    relevance = db.Column(db.Integer)            # AI 给的相关度 1-10，仅供个人筛选
    rank = db.Column(db.Integer, nullable=False)

    @property
    def author_list(self):
        return json.loads(self.author_list_json or "[]")

    @property
    def citation(self):
        return format_citation(self)
