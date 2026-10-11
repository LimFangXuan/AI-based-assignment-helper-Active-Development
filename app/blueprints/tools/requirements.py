"""Requirements Checklist：一轮一轮提问，直到任务的每个方面都清楚（spec §7.1）。

一个项目可以做多次检查，最新的一次生效。页面根据最新一次的状态显示：
还没开始 → 介绍页；进行中 → 当前这一轮的问题；已结束 → 结果页。
"""
import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import RequirementsCheck
from ...security import get_own_child, login_required
from ...services import requirements_checker as rc
from ...services.ai_client import AIServiceError
from . import get_tool_project

bp = Blueprint("requirements", __name__, url_prefix="/projects/<int:project_id>/tools/requirements")


def latest_check(project):
    return project.requirements_checks[0] if project.requirements_checks else None


def finish(check, aspects, conflicts):
    """结束一次检查：还没清楚的方面变成假设。"""
    final = rc.finish_with_assumptions(aspects)
    check.status = "complete" if all(a["state"] != "assumed" for a in final) else "complete_with_assumptions"
    check.set_state(aspects=final, conflicts=conflicts, questions=[])


def page(project):
    return redirect(url_for("requirements.index", project_id=project.id))


@bp.route("")
@login_required
def index(project_id):
    project, tool = get_tool_project(project_id, "requirements")
    check = latest_check(project)
    stale = bool(check and check.content_fingerprint != project.fingerprint)
    return render_template("pages/requirements.html", project=project, tool=tool, check=check, stale=stale)


@bp.route("/start", methods=["POST"])
@login_required
def start(project_id):
    """预扫描（1 次 AI）：能从资料里判断的方面直接标好，只把真正的缺口留下来问。"""
    project, _ = get_tool_project(project_id, "requirements")
    try:
        result = rc.prescan(project)
    except AIServiceError as e:
        flash(e.user_message, "error")  # 失败不留下半成品
        return page(project)

    check = RequirementsCheck(project_id=project.id, content_fingerprint=project.fingerprint, round_number=1)
    questions = result["questions"] or rc.fallback_questions(result["aspects"], result["conflicts"])
    check.set_state(result["aspects"], result["conflicts"], questions)
    if rc.is_settled(result["aspects"], result["conflicts"]):
        finish(check, result["aspects"], result["conflicts"])
    db.session.add(check)
    db.session.commit()
    return page(project)


@bp.route("/<int:check_id>/answers", methods=["POST"])
@login_required
def answers(project_id, check_id):
    """提交这一轮的回答（1 次 AI）：更新各方面的状态，并给出下一轮问题。"""
    project, _ = get_tool_project(project_id, "requirements")
    check = get_own_child(RequirementsCheck, check_id, project)
    if check.finished or check is not latest_check(project):
        return page(project)

    history = check.history + [{"round": check.round_number,
                                "answers": rc.collect_answers(check.questions, request.form)}]
    ask_more = check.round_number < rc.MAX_ROUNDS
    try:
        result = rc.evaluate_round(project, check.aspects, check.conflicts, history, ask_more)
    except AIServiceError as e:
        flash(e.user_message, "error")  # 回答没保存：回到同一轮，学生可以直接再提交一次
        return page(project)

    check.history_json = json.dumps(history, ensure_ascii=False)
    if rc.is_settled(result["aspects"], result["conflicts"]) or not ask_more:
        finish(check, result["aspects"], result["conflicts"])  # 全部清楚，或到了内部上限
    else:
        check.round_number += 1
        questions = result["questions"] or rc.fallback_questions(result["aspects"], result["conflicts"])
        check.set_state(result["aspects"], result["conflicts"], questions)
    db.session.commit()
    return page(project)


@bp.route("/<int:check_id>/finish", methods=["POST"])
@login_required
def finish_now(project_id, check_id):
    """“Finish with what we have”：不调用 AI，剩下的缺口全部记为假设。"""
    project, _ = get_tool_project(project_id, "requirements")
    check = get_own_child(RequirementsCheck, check_id, project)
    if not check.finished:
        finish(check, check.aspects, check.conflicts)
        db.session.commit()
    return page(project)
