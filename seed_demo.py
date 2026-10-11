"""放一些示例数据，方便本机演示：python seed_demo.py

会创建账号 demo / demo1234（已存在就跳过）。只用于本机开发，不要在线上运行。
"""
from datetime import date, datetime, timedelta

from app import Project, Task, User, app, db

DEMO_USER, DEMO_PASSWORD = "demo", "demo1234"

PROJECTS = [
    ("数据结构 Assignment 2：哈希表", 5, "in_progress",
     "用 C++ 实现一个支持动态扩容的哈希表，对比线性探测和链地址法的性能，并写 1000 字报告。",
     [("读题，列出评分标准里的每一项", 0, 20, True), ("写出哈希表的接口和测试用例", 0, 60, False),
      ("实现线性探测版本", 1, 90, False), ("实现链地址法版本", 2, 90, False),
      ("跑性能对比并画图", 3, 60, False), ("写报告并检查格式", 4, 120, False)]),
    ("市场营销小组报告", 9, "not_started",
     "4 人小组，分析一个本地品牌的社交媒体策略，3000 字报告 + 10 分钟展示。",
     [("和组员确定品牌和分工", 0, 30, False), ("收集品牌近三个月的帖子数据", 2, 90, False),
      ("写自己负责的竞品分析部分", 5, 120, False), ("合并报告，做展示幻灯片", 7, 120, False)]),
    ("微积分作业 5", -1, "in_progress", "第 7 章习题 1 到 20 题。",
     [("做 1 到 10 题", -2, 60, True), ("做 11 到 20 题", -1, 60, False)]),
    ("毕业设计开题报告", 30, "not_started", "", []),
]

with app.app_context():
    if User.query.filter_by(username=DEMO_USER).first():
        print(f"账号 {DEMO_USER} 已存在，跳过。")
    else:
        user = User(username=DEMO_USER)
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        db.session.flush()
        today = date.today()
        for name, days, status, desc, tasks in PROJECTS:
            deadline = datetime.combine(today + timedelta(days=days), datetime.min.time()).replace(hour=23, minute=59)
            project = Project(user_id=user.id, name=name, deadline=deadline, status=status, description=desc)
            db.session.add(project)
            db.session.flush()
            for i, (title, offset, minutes, done) in enumerate(tasks):
                db.session.add(Task(project_id=project.id, title=title, due_date=today + timedelta(days=offset),
                                    minutes=minutes, done=done, position=i,
                                    done_at=datetime.now() if done else None))
        db.session.commit()
        print(f"已创建示例账号 {DEMO_USER} / {DEMO_PASSWORD} 和 {len(PROJECTS)} 个项目。")
