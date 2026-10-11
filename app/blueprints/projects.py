"""项目：创建、编辑、项目页、状态、提交、删除、已提交列表。"""
from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..constants import (CITATION_STYLES, DEFAULT_TYPE, DEFAULT_WORK_MODE, DESCRIPTION_MAX_CHARS,
                         EDITABLE_STATUSES, GUIDELINE_MAX_CHARS, NAME_MAX_CHARS, STATUS_LABELS, TYPE_LABELS,
                         WORK_MODES)
from ..extensions import db
from ..models import Project
from ..security import get_own_project, login_required
from ..tools_registry import tools_for

bp = Blueprint("projects", __name__)

FORM_FIELDS = ("name", "deadline", "description", "guideline", "type", "work_mode", "citation_style")


def parse_deadline(raw):
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def read_project_form(form):
    """返回 (字段, 错误信息)。校验失败时页面会带着用户已填的内容重新显示。"""
    values = {k: form.get(k, "").strip() for k in FORM_FIELDS}
    deadline = parse_deadline(values["deadline"])
    if not 1 <= len(values["name"]) <= NAME_MAX_CHARS:
        return values, f"Project name must be 1 to {NAME_MAX_CHARS} characters."
    if deadline is None:
        return values, "Choose a valid deadline date and time."
    if not values["description"]:
        return values, "Describe the task so the tools know what you are working on."
    if len(values["description"]) > DESCRIPTION_MAX_CHARS:
        return values, f"Description can be at most {DESCRIPTION_MAX_CHARS:,} characters."
    if len(values["guideline"]) > GUIDELINE_MAX_CHARS:
        return values, f"Guideline can be at most {GUIDELINE_MAX_CHARS:,} characters."
    if values["type"] not in TYPE_LABELS:
        return values, "Choose a project type."
    if values["work_mode"] not in WORK_MODES:
        return values, "Choose individual or group."
    if values["citation_style"] and values["citation_style"] not in CITATION_STYLES:
        return values, "Choose a citation style from the list."
    fields = dict(values, deadline=deadline, citation_style=values["citation_style"] or None)
    return fields, None


def render_form(editing=None, error=None, values=None):
    return render_template("pages/project_form.html", editing=editing, error=error, values=values or {},
                           description_max=DESCRIPTION_MAX_CHARS, guideline_max=GUIDELINE_MAX_CHARS,
                           name_max=NAME_MAX_CHARS)


@bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        fields, error = read_project_form(request.form)
        if error:
            return render_form(error=error, values=fields)
        project = Project(user_id=g.user.id, **fields)
        db.session.add(project)
        db.session.commit()
        flash("Project created.", "success")
        return redirect(url_for("projects.detail", project_id=project.id))
    return render_form(values={"type": DEFAULT_TYPE, "work_mode": DEFAULT_WORK_MODE})


@bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit(project_id):
    """修改项目资料：例如补充老师的书面许可，或改变方向后重新生成。"""
    project = get_own_project(project_id)
    if request.method == "POST":
        fields, error = read_project_form(request.form)
        if error:
            return render_form(editing=project, error=error, values=fields)
        for key, value in fields.items():
            setattr(project, key, value)
        db.session.commit()
        flash("Project updated.", "success")
        return redirect(url_for("projects.detail", project_id=project.id))
    values = {k: getattr(project, k) or "" for k in FORM_FIELDS}
    values["deadline"] = project.deadline.strftime("%Y-%m-%dT%H:%M")
    return render_form(editing=project, values=values)


def tool_cards(project):
    """每张工具卡片的状态和提示。前面的工具没完成时给后面的卡片一个温和提示，但不锁住（spec §5.5）。"""
    from .tools import confirmed_framework, finished_requirements, framework_sessions  # 避免循环导入

    check = project.requirements_checks[0] if project.requirements_checks else None
    requirements_done = finished_requirements(project) is not None
    framework = confirmed_framework(project)
    done, total, _ = project.progress
    papers = sum(len(s.papers) for s in project.paper_searches)
    draft = project.report_drafts[0] if project.report_drafts else None
    approved = sum(1 for s in draft.sections if s.status == "approved") if draft else 0

    states = {
        "requirements": ("todo", "Not started") if check is None else
        ("active", "In progress") if not check.finished else
        ("done", "Confirmed" if check.status == "complete" else "Finished with assumptions"),
        "prompt": ("done", "Prompt ready") if framework else
        ("active", "Framework waiting for your review") if framework_sessions(project) else ("todo", "Not started"),
        "planner": ("done" if total and done == total else ("todo" if not total else "active"),
                    f"{done} / {total} tasks done" if total else "No tasks yet"),
        "papers": ("done", f"{papers} paper{'s' if papers != 1 else ''} found") if papers else ("todo", "No papers yet"),
        "report": ("todo", "Not started") if draft is None else
        ("done" if approved == len(draft.sections) else "active", f"{approved} / {len(draft.sections)} sections approved"),
    }
    hints = {
        "prompt": None if requirements_done else "Needs the Requirements Checklist first.",
        "planner": None if framework else "AI planning needs a confirmed framework from the Prompt Generator.",
        "papers": None if requirements_done else "Needs the Requirements Checklist first.",
        "report": "Works best after the Paper Finder, so paragraphs can cite real papers."
        if requirements_done and not papers else (None if requirements_done else "Needs the Requirements Checklist first."),
    }
    cards = []
    for tool in tools_for(project):
        state, meta = states.get(tool.slug, ("soon", "Coming soon"))
        cards.append({"tool": tool, "state": state if tool.implemented else "soon",
                      "meta": meta if tool.implemented else "Coming soon",
                      "hint": hints.get(tool.slug) if tool.implemented else None})
    return cards


@bp.route("/projects/<int:project_id>")
@login_required
def detail(project_id):
    project = get_own_project(project_id)
    return render_template("pages/project.html", project=project, cards=tool_cards(project),
                           editable=EDITABLE_STATUSES)


@bp.route("/projects/<int:project_id>/status", methods=["POST"])
@login_required
def update_status(project_id):
    project = get_own_project(project_id)
    status = request.form.get("status", "")
    if status not in EDITABLE_STATUSES:  # 不允许通过这个入口直接改成 submitted
        abort(400)
    project.status = status
    db.session.commit()
    flash(f"Status changed to “{STATUS_LABELS[status]}”.", "success")
    return redirect(url_for("projects.detail", project_id=project.id))


@bp.route("/projects/<int:project_id>/submit", methods=["POST"])
@login_required
def submit(project_id):
    """软删除：只把状态改成 submitted，数据保留，Overview、日历和侧栏不再显示。"""
    project = get_own_project(project_id)
    project.status = "submitted"
    db.session.commit()
    flash(f"“{project.name}” marked as submitted.", "success")
    return redirect(url_for("overview.index"))


@bp.route("/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def delete(project_id):
    """真正删除（连同步骤、prompt 记录、论文）。页面上会先弹窗确认。"""
    project = get_own_project(project_id)
    name = project.name
    db.session.delete(project)
    db.session.commit()
    flash(f"“{name}” deleted.", "success")
    return redirect(url_for("overview.index"))


@bp.route("/submitted")
@login_required
def submitted():
    projects = (Project.query.filter(Project.user_id == g.user.id, Project.status == "submitted")
                .order_by(Project.deadline.desc()).all())
    return render_template("pages/submitted.html", projects=projects)
