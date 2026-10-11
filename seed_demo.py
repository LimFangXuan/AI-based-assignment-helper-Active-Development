"""放一些示例数据，方便本机演示：python seed_demo.py

会创建账号 demo / demo1234（已存在就跳过）。只用于本机开发，不要在线上运行。
"""
from datetime import date, datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Project, Task, User

app = create_app()

DEMO_USER, DEMO_PASSWORD = "demo", "demo1234"

# (名称, 距今天数, 状态, 类型, 个人/小组, 描述, guideline, [(步骤, 距今天数, 分钟, 已完成)])
PROJECTS = [
    ("Data Structures Assignment 2: Hash Tables", 5, "in_progress", "software_development", "individual",
     "Implement a resizable hash table in C++ and compare linear probing with separate chaining. "
     "Write a 1,000-word report on the results.",
     "Marks: implementation 50%, performance analysis 30%, report 20%. Use only the C++ standard library.",
     [("Read the brief and list every marking criterion", 0, 20, True),
      ("Write the hash table interface and test cases", 0, 60, False),
      ("Implement the linear probing version", 1, 90, False),
      ("Implement the separate chaining version", 2, 90, False),
      ("Run the benchmarks and plot the results", 3, 60, False),
      ("Write the report and check the format", 4, 120, False)]),
    ("Marketing group report", 9, "not_started", "report", "group",
     "Analyse a local brand's social media strategy: a 3,000-word report plus a 10-minute presentation.",
     "",
     [("Agree on the brand and split the work", 0, 30, False),
      ("Collect the brand's posts from the last three months", 2, 90, False),
      ("Write my competitor analysis section", 5, 120, False),
      ("Merge the report and build the slides", 7, 120, False)]),
    ("Calculus problem set 5", -1, "in_progress", "exam_preparation", "individual",
     "Chapter 7 exercises 1 to 20.", "",
     [("Do questions 1 to 10", -2, 60, True), ("Do questions 11 to 20", -1, 60, False)]),
    ("Final year project proposal", 30, "not_started", "research_proposal", "individual",
     "Proposal for an app that helps students plan assignments.", "", []),
    ("Database design coursework", 12, "done", "system_database_design", "group",
     "Design and normalise a database for a library system.", "", []),
]

with app.app_context():
    if User.query.filter_by(username=DEMO_USER).first():
        print(f"User {DEMO_USER} already exists, skipping.")
    else:
        user = User(username=DEMO_USER)
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        db.session.flush()
        today = date.today()
        for name, days, status, ptype, mode, desc, guideline, tasks in PROJECTS:
            deadline = datetime.combine(today + timedelta(days=days), datetime.min.time()).replace(hour=23, minute=59)
            project = Project(user_id=user.id, name=name, deadline=deadline, status=status, type=ptype,
                              work_mode=mode, description=desc, guideline=guideline)
            db.session.add(project)
            db.session.flush()
            for i, (title, offset, minutes, done) in enumerate(tasks):
                db.session.add(Task(project_id=project.id, title=title, due_date=today + timedelta(days=offset),
                                    minutes=minutes, done=done, position=i,
                                    done_at=datetime.now() if done else None))
        db.session.commit()
        print(f"Created demo user {DEMO_USER} / {DEMO_PASSWORD} with {len(PROJECTS)} projects.")
