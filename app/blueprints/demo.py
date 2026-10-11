"""作品集演示模式（DEMO_MODE=1）的入口和限制。

- POST /demo/enter：一键进入共用的演示账号（没有就先创建示例数据）。
- POST /demo/reset：把演示账号恢复成初始的示例数据。
- 拦截所有“会改账号”或“会连外部服务”的地址：注册、Google 登入、忘记密码、验证邮箱、Settings 里的修改、推送、定时任务入口。
不在演示模式时，这两个入口都是 404，拦截也不生效。
"""
from flask import Blueprint, abort, flash, jsonify, redirect, request, url_for

from .. import demo_data
from ..extensions import db
from ..services import demo_mode
from .auth import start_session

bp = Blueprint("demo", __name__)

OFF_MESSAGE = "This is turned off in the portfolio demo."
# 演示模式下整页关闭的地址（跳回登录页）
CLOSED_PAGES = {"auth.register", "auth.forgot_password", "auth.reset_password", "auth.verify_email",
                "auth.google_start", "auth.google_callback"}
# Settings 里只允许“下载我的数据”，其余修改都拦下
SETTINGS_ALLOWED = {"settings.index", "settings.export"}


@bp.before_app_request
def demo_guard():
    if not demo_mode.enabled():
        return None
    endpoint = request.endpoint or ""
    if endpoint == "cron.reminders":
        abort(404)
    if endpoint in CLOSED_PAGES:
        flash("Sign-up and sign-in options are turned off in the portfolio demo. Use “Enter the demo”.", "error")
        return redirect(url_for("auth.login"))
    if endpoint.startswith("settings.") and endpoint not in SETTINGS_ALLOWED:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": OFF_MESSAGE}), 403
        flash(OFF_MESSAGE, "error")
        return redirect(url_for("settings.index"))
    return None


@bp.route("/demo/enter", methods=["POST"])
def enter():
    if not demo_mode.enabled():
        abort(404)
    from ..models import User

    user = User.query.filter_by(username=demo_data.DEMO_USERNAME).first() or demo_data.reset()
    start_session(user)
    return redirect(url_for("overview.index"))


@bp.route("/demo/reset", methods=["POST"])
def reset():
    if not demo_mode.enabled():
        abort(404)
    user = demo_data.reset()
    db.session.commit()
    start_session(user)
    flash("Demo data reset to the original sample.", "success")
    return redirect(url_for("overview.index"))
