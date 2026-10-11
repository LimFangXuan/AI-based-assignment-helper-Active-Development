"""模板里用的过滤器和全局变量（日期显示、倒计时、侧栏数据）。"""
from datetime import date, datetime

from flask import g

from .constants import (CITATION_STYLES, DUE_SOON_DAYS, SIDEBAR_PROJECT_LIMIT, STATUS_LABELS, TYPE_GROUPS,
                        TYPE_LABELS, WORK_MODES)
from .models import Project
from .security import get_csrf_token


def relday(d):
    """把日期显示成 “Today / Tomorrow / Wed / Oct 14” 这种更好读的形式。"""
    if d is None:
        return "No date"
    diff = (d - date.today()).days
    if diff == 0:
        return "Today"
    if diff == 1:
        return "Tomorrow"
    if diff == -1:
        return "Yesterday"
    if 1 < diff < 7:
        return d.strftime("%a")
    return f"{d.strftime('%b')} {d.day}"


def countdown(project):
    days = project.days_left
    if days < 0:
        return f"Overdue by {-days} day{'s' if days != -1 else ''}"
    if days == 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    return f"{days} days left"


def minutes_label(minutes):
    if not minutes:
        return "0 min"
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def sidebar_context():
    """侧栏数据：只在登录后计算，只查一次数据库（spec §5.1）。"""
    user = g.get("user")
    if user is None:
        return {}
    active = (Project.query.filter(Project.user_id == user.id, Project.status != "submitted")
              .order_by(Project.deadline.asc()).all())
    # 徽章：还没开始或进行中，并且已逾期或 3 天内到期。“Ready to submit” 不算
    urgent = sum(1 for p in active if p.status in ("not_started", "in_progress") and p.days_left <= DUE_SOON_DAYS)
    return {"sidebar_projects": active[:SIDEBAR_PROJECT_LIMIT], "sidebar_more": max(0, len(active) - SIDEBAR_PROJECT_LIMIT),
            "overview_badge": urgent}


def register(app):
    app.jinja_env.globals["csrf_token"] = get_csrf_token
    app.add_template_filter(relday)
    app.add_template_filter(countdown)
    app.add_template_filter(minutes_label)

    @app.context_processor
    def inject_globals():
        return {
            "now": datetime.now(), "today": date.today(),
            "STATUS_LABELS": STATUS_LABELS, "TYPE_LABELS": TYPE_LABELS, "TYPE_GROUPS": TYPE_GROUPS,
            "WORK_MODES": WORK_MODES, "CITATION_STYLES": CITATION_STYLES,
            **sidebar_context(),
        }
