"""Settings：个人资料、密码、已连接的账号、外观、隐私与数据（下载 / 删除）。

敏感操作（改密码、删除账号）要求再输入一次当前密码，并共用登录的防暴力破解限制。
只用 Google 注册的账号没有密码：它们可以先“设置密码”，删除账号时改为输入用户名确认。
"""
from datetime import datetime

from flask import Blueprint, Response, flash, g, redirect, render_template, request, session, url_for

from .. import data_export, login_throttle, validators
from ..extensions import db
from ..security import login_required
from ..services import google_auth

bp = Blueprint("settings", __name__, url_prefix="/settings")


def back(anchor=""):
    return redirect(url_for("settings.index") + anchor)


def password_ok(user):
    """验证表单里的 current_password。返回 (是否通过, 错误信息)。失败计入限制。"""
    key = login_throttle.user_key(user.id)
    blocked = login_throttle.blocked_message(key)
    if blocked:
        return False, blocked
    if user.check_password(request.form.get("current_password", "")):
        login_throttle.reset(key)
        return True, None
    login_throttle.record_failure(key)
    return False, "Your current password is not correct."


@bp.route("")
@login_required
def index():
    return render_template("pages/settings.html", google_enabled=google_auth.configured(),
                           project_count=len(g.user.projects))


@bp.route("/profile", methods=["POST"])
@login_required
def profile():
    username = request.form.get("username", "").strip()
    email, email_error = validators.normalize_email(request.form.get("email"), g.user)
    error = validators.check_username(username, g.user) or email_error
    if error:
        flash(error, "error")
        return back("#profile")
    g.user.username, g.user.email = username, email
    db.session.commit()
    flash("Profile updated.", "success")
    return back("#profile")


@bp.route("/password", methods=["POST"])
@login_required
def password():
    user = g.user
    new, confirm = request.form.get("new_password", ""), request.form.get("confirm_password", "")
    if user.has_password:
        ok, error = password_ok(user)
        if not ok:
            flash(error, "error")
            return back("#security")
    error = validators.check_password(new)
    if error is None and new != confirm:
        error = "The two new passwords don't match."
    if error is None and user.has_password and new == request.form.get("current_password", ""):
        error = "Choose a password different from the current one."
    if error:
        flash(error, "error")
        return back("#security")
    had_password = user.has_password
    user.set_password(new)
    db.session.commit()
    uid = user.id
    session.clear()  # 换一份新的 session，旧的登录凭证作废
    session["user_id"] = uid
    flash("Password changed." if had_password else "Password set. You can now also log in with your username.", "success")
    return back("#security")


@bp.route("/google/disconnect", methods=["POST"])
@login_required
def google_disconnect():
    user = g.user
    if not user.has_password:
        flash("Set a password first, so you can still log in after disconnecting Google.", "error")
        return back("#connected")
    user.google_sub = None
    db.session.commit()
    flash("Google account disconnected.", "success")
    return back("#connected")


@bp.route("/export", methods=["POST"])
@login_required
def export():
    """下载我的数据（JSON）。用 POST + CSRF 令牌，避免别的网站诱导浏览器下载你的数据。"""
    name = f"assignment-helper-data-{datetime.now():%Y%m%d}.json"
    return Response(data_export.export_json(g.user), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@bp.route("/delete", methods=["POST"])
@login_required
def delete_account():
    user = g.user
    if request.form.get("confirm_username", "").strip() != user.username:
        flash("Type your username exactly to confirm.", "error")
        return back("#delete")
    if user.has_password:
        ok, error = password_ok(user)
        if not ok:
            flash(error, "error")
            return back("#delete")
    db.session.delete(user)  # 项目、步骤、需求检查、prompt、论文、报告草稿都会一起删除（cascade）
    db.session.commit()
    session.clear()
    flash("Your account and all its data have been deleted.", "success")
    return redirect(url_for("auth.login"))
