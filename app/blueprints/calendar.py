"""Calendar：按月显示截止日期。"""
import calendar as pycal
from datetime import date, datetime

from flask import Blueprint, g, render_template, request

from ..constants import CALENDAR_CELL_LIMIT
from ..models import Project
from ..security import login_required

bp = Blueprint("calendar", __name__)


def parse_month(raw):
    """?month=YYYY-MM；无效或没给就用当前月份。"""
    try:
        d = datetime.strptime(raw or "", "%Y-%m").date()
        if 1900 <= d.year <= 2999:
            return d
    except ValueError:
        pass
    return date.today().replace(day=1)


def shift_month(first, delta):
    month = first.month - 1 + delta
    return date(first.year + month // 12, month % 12 + 1, 1)


@bp.route("/calendar")
@login_required
def month():
    first = parse_month(request.args.get("month"))
    next_first = shift_month(first, 1)
    projects = (Project.query.filter(Project.user_id == g.user.id, Project.status != "submitted",
                                     Project.deadline >= datetime.combine(first, datetime.min.time()),
                                     Project.deadline < datetime.combine(next_first, datetime.min.time()))
                .order_by(Project.deadline.asc()).all())
    by_day = {}
    for p in projects:
        by_day.setdefault(p.deadline.date(), []).append(p)
    # 一周从周一开始；monthdatescalendar 会补齐前后月份的日期，凑成完整的几周
    weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    months = [date(first.year, m, 1) for m in range(1, 13)]
    return render_template("pages/calendar.html", first=first, weeks=weeks, by_day=by_day, months=months,
                           prev_month=shift_month(first, -1), next_month=next_first,
                           cell_limit=CALENDAR_CELL_LIMIT, total=len(projects))
