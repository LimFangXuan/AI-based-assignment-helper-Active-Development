"""登录检查、CSRF 防护、所有权检查。所有需要“这是不是你的东西”的地方都用这里的函数。"""
import hmac
import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from .extensions import db
from .models import Project, User


def login_required(view):
    """需要登录的页面都套上这个装饰器，不用每个函数重复写检查。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id is not None else None
        if user is None:
            session.clear()  # session 里的用户已不存在（比如数据库被重建）
            return redirect(url_for("auth.login"))
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def get_own_project(project_id):
    """取项目；不存在或不属于当前用户都返回 404，不暴露别人的项目是否存在。"""
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != g.user.id:
        abort(404)
    return project


def get_own_child(model, child_id, project, field="project_id"):
    """取项目下的子记录（步骤、prompt 记录……）；不属于这个项目就 404。"""
    child = db.session.get(model, child_id)
    if child is None or getattr(child, field) != project.id:
        abort(404)
    return child


# ---- CSRF 防护：所有 POST 表单必须带上服务器发的随机令牌 ----
def get_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]


def check_csrf():
    """注册为 before_request：任何 POST 都必须带正确的令牌。"""
    if request.method == "POST" and request.endpoint != "cron.reminders":  # cron 入口用自己的令牌，不是浏览器表单
        sent = request.form.get("_csrf_token", "").encode()
        expected = session.get("_csrf_token", "").encode()
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, "This form has expired. Refresh the page and try again.")


def safe_next(default):
    """只允许跳回本站的相对路径，防止被当成开放重定向。"""
    target = request.form.get("next", "")
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default
