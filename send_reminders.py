"""发送每日摘要和截止日提醒：python send_reminders.py

建议用系统的定时任务每小时运行一次（Windows 任务计划程序 / Linux cron / 托管平台的 Cron Job）。
每次运行只会发出“该发而还没发过”的提醒，所以多运行几次也不会重复（详见 app/reminders.py）。
"""
import json
import sys

from app import create_app, reminders

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        stats = reminders.run()
    print(json.dumps(stats))
    sys.exit(1 if stats["errors"] else 0)
