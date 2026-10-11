"""“下载我的数据”：把一个用户的全部数据整理成一份 JSON（数据可携带权）。

只导出这个用户自己的数据；不包含密码哈希，也不包含其他用户的任何信息。
"""
import json
from datetime import date, datetime

from .models import User


def _iso(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _loads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def build_export(user: User):
    projects = []
    for p in user.projects:
        projects.append({
            "name": p.name, "description": p.description, "guideline": p.guideline, "type": p.type,
            "work_mode": p.work_mode, "citation_style": p.citation_style, "status": p.status,
            "deadline": _iso(p.deadline), "created_at": _iso(p.created_at),
            "tasks": [{"title": t.title, "detail": t.detail, "due_date": _iso(t.due_date), "minutes": t.minutes,
                       "done": t.done, "done_at": _iso(t.done_at), "based_on_assumption": t.based_on_assumption}
                      for t in p.tasks],
            "requirements_checks": [{
                "status": c.status, "created_at": _iso(c.created_at), "aspects": c.aspects, "conflicts": c.conflicts,
                "answers": c.history} for c in p.requirements_checks],
            "prompts": [{"created_at": _iso(s.created_at), "framework": s.framework, "prompt": s.final_prompt}
                        for s in p.prompt_sessions if s.framework_json or s.final_prompt],
            "paper_searches": [{
                "created_at": _iso(s.created_at), "queries": s.queries,
                "papers": [{"title": x.title, "authors": x.author_list, "year": x.year, "venue": x.venue, "doi": x.doi,
                            "url": x.url, "reason": x.reason, "citation": x.citation} for x in s.papers]}
                for s in p.paper_searches],
            "report_drafts": [{
                "created_at": _iso(d.created_at), "outline": d.outline,
                "sections": [{"title": s.title, "status": s.status, "content": s.content} for s in d.sections]}
                for d in p.report_drafts],
        })
    return {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "account": {"username": user.username, "email": user.email, "email_verified": bool(user.email_verified),
                    "created_at": _iso(user.created_at), "google_connected": bool(user.google_sub),
                    "has_password": bool(user.has_password),
                    "notifications": {"timezone": user.timezone, "daily_summary_hour": user.digest_hour,
                                      "email_daily_summary": bool(user.notify_email_digest),
                                      "email_deadline_reminders": bool(user.notify_email_deadlines),
                                      "push_daily_summary": bool(user.notify_push_digest),
                                      "push_deadline_reminders": bool(user.notify_push_deadlines),
                                      "push_devices": len(user.push_subscriptions)}},
        "projects": projects,
    }


def export_json(user):
    return json.dumps(build_export(user), ensure_ascii=False, indent=2)
