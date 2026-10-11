"""启动入口：python run.py（本机开发）。部署时用 WSGI 服务器指向 run:app。"""
import os

from app import create_app

app = create_app()  # create_app 里已经运行 ensure_schema()：建新表、给旧表补新列，已有数据不会动

if __name__ == "__main__":
    # 调试模式会开启 Werkzeug 调试器（可以在网页上执行代码），只能在本机开发时打开
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
