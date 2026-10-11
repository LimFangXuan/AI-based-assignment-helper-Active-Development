"""账号：注册 / 登录 / 登出 / 设置。"""
from flask import Blueprint, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import User
from ..security import login_required

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        error = None
        if not 3 <= len(username) <= 80:
            error = "Username must be 3 to 80 characters."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."

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
            return render_template("pages/register.html", error=error, username=username)

        session.clear()
        session["user_id"] = user.id
        return redirect(url_for("overview.index"))

    return render_template("pages/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        # 用户名不存在和密码错误提示同一句，避免被人用来试探哪些用户名已注册
        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            return redirect(url_for("overview.index"))
        return render_template("pages/login.html", error="Incorrect username or password.", username=username)

    return render_template("pages/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/settings")
@login_required
def settings():
    return render_template("pages/settings.html")
