"""账号：注册 / 登录 / 登出，以及用 Google 账号登录、注册、连接（OAuth 授权码 + PKCE）。"""
import hmac
import os
import random
import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

from .. import login_throttle, validators
from ..extensions import db
from ..models import User
from ..services import google_auth
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
    if User.query.filter_by(email=profile["email"]).first():
        # 不自动合并：本站的邮箱是用户自己填的、没验证过，自动合并会让别人用你的邮箱抢你的账号
        flash("An account with this email already exists. Log in with your password, then connect Google "
              "in Settings.", "error")
        return redirect(url_for("auth.login"))
    user = User(username=username_from(profile), email=profile["email"], google_sub=profile["sub"])
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
    if not user.email and not User.query.filter_by(email=profile["email"]).first():
        user.email = profile["email"]
    db.session.commit()
    flash("Google account connected. You can now log in with Google.", "success")
    return redirect(back_to("link"))
