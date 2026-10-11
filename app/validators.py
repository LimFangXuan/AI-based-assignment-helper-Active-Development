"""账号相关的输入校验：注册、Settings、Google 注册共用，规则只写一次。每个函数返回错误信息，没有错误返回 None。"""
import re

from sqlalchemy import func

from .constants import EMAIL_MAX_CHARS, PASSWORD_MIN_CHARS, USERNAME_RANGE
from .extensions import db
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
    # 只有“已验证”的邮箱才算被占用。没验证的只是对方自己填的、谁都可以填，不能因此挡住真正拥有这个邮箱的人
    if taken and taken.email_verified and (current_user is None or taken.id != current_user.id):
        return None, "That email is already used by another account."
    return email, None


def release_unverified(email, current_user=None):
    """把别的账号上“没验证过的”同名邮箱拿掉（数据库里邮箱唯一），让真正验证了这个邮箱的人可以使用。"""
    other = User.query.filter(User.email == email).first()
    if other and not other.email_verified and (current_user is None or other.id != current_user.id):
        other.email = None
        db.session.flush()
