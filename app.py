import os
from flask import Flask, render_template, request, redirect, url_for, session
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app=Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"

db = SQLAlchemy(app)

class User(db.Model):
    # 每个用户的编号，自动递增，是这一行数据的唯一标识
    id = db.Column(db.Integer, primary_key=True)

    # 用户名：最长80个字符，不能重复（unique），不能为空（nullable=False）
    username = db.Column(db.String(80), unique=True, nullable=False)

    # 列名叫 password_hash，类型是 db.String(255)，不能为空
    password_hash = db.Column(db.String(255),nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash,password)


    

@app.route("/")
def home():
    user_id = session.get("user_id")

    # 如果 user_id 是 None（没登录），跳转到登录页
    if user_id is None:
        return redirect(url_for("login"))
    
    # 根据编号从数据库取出用户
    user = db.session.get(User, user_id)
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    return render_template("home.html", name=user.username)

# methods 声明这个网址同时接受 GET（看页面）和 POST（提交数据）
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        # 检查用户名是否已被注册
        existing = User.query.filter_by(username=username).first()
        if existing:
            return render_template("register.html", error="用户名已被使用")

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        return redirect(url_for("home"))

    # GET 请求：直接显示空表单
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # 从表单取出 username 和 password
        username = request.form["username"]
        password = request.form["password"]

        # 按用户名查找用户，找不到时 user 是 None
        user = User.query.filter_by(username=username).first()

        
        # 条件：user 存在，并且 user.check_password(password) 为真
        # 成功：把 user.id 存进 session["user_id"]，然后跳转到首页
        # 失败：return render_template("login.html", error="用户名或密码错误")
        if user and user.check_password(password):
            session["user_id"] = user.id
            return redirect(url_for("home"))
            
        return render_template("login.html", error="用户名或密码错误")


    return render_template("login.html")

@app.route("/logout")
def logout():
    #清空 session，然后跳转到登录页
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)