import os
from flask import Flask
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
    return "<h1>作业效率助手</h1><p>Flask 跑起来了吗</p>"

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)