from datetime import datetime

from ..extensions import db


class PushSubscription(db.Model):
    """一台设备的 Web Push 订阅。endpoint 是推送服务给这台浏览器的专属地址，全局唯一。"""

    __table_args__ = (db.Index("ix_push_endpoint", "endpoint", unique=True),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    endpoint = db.Column(db.String(1000), nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    user_agent = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def as_info(self):
        """pywebpush 需要的订阅信息格式。"""
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


class NotificationLog(db.Model):
    """已经发出的提醒。(user_id, kind, ref_key) 唯一：同一条提醒绝不会发第二次（例如同一个项目的“截止前 24 小时”）。"""

    __table_args__ = (db.Index("ix_notification_unique", "user_id", "kind", "ref_key", unique=True),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(30), nullable=False)       # digest / deadline-3d / deadline-1d
    ref_key = db.Column(db.String(100), nullable=False)   # digest: 本地日期；deadline: 项目 id + 截止时间
    channels = db.Column(db.String(40), nullable=False, default="")
    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
