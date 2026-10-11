"""登录防暴力破解：同一个“用户名 + 来源地址”在时间窗口内失败太多次，就暂时拒绝。

记录放在进程内存里：重启或多进程部署时不共享，所以这是一道基本防线，不是完整的风控。
成功登录会清零。也用于 Settings 里验证当前密码（改密码、删除账号）。
"""
import time

from flask import request

from .constants import LOGIN_MAX_FAILURES, LOGIN_WINDOW_SECONDS

_failures = {}


def login_key(username):
    return f"login|{(username or '').strip().lower()}|{request.remote_addr}"


def user_key(user_id):
    return f"user|{user_id}|{request.remote_addr}"


def _recent(key, now):
    kept = [t for t in _failures.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _failures[key] = kept
    return kept


_limits = {}  # 个别 key 用自己的上限（例如“忘记密码”按发信频率限制）


def seconds_blocked(key):
    """还要等几秒才能再试；没被限制返回 0。"""
    now = time.time()
    recent = _recent(key, now)
    if len(recent) < _limits.get(key, LOGIN_MAX_FAILURES):
        return 0
    return int(recent[0] + LOGIN_WINDOW_SECONDS - now) + 1


def blocked_message(key):
    wait = seconds_blocked(key)
    if not wait:
        return None
    minutes = max(1, -(-wait // 60))
    return f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."


def record_failure(key, limit=None):
    _failures.setdefault(key, []).append(time.time())
    if limit:
        _limits[key] = limit


def reset(key):
    _failures.pop(key, None)


def reset_all():
    _failures.clear()
    _limits.clear()
