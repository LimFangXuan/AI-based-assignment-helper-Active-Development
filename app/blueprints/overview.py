"""Overview（首页）、Today、Next 6 days 三个页面。"""
from datetime import date, datetime, timedelta

from flask import Blueprint, g, render_template

from ..constants import ACTIVE_STATUSES, UPCOMING_DAYS
from ..models import Project, Task
from ..security import login_required

bp = Blueprint("overview", __name__)


def active_projects():
    return (Project.query.filter(Project.user_id == g.user.id, Project.status != "submitted")
            .order_by(Project.deadline.asc()).all())


def open_tasks(until, since=None):
    """还没打勾、有日期、所属项目没提交的步骤，按日期排序。since 为空表示包括所有逾期的。"""
    query = (Task.query.join(Project)
             .filter(Project.user_id == g.user.id, Project.status != "submitted", Task.done.is_(False),
                     Task.due_date.isnot(None), Task.due_date <= until))
    if since is not None:
        query = query.filter(Task.due_date >= since)
    return query.order_by(Task.due_date.asc(), Task.position.asc(), Task.id.asc()).all()


def done_today_count():
    start = datetime.combine(date.today(), datetime.min.time())
    return (Task.query.join(Project)
            .filter(Project.user_id == g.user.id, Task.done.is_(True), Task.done_at >= start).count())


@bp.route("/")
@login_required
def index():
    projects = active_projects()
    counts = {s: sum(1 for p in projects if p.status == s) for s in ACTIVE_STATUSES}
    today = date.today()
    today_tasks = open_tasks(today)
    upcoming = open_tasks(today + timedelta(days=UPCOMING_DAYS), since=today + timedelta(days=1))
    return render_template("pages/overview.html", projects=projects, counts=counts,
                           today_count=len(today_tasks), upcoming_count=len(upcoming),
                           done_today=done_today_count())


@bp.route("/today")
@login_required
def today():
    today = date.today()
    tasks = open_tasks(today)
    overdue = [t for t in tasks if t.due_date < today]
    due_today = [t for t in tasks if t.due_date == today]
    return render_template("pages/today.html", overdue=overdue, due_today=due_today,
                           minutes=sum(t.minutes or 0 for t in tasks), done_today=done_today_count())


@bp.route("/upcoming")
@login_required
def upcoming():
    today = date.today()
    tasks = open_tasks(today + timedelta(days=UPCOMING_DAYS), since=today + timedelta(days=1))
    days = [today + timedelta(days=i) for i in range(1, UPCOMING_DAYS + 1)]
    by_day = {d: [t for t in tasks if t.due_date == d] for d in days}
    return render_template("pages/upcoming.html", days=days, by_day=by_day, total=len(tasks),
                           minutes=sum(t.minutes or 0 for t in tasks))
