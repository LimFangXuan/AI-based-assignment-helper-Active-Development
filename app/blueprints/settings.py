"""Settings：个人资料、密码、已连接的账号、外观、隐私与数据（下载 / 删除）。

敏感操作（改密码、删除账号）要求再输入一次当前密码，并共用登录的防暴力破解限制。
只用 Google 注册的账号没有密码：它们可以先“设置密码”，删除账号时改为输入用户名确认。
"""
import re
import zoneinfo
from datetime import datetime

from flask import Blueprint, Response, flash, g, jsonify, redirect, render_template, request, session, url_for

from .. import account_mail, data_export, emails, login_throttle, reminders, validators
from ..constants import DIGEST_LAST_HOUR, MAX_PUSH_DEVICES
from ..extensions import db
from ..models import PushSubscription
from ..security import login_required
from ..services import demo_mode, google_auth, mailer, push

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


def _timezones():
    zones = sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "posix", "right", "SystemV", "US/")))
    return ["UTC"] + zones


TIMEZONES = _timezones()


@bp.route("")
@login_required
def index():
    return render_template("pages/settings.html", google_enabled=google_auth.configured(),
                           project_count=len(g.user.projects), mail_enabled=mailer.enabled(), mail_real=mailer.real(),
                           vapid_key="" if demo_mode.enabled() else push.public_key(), timezones=TIMEZONES, digest_last_hour=DIGEST_LAST_HOUR,
                           devices=sorted(g.user.push_subscriptions, key=lambda d: d.created_at, reverse=True),
                           email_ready=reminders.email_usable(g.user))


@bp.route("/profile", methods=["POST"])
@login_required
def profile():
    username = request.form.get("username", "").strip()
    email, email_error = validators.normalize_email(request.form.get("email"), g.user)
    error = validators.check_username(username, g.user) or email_error
    if error:
        flash(error, "error")
        return back("#profile")
    user = g.user
    old_email, was_verified = user.email, user.email_verified
    user.username = username
    message = "Profile updated."
    if email != old_email:
        if email:
            validators.release_unverified(email, user)
        user.email, user.email_verified = email, False  # 新邮箱要重新验证；旧的验证作废
    db.session.commit()
    if email != old_email:
        if old_email and was_verified:
            account_mail.send_notice(user, emails.email_changed(user, email or "(removed)"), address=old_email)
        if email:
            ok, note = account_mail.send_verification(user)
            message = f"Profile updated. {note}" if ok else f"Profile updated, but the confirmation email was not sent: {note}"
    flash(message, "success")
    return back("#profile")


@bp.route("/email/resend", methods=["POST"])
@login_required
def resend_verification():
    user = g.user
    if user.email_verified:
        flash("Your email address is already confirmed.", "success")
        return back("#profile")
    key = login_throttle.user_key(f"verify-{user.id}")
    if login_throttle.seconds_blocked(key):
        flash("Too many requests. Please wait a few minutes and try again.", "error")
        return back("#profile")
    login_throttle.record_failure(key, limit=5)
    ok, note = account_mail.send_verification(user)
    flash(note, "success" if ok else "error")
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
    account_mail.send_notice(user, emails.password_changed(user, "changed" if had_password else "set"))
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


# ======================= 通知 =======================
B64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


@bp.route("/notifications", methods=["POST"])
@login_required
def notifications():
    user = g.user
    tz = request.form.get("timezone", "")
    try:
        zoneinfo.ZoneInfo(tz)
        hour = int(request.form.get("digest_hour", ""))
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError):
        flash("Choose a valid time zone and hour.", "error")
        return back("#notifications")
    if not 0 <= hour < DIGEST_LAST_HOUR:
        flash("Choose an hour for the daily summary before 10 pm.", "error")
        return back("#notifications")
    flags = {name: request.form.get(name) == "1" for name in
             ("notify_email_digest", "notify_email_deadlines", "notify_push_digest", "notify_push_deadlines")}
    if (flags["notify_email_digest"] or flags["notify_email_deadlines"]) and not reminders.email_usable(user):
        flash("Confirm your email address first, then you can turn on email notifications.", "error")
        return back("#notifications")
    if (flags["notify_push_digest"] or flags["notify_push_deadlines"]) and not user.push_subscriptions:
        flash("Enable push notifications on this device first.", "error")
        return back("#notifications")
    user.timezone, user.digest_hour = tz, hour
    for name, value in flags.items():
        setattr(user, name, value)
    db.session.commit()
    flash("Notification settings saved.", "success")
    return back("#notifications")


@bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    """浏览器订阅成功后，把这台设备登记到当前账号。同一台设备换了账号登录，就归到新账号名下。"""
    endpoint = request.form.get("endpoint", "").strip()
    p256dh, auth = request.form.get("p256dh", "").strip(), request.form.get("auth", "").strip()
    if (not endpoint.startswith("https://") or len(endpoint) > 1000 or not B64URL.match(p256dh) or not B64URL.match(auth)
            or not 60 <= len(p256dh) <= 200 or not 10 <= len(auth) <= 100):
        return jsonify({"ok": False, "error": "This device sent an invalid subscription."}), 400
    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if sub is None:
        if len(g.user.push_subscriptions) >= MAX_PUSH_DEVICES:
            return jsonify({"ok": False, "error": f"You can register at most {MAX_PUSH_DEVICES} devices. Remove one first."}), 400
        sub = PushSubscription(endpoint=endpoint)
        db.session.add(sub)
    sub.user_id, sub.p256dh, sub.auth = g.user.id, p256dh, auth
    sub.user_agent = (request.headers.get("User-Agent") or "")[:300]
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    sub = PushSubscription.query.filter_by(endpoint=request.form.get("endpoint", ""), user_id=g.user.id).first()
    if sub:
        db.session.delete(sub)
        db.session.commit()
    _drop_push_prefs_if_no_devices()
    return jsonify({"ok": True})


@bp.route("/push/<int:device_id>/remove", methods=["POST"])
@login_required
def push_remove(device_id):
    sub = PushSubscription.query.filter_by(id=device_id, user_id=g.user.id).first()
    if sub:
        db.session.delete(sub)
        db.session.commit()
        _drop_push_prefs_if_no_devices()
        flash("Device removed.", "success")
    return back("#notifications")


def _drop_push_prefs_if_no_devices():
    """没有任何设备了，推送开关自动关掉，避免界面上显示“已开启”但其实没有地方可发。"""
    db.session.refresh(g.user)
    if not g.user.push_subscriptions and (g.user.notify_push_digest or g.user.notify_push_deadlines):
        g.user.notify_push_digest = g.user.notify_push_deadlines = False
        db.session.commit()


@bp.route("/notifications/test", methods=["POST"])
@login_required
def notifications_test():
    user = g.user
    key = login_throttle.user_key(f"test-{user.id}")
    if login_throttle.seconds_blocked(key):
        flash("Too many test messages. Please wait a few minutes.", "error")
        return back("#notifications")
    login_throttle.record_failure(key, limit=10)
    if request.form.get("channel") == "push":
        ok, note = reminders.deliver_push(user, "It works", "Push notifications are working on this device.",
                                          url_for("settings.index"), "test")
    else:
        ok, note = reminders.deliver_email(user, emails.test_message(user))
        if ok and not mailer.real():
            note = "Email isn't configured on this server, so the test message was printed in the server log instead."
    flash(note, "success" if ok else "error")
    return back("#notifications")
