import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

app=Flask(__name__)
app.config["SECRET KEY"] = os.getenv("SECRET_KEY")

@app.route("/")
def home():
    return "<h1>作业效率助手</h1><p>Flask 跑起来吗</p>"

if __name__ == "__main__":
    app.run(debug=True)