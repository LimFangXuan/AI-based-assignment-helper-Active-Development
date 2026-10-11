"""Prompt Generator。

现在仍是旧流程：诊断 → 提问 → 摘要 → 确认 → 生成 prompt。
阶段 5 会改成以 Requirements Checklist 为输入、没有单独提问阶段的新流程（spec §7.2）。
"""
import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import PromptSession
from ...security import get_own_child, login_required
from ...services import prompt_builder
from ...services.ai_client import AIServiceError
from . import get_tool_project

bp = Blueprint("prompt", __name__, url_prefix="/projects/<int:project_id>/tools/prompt")


def load(project_id, session_id):
    project, tool = get_tool_project(project_id, "prompt")
    return project, tool, get_own_child(PromptSession, session_id, project)


def back(project, ps):
    return redirect(url_for("prompt.view", project_id=project.id, session_id=ps.id))


@bp.route("")
@login_required
def index(project_id):
    project, tool = get_tool_project(project_id, "prompt")
    return render_template("pages/prompt_index.html", project=project, tool=tool)


@bp.route("/new", methods=["POST"])
@login_required
def new(project_id):
    project, _ = get_tool_project(project_id, "prompt")
    if not project.description:
        flash("Add a description to the project first, so the AI knows what to ask.", "error")
        return redirect(url_for("prompt.index", project_id=project.id))

    try:
        diagnosis = prompt_builder.diagnose(project)                      # 阶段1：诊断
        questions = prompt_builder.generate_questions(project, diagnosis)  # 阶段2：提问
    except AIServiceError as e:
        flash(e.user_message, "error")  # 503 等失败：只提示，不崩溃，也不留下半成品
        return redirect(url_for("prompt.index", project_id=project.id))

    ps = PromptSession(project_id=project.id, content_fingerprint=project.fingerprint,
                       diagnosis_json=json.dumps(diagnosis, ensure_ascii=False),
                       questions_json=json.dumps(questions, ensure_ascii=False))
    db.session.add(ps)
    db.session.commit()
    return back(project, ps)


@bp.route("/<int:session_id>")
@login_required
def view(project_id, session_id):
    """根据这次记录走到哪一步，显示对应的页面：提问 → 确认（或被冲突拦截）→ 结果。"""
    project, tool, ps = load(project_id, session_id)
    if ps.final_prompt:
        template = "prompt_result"
    elif request.args.get("retry") or not ps.summary:  # retry：学生想重新回答这组问题
        template = "prompt_questions"
    else:
        template = "prompt_blocked" if ps.blocked else "prompt_confirm"
    return render_template(f"pages/{template}.html", project=project, tool=tool, ps=ps)


@bp.route("/<int:session_id>/answers", methods=["POST"])
@login_required
def answers(project_id, session_id):
    project, _, ps = load(project_id, session_id)
    if ps.final_prompt:  # 已经生成过的记录不再覆盖
        return back(project, ps)
    qa = prompt_builder.collect_answers(ps.questions, request.form)
    diagnosis = ps.diagnosis or prompt_builder.empty_diagnosis()
    try:
        summary = prompt_builder.generate_summary(project, diagnosis, qa)
    except AIServiceError as e:
        flash(e.user_message, "error")  # 回答不会丢：回到问题页，学生可以直接再点一次
        return back(project, ps)

    ps.answers_json = json.dumps(qa, ensure_ascii=False)
    ps.summary_json = json.dumps(summary, ensure_ascii=False)
    db.session.commit()
    return back(project, ps)


@bp.route("/<int:session_id>/revise", methods=["POST"])
@login_required
def revise(project_id, session_id):
    """学生看过摘要后提出修改意见：把意见加进问答记录，重新整理一次摘要。"""
    project, _, ps = load(project_id, session_id)
    if ps.final_prompt or not ps.summary:
        return back(project, ps)
    notes = request.form.get("notes", "").strip()
    if not notes:
        flash("Write what should be changed or added first.", "error")
        return back(project, ps)

    qa = prompt_builder.add_revision(ps.answers, notes)
    diagnosis = ps.diagnosis or prompt_builder.empty_diagnosis()
    try:
        summary = prompt_builder.generate_summary(project, diagnosis, qa)
    except AIServiceError as e:
        flash(e.user_message, "error")  # 失败时保留上一版摘要
        return back(project, ps)

    ps.answers_json = json.dumps(qa, ensure_ascii=False)
    ps.summary_json = json.dumps(summary, ensure_ascii=False)
    db.session.commit()
    flash("Summary updated with your notes. Please check it again.", "success")
    return back(project, ps)


@bp.route("/<int:session_id>/confirm", methods=["POST"])
@login_required
def confirm(project_id, session_id):
    """学生确认摘要后生成最终 prompt。这一步只是用模板拼接，不调用 AI。"""
    project, _, ps = load(project_id, session_id)
    if ps.final_prompt or not ps.summary or ps.blocked:  # 已生成 / 还没摘要 / 冲突未解决
        return back(project, ps)
    diagnosis = ps.diagnosis or prompt_builder.empty_diagnosis()
    ps.final_prompt = prompt_builder.build_final_prompt(project, ps.answers, ps.summary, diagnosis)
    db.session.commit()
    return back(project, ps)
