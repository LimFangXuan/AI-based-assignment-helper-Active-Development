from datetime import datetime

from ..extensions import db


class Task(db.Model):
    """项目里的一个步骤：可以打勾、有自己的日期。Today 和 Next 6 days 两个页面就是从这里来的。"""

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    detail = db.Column(db.Text)      # Task Planner 写的“做完是什么样子”
    based_on_assumption = db.Column(db.Boolean, nullable=False, default=False)  # 依赖还没确认的需求
    content_fingerprint = db.Column(db.String(64))  # AI 规划的任务：生成时的描述 + guideline 指纹；手动添加的为空
    due_date = db.Column(db.Date)
    minutes = db.Column(db.Integer)  # 预计用时（分钟），可以为空
    done = db.Column(db.Boolean, nullable=False, default=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    done_at = db.Column(db.DateTime)
