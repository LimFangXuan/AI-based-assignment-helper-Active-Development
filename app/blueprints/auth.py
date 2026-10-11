"""账号：注册 / 登录 / 登出，以及用 Google 账号登录、注册、连接（OAuth 授权码 + PKCE）。"""
import hmac
import os
import random
import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

from .. import account_mail, login_throttle, tokens, validators
from .. import emails
from ..constants import EMAIL_REQUEST_LIMIT
from ..extensions import db
from ..models import User
from ..services import google_auth, mailer
from ..services.google_auth import GoogleAuthError

bp = Blueprint("auth", __name__)


def start_session(user):
    """登录成功：换一份全新的 session（防止 session 固定攻击），只留 user_id。"""
    session.clear()
    session["user_id"] = user.id


def render_auth(template, **kw):
    return render_template(template, **kw)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        error = validators.check_username(username) or validators.check_password(password)

        if error is None:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:  # 两个人同时注册同名时，数据库的 unique 兜底
                db.session.rollback()
                error = "That username is already taken."

        if error:
            return render_auth("pages/register.html", error=error, username=username)

        start_session(user)
        return redirect(url_for("overview.index"))

    return render_auth("pages/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = login_throttle.login_key(username)
        blocked = login_throttle.blocked_message(key)
        if blocked:
            return render_auth("pages/login.html", error=blocked, username=username)

        user = User.query.filter_by(username=username).first()
        # 用户名不存在、密码错误、账号没有密码（只用 Google 注册）提示同一句，避免被人用来试探哪些用户名已注册
        if user and user.check_password(password):
            login_throttle.reset(key)
            start_session(user)
            return redirect(url_for("overview.index"))
        login_throttle.record_failure(key)
        return render_auth("pages/login.html", error="Incorrect username or password.", username=username)

    return render_auth("pages/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# ======================= 忘记密码 / 验证邮箱 =======================
def too_many(key_kinds):
    return any(login_throttle.seconds_blocked(k) for k in key_kinds)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """输入邮箱，收到重置链接。无论邮箱存不存在、有没有验证，页面和回复都一样，不泄露哪些邮箱注册过。"""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        keys = (f"forgot-ip|{request.remote_addr}", f"forgot-email|{email}")
        if too_many(keys):
            flash("Too many requests. Please wait a few minutes and try again.", "error")
            return render_template("pages/forgot_password.html", email=email, mail_enabled=mailer.enabled())
        for k in keys:
            login_throttle.record_failure(k, limit=EMAIL_REQUEST_LIMIT)  # 每次请求都计数（限制发信频率，防止被用来骚扰别人）
        user = User.query.filter_by(email=email).first() if email else None
        if user and user.email_verified and mailer.enabled():
            account_mail.send_reset(user)
        return render_template("pages/forgot_password.html", sent=True, email=email, mail_enabled=mailer.enabled())
    return render_template("pages/forgot_password.html", mail_enabled=mailer.enabled())


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = tokens.read_reset_token(token)
    if user is None:
        return render_template("pages/reset_password.html", invalid=True), 400
    if request.method == "POST":
        new, confirm = request.form.get("new_password", ""), request.form.get("confirm_password", "")
        error = validators.check_password(new)
        if error is None and new != confirm:
            error = "The two passwords don't match."
        if error:
            return render_template("pages/reset_password.html", token=token, error=error)
        user.set_password(new)  # 令牌里绑着旧密码的指纹，所以这个链接现在失效了
        db.session.commit()
        account_mail.send_notice(user, emails.password_changed(user, "reset"))
        login_throttle.reset(login_throttle.login_key(user.username))
        flash("Your password was reset. Log in with the new password.", "success")
        return redirect(url_for("auth.login"))
    return render_template("pages/reset_password.html", token=token)


@bp.route("/verify-email/<token>")
def verify_email(token):
    user = tokens.read_verify_token(token)
    if user is None:
        flash("This confirmation link is invalid or has expired. Request a new one from Settings.", "error")
        return redirect(url_for("settings.index") if session.get("user_id") else url_for("auth.login"))
    validators.release_unverified(user.email, user)
    user.email_verified = True
    db.session.commit()
    flash("Your email address is confirmed.", "success")
    return redirect(url_for("settings.index") + "#profile" if session.get("user_id") == user.id else url_for("auth.login"))


# ======================= Google 登录 =======================
def redirect_uri():
    """必须和 Google Cloud Console 里登记的“已授权的重定向 URI”一字不差。部署在代理后面时用 GOOGLE_REDIRECT_URI 指定。"""
    return os.getenv("GOOGLE_REDIRECT_URI", "").strip() or url_for("auth.google_callback", _external=True)


def back_to(intent):
    return url_for("settings.index") + "#connected" if intent == "link" else url_for("auth.login")


@bp.route("/auth/google")
def google_start():
    """把用户送去 Google。intent=login（登录或注册，默认）或 link（已登录的用户连接自己的 Google 账号）。"""
    intent = "link" if request.args.get("intent") == "link" else "login"
    if intent == "link" and session.get("user_id") is None:
        return redirect(url_for("auth.login"))
    if not google_auth.configured():
        flash("Google sign-in is not set up on this server yet.", "error")
        return redirect(back_to(intent))
    state, verifier = google_auth.new_state_and_verifier()
    session["oauth"] = {"state": state, "verifier": verifier, "intent": intent}
    return redirect(google_auth.authorization_url(redirect_uri(), state, verifier))


def username_from(profile):
    """给用 Google 注册的人起一个不重复的用户名：邮箱 @ 前面的部分，撞了就加数字。之后可以在 Settings 里改。"""
    base = re.sub(r"[^A-Za-z0-9._-]", "", profile["email"].split("@")[0])[:30] or "student"
    if len(base) < 3:
        base = (base + "user")[:30]
    candidate = base
    while validators.check_username(candidate):
        candidate = f"{base}{random.randint(10, 9999)}"
    return candidate


@bp.route("/auth/google/callback")
def google_callback():
    saved = session.pop("oauth", None)  # 一次性：用过就删，回调页面被重放也没用
    intent = (saved or {}).get("intent", "login")
    sent_state = request.args.get("state", "")
    if (not saved or not hmac.compare_digest(sent_state.encode(), saved["state"].encode())
            or request.args.get("error") or not request.args.get("code")):
        flash("Google sign-in was cancelled or expired. Please try again.", "error")
        return redirect(back_to(intent))
    try:
        profile = google_auth.fetch_profile(request.args["code"], saved["verifier"], redirect_uri())
    except GoogleAuthError as e:
        flash(e.user_message, "error")
        return redirect(back_to(intent))

    if intent == "link":
        return link_google(profile)

    user = User.query.filter_by(google_sub=profile["sub"]).first()
    if user:  # 已经连接过：直接登录
        start_session(user)
        return redirect(url_for("overview.index"))
    existing = User.query.filter_by(email=profile["email"]).first()
    if existing and existing.email_verified:
        # 两边都验证过这个邮箱，可以安全地把 Google 连到已有的账号上
        if existing.google_sub:
            flash("That email belongs to an account connected to a different Google account.", "error")
            return redirect(url_for("auth.login"))
        existing.google_sub = profile["sub"]
        db.session.commit()
        start_session(existing)
        flash("Google was connected to your existing account.", "success")
        return redirect(url_for("overview.index"))
    if existing:
        # 对方只是自己填了这个邮箱、没验证过，不能凭它抢走账号；Google 验证过的邮箱优先，把没验证的占用拿掉
        validators.release_unverified(profile["email"])
    user = User(username=username_from(profile), email=profile["email"], email_verified=True, google_sub=profile["sub"])
    user.set_unusable_password()
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:  # 极少见：同时有人用了同名 / 同一个 Google 账号
        db.session.rollback()
        flash("Could not create your account. Please try again.", "error")
        return redirect(url_for("auth.login"))
    start_session(user)
    flash(f"Welcome, {user.username}! Your account was created with Google.", "success")
    return redirect(url_for("overview.index"))


def link_google(profile):
    """已登录的用户把 Google 账号连到自己的账号上。"""
    user = db.session.get(User, session.get("user_id"))
    if user is None:
        return redirect(url_for("auth.login"))
    other = User.query.filter_by(google_sub=profile["sub"]).first()
    if other and other.id != user.id:
        flash("That Google account is already connected to another account.", "error")
        return redirect(back_to("link"))
    user.google_sub = profile["sub"]
    if user.email == profile["email"]:
        user.email_verified = True  # Google 已经证明这个邮箱属于同一个人
    elif not user.email:
        holder = User.query.filter_by(email=profile["email"]).first()
        if holder is None or (not holder.email_verified and holder.id != user.id):
            validators.release_unverified(profile["email"], user)
            user.email, user.email_verified = profile["email"], True
    db.session.commit()
    flash("Google account connected. You can now log in with Google.", "success")
    return redirect(back_to("link"))
