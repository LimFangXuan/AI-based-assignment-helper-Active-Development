"""Prompt Generator：确认过的需求 → 项目 framework → 可以复制的 prompt（spec §7.2）。

- 没有单独的提问阶段，输入是最新一次已结束的 Requirements Checklist。
- 需求里还有没解决的冲突时，不生成。
- framework 需要学生拍板的地方（Needs your decision）在同一页选，选完重新生成。
- 写修改意见 → 重新生成；确认之后才用代码拼出最终 prompt（这一步不调用 AI）。
"""
import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import PromptSession, RequirementsCheck
from ...security import get_own_child, login_required
from ...services import prompt_generator as pg
from ...services.ai_client import AIServiceError
from . import finished_requirements, framework_sessions, get_tool_project

bp = Blueprint("prompt", __name__, url_prefix="/projects/<int:project_id>/tools/prompt")


def page(project):
    return redirect(url_for("prompt.index", project_id=project.id))


def ready_requirements(project):
    """返回可用的需求；没有或有未解决的冲突时给出提示并返回 None。"""
    check = finished_requirements(project)
    if check is None:
        flash("Finish the Requirements Checklist first. The framework is built from it.", "error")
    elif check.open_conflicts:
        flash("Resolve the open conflict in the Requirements Checklist first.", "error")
        check = None
    return check


def regenerate(project, check, notes, decisions):
    """生成一份新的 framework 记录（1 次 AI）。失败时只提示，不留下半成品。"""
    try:
        framework = pg.generate_framework(project, check.aspects, check.conflicts, notes, decisions)
    except AIServiceError as e:
        flash(e.user_message, "error")
        return None
    ps = PromptSession(project_id=project.id, requirements_check_id=check.id, content_fingerprint=project.fingerprint,
                       framework_json=json.dumps(framework, ensure_ascii=False),
                       answers_json=json.dumps({"notes": notes, "decisions": decisions}, ensure_ascii=False))
    db.session.add(ps)
    db.session.commit()
    return ps


@bp.route("")
@login_required
def index(project_id):
    project, tool = get_tool_project(project_id, "prompt")
    check = finished_requirements(project)
    sessions = framework_sessions(project)
    current = sessions[0] if sessions else None
    stale = bool(current and (current.content_fingerprint != project.fingerprint
                              or (check and current.requirements_check_id != check.id)))
    return render_template("pages/prompt.html", project=project, tool=tool, check=check, ps=current,
                           history=sessions[1:6], stale=stale)


@bp.route("/generate", methods=["POST"])
@login_required
def generate(project_id):
    project, _ = get_tool_project(project_id, "prompt")
    check = ready_requirements(project)
    if check:
        regenerate(project, check, [], {})
    return page(project)


@bp.route("/<int:session_id>/revise", methods=["POST"])
@login_required
def revise(project_id, session_id):
    """学生写修改意见 → 带着之前的意见和决定重新生成。"""
    project, _ = get_tool_project(project_id, "prompt")
    ps = get_own_child(PromptSession, session_id, project)
    notes = request.form.get("notes", "").strip()[:1000]
    if not notes:
        flash("Write what should change first.", "error")
        return page(project)
    check = ready_requirements(project)
    if check and not ps.final_prompt:
        regenerate(project, check, ps.inputs.get("notes", []) + [notes], ps.inputs.get("decisions", {}))
    return page(project)


@bp.route("/<int:session_id>/decide", methods=["POST"])
@login_required
def decide(project_id, session_id):
    """“Needs your decision”：学生选好后，按选择重新生成 framework。"""
    project, _ = get_tool_project(project_id, "prompt")
    ps = get_own_child(PromptSession, session_id, project)
    framework = ps.framework or {}
    decisions = dict(ps.inputs.get("decisions", {}))
    for d in framework.get("decisions_needed", []):
        choice = request.form.get(d["id"], "")
        if choice in {o["label"] for o in d["options"]}:
            decisions[d["question"]] = {"question": d["question"], "choice": choice}
    if len(decisions) == len(ps.inputs.get("decisions", {})):
        flash("Choose an option first.", "error")
        return page(project)
    check = ready_requirements(project)
    if check and not ps.final_prompt:
        regenerate(project, check, ps.inputs.get("notes", []), decisions)
    return page(project)


@bp.route("/<int:session_id>/confirm", methods=["POST"])
@login_required
def confirm(project_id, session_id):
    """确认 framework 后用代码拼出最终 prompt，不调用 AI。还有待决定的事项或冲突时不确认。"""
    project, _ = get_tool_project(project_id, "prompt")
    ps = get_own_child(PromptSession, session_id, project)
    # 用生成这份 framework 时所依据的那次需求，而不是之后新做的检查
    check = db.session.get(RequirementsCheck, ps.requirements_check_id) if ps.requirements_check_id else None
    if check is None or check.open_conflicts:
        check = ready_requirements(project)
    framework = ps.framework
    if check is None or framework is None or ps.final_prompt:
        return page(project)
    if framework["decisions_needed"]:
        flash("Make the decisions marked “Needs your decision” first.", "error")
        return page(project)
    ps.final_prompt = pg.build_prompt(project, check.aspects, check.conflicts, framework, ps.inputs.get("decisions", {}))
    db.session.commit()
    flash("Framework confirmed. Your prompt is ready.", "success")
    return page(project)
