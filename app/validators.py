"""账号相关的输入校验：注册、Settings、Google 注册共用，规则只写一次。每个函数返回错误信息，没有错误返回 None。"""
import re

from sqlalchemy import func

from .constants import EMAIL_MAX_CHARS, PASSWORD_MIN_CHARS, USERNAME_RANGE
from .models import User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def check_username(username, current_user=None):
    low, high = USERNAME_RANGE
    if not low <= len(username) <= high:
        return f"Username must be {low} to {high} characters."
    taken = User.query.filter(func.lower(User.username) == username.lower()).first()
    if taken and (current_user is None or taken.id != current_user.id):
        return "That username is already taken."
    return None


def check_password(password):
    if len(password) < PASSWORD_MIN_CHARS:
        return f"Password must be at least {PASSWORD_MIN_CHARS} characters."
    return None


def normalize_email(raw, current_user=None):
    """返回 (小写邮箱或 None, 错误信息)。空字符串表示不填，是允许的。"""
    email = (raw or "").strip().lower()
    if not email:
        return None, None
    if len(email) > EMAIL_MAX_CHARS or not EMAIL_RE.match(email):
        return None, "Enter a valid email address."
    taken = User.query.filter(User.email == email).first()
    if taken and (current_user is None or taken.id != current_user.id):
        return None, "That email is already used by another account."
    return email, None
