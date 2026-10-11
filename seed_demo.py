"""放示例数据，方便本机演示：python seed_demo.py

会（重新）创建账号 demo / demo1234，并放入一套完整的示例数据：一个项目走完全部五个工具（需求检查、framework 和
prompt、任务、论文、报告草稿），另外几个项目让 Overview、Today、日历都有内容。全部是虚构的。
已有的 demo 账号会被删掉重建。只用于本机，不要在有真实用户的数据库上运行。

只想给别人看、不想让任何内容发到外部服务时，用演示模式：DEMO_MODE=1 python run.py（见 README）。
"""
from app import create_app, demo_data
from app.extensions import db

DEMO_PASSWORD = "demo1234"

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        demo_data.reset(password=DEMO_PASSWORD)
        db.session.commit()
    print(f"Sample data ready. Log in as {demo_data.DEMO_USERNAME} / {DEMO_PASSWORD}.")
