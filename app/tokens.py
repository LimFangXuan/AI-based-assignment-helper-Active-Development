"""邮件里的一次性链接令牌（带签名、有时效，不需要额外的数据库表）。

- 验证邮箱：令牌里记着用户 ID 和那个邮箱地址。用户之后改了邮箱，旧链接自动失效。
- 重置密码：令牌里记着当前密码哈希的指纹。密码一改（包括用这个链接改），同一个链接立刻失效，所以只能用一次。
令牌被改动、过期、或者属于别的用途（salt 不同）都会被拒绝，一律返回 None，调用方不需要区分原因。
"""
import hashlib

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

from .constants import RESET_PASSWORD_MAX_AGE, VERIFY_EMAIL_MAX_AGE
from .extensions import db
from .models import User


def _serializer(purpose):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=f"assignment-helper:{purpose}")


def _fingerprint(user):
    return hashlib.sha256(user.password_hash.encode("utf-8")).hexdigest()[:20]


def make_verify_token(user):
    return _serializer("verify-email").dumps({"u": user.id, "e": user.email})


def read_verify_token(token):
    """返回用户或 None。邮箱必须仍然是令牌发出时的那个。"""
    try:
        data = _serializer("verify-email").loads(token, max_age=VERIFY_EMAIL_MAX_AGE)
        user = db.session.get(User, data["u"])
    except (BadData, KeyError, TypeError):
        return None
    if user is None or not user.email or user.email != data.get("e"):
        return None
    return user


def make_reset_token(user):
    return _serializer("reset-password").dumps({"u": user.id, "p": _fingerprint(user)})


def read_reset_token(token):
    """返回用户或 None。密码在发出链接之后改过，或邮箱已不再是验证过的，都算失效。"""
    try:
        data = _serializer("reset-password").loads(token, max_age=RESET_PASSWORD_MAX_AGE)
        user = db.session.get(User, data["u"])
    except (BadData, KeyError, TypeError):
        return None
    if user is None or not user.email_verified or data.get("p") != _fingerprint(user):
        return None
    return user
