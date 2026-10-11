"""Task Planner：项目的步骤列表（可手动增删改、打勾、拖拽排序）+ AI 拆解草稿（spec §7.3）。

AI 拆解的输入是已确认的 framework + 截止日期 + 今天的日期。草稿不存库，学生改完才保存；
保存时可以选择替换之前 AI 规划、还没完成的任务，或者追加在后面。手动添加的任务和已完成的任务不会被替换。
"""
from datetime import date, datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from ...constants import STATUS_LABELS, TASK_MINUTES_RANGE, TASK_TITLE_MAX_CHARS
from ...extensions import db
from ...models import RequirementsCheck, Task
from ...security import get_own_child, login_required, safe_next
from ...services import task_planner
from ...services.ai_client import AIServiceError
from . import confirmed_framework, get_tool_project

bp = Blueprint("planner", __name__, url_prefix="/projects/<int:project_id>/tools/planner")


# ---------------- 工具函数 ----------------
def parse_date(raw):
    """返回 (日期或 None, 是否有效)。空字符串表示“没有日期”，是有效的。"""
    raw = (raw or "").strip()
    if not raw:
        return None, True
    try:
        return date.fromisoformat(raw), True
    except ValueError:
        return None, False


def parse_minutes(raw):
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    low, high = TASK_MINUTES_RANGE
    return minutes if low <= minutes <= high else None


def read_task_form(form):
    """返回 (字段, 错误信息)。"""
    title = form.get("title", "").strip()
    if not 1 <= len(title) <= TASK_TITLE_MAX_CHARS:
        return None, f"Task name must be 1 to {TASK_TITLE_MAX_CHARS} characters."
    due, ok = parse_date(form.get("due_date"))
    if not ok:
        return None, "That date is not valid."
    return {"title": title, "due_date": due, "minutes": parse_minutes(form.get("minutes"))}, None


def wants_json():
    """页面上的 JS 用 fetch 提交时会带这个请求头；没有 JS 时表单照常提交、整页跳转。"""
    return request.headers.get("X-Requested-With") == "fetch"


def sync_status(project):
    """根据打勾情况自动更新项目状态：全部完成 → Ready to submit；做了一部分 → In progress。已提交的不动。"""
    if project.status == "submitted" or not project.tasks:
        return
    done, total, _ = project.progress
    if done == total:
        project.status = "done"
    elif done:
        project.status = "in_progress"
    elif project.status == "done":  # 加了新步骤或取消打勾，不再是“全部完成”
        project.status = "in_progress"


def default_page(project):
    return url_for("planner.index", project_id=project.id)


def task_response(project, message=None, task=None):
    """fetch 请求返回 JSON（页面局部刷新）；普通表单提交则跳转回原页面。"""
    if wants_json():
        done, total, pct = project.progress
        data = {"ok": True, "message": message, "status": project.status,
                "status_label": STATUS_LABELS[project.status],
                "progress": {"done": done, "total": total, "pct": pct}}
        if task is not None:
            data["html"] = render_template("components/task_row.html", project=project, task=task)
        return jsonify(data)
    if message:
        flash(message, "success")
    return redirect(safe_next(default_page(project)))


def task_error(project, message):
    if wants_json():
        return jsonify({"ok": False, "error": message}), 400
    flash(message, "error")
    return redirect(safe_next(default_page(project)))


def next_position(project):
    return max((t.position for t in project.tasks), default=-1) + 1


# ---------------- 页面 ----------------
@bp.route("")
@login_required
def index(project_id):
    project, tool = get_tool_project(project_id, "planner")
    planned = [t for t in project.tasks if t.content_fingerprint and not t.done]
    stale = any(t.content_fingerprint != project.fingerprint for t in planned)
    return render_template("pages/planner.html", project=project, tool=tool, stale=stale,
                           framework_session=confirmed_framework(project))


@bp.route("/tasks", methods=["POST"])
@login_required
def task_add(project_id):
    project, _ = get_tool_project(project_id, "planner")
    fields, error = read_task_form(request.form)
    if error:
        return task_error(project, error)
    task = Task(project_id=project.id, position=next_position(project), **fields)
    db.session.add(task)
    db.session.flush()
    db.session.refresh(project)  # 让 project.tasks 包含刚加的步骤
    sync_status(project)
    db.session.commit()
    return task_response(project, task=task)


@bp.route("/tasks/<int:task_id>/toggle", methods=["POST"])
@login_required
def task_toggle(project_id, task_id):
    project, _ = get_tool_project(project_id, "planner")
    task = get_own_child(Task, task_id, project)
    task.done = not task.done
    task.done_at = datetime.now() if task.done else None
    sync_status(project)
    db.session.commit()
    done, total, _ = project.progress
    message = "All tasks done. Give it a final check, then submit." if task.done and done == total else None
    return task_response(project, message)


@bp.route("/tasks/<int:task_id>/update", methods=["POST"])
@login_required
def task_update(project_id, task_id):
    project, _ = get_tool_project(project_id, "planner")
    task = get_own_child(Task, task_id, project)
    fields, error = read_task_form(request.form)
    if error:
        return task_error(project, error)
    task.title, task.due_date, task.minutes = fields["title"], fields["due_date"], fields["minutes"]
    db.session.commit()
    return task_response(project, task=task)


@bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
def task_delete(project_id, task_id):
    project, _ = get_tool_project(project_id, "planner")
    task = get_own_child(Task, task_id, project)
    db.session.delete(task)
    db.session.flush()
    db.session.refresh(project)
    sync_status(project)
    db.session.commit()
    return task_response(project)


@bp.route("/tasks/reorder", methods=["POST"])
@login_required
def task_reorder(project_id):
    """拖拽排序：ids 是按新顺序排列、逗号分隔的步骤 ID。不属于这个项目的 ID 一律忽略。"""
    project, _ = get_tool_project(project_id, "planner")
    by_id = {t.id: t for t in project.tasks}
    order = []
    for raw in request.form.get("ids", "").split(","):
        raw = raw.strip()
        if raw.isdigit() and int(raw) in by_id and int(raw) not in order:
            order.append(int(raw))
    order += [t.id for t in project.tasks if t.id not in order]  # 漏掉的步骤保持在后面
    for position, task_id in enumerate(order):
        by_id[task_id].position = position
    db.session.commit()
    return task_response(project)


def planning_inputs(project):
    """AI 拆解需要的输入：已确认的 framework，以及它所依据的那次需求。没有就返回 None。"""
    ps = confirmed_framework(project)
    if ps is None:
        return None
    check = db.session.get(RequirementsCheck, ps.requirements_check_id) if ps.requirements_check_id else None
    return ps, (check.aspects if check else []), (check.conflicts if check else [])


@bp.route("/draft", methods=["POST"])
@login_required
def draft(project_id):
    """AI 按天拆出任务草稿（1 次 AI）。草稿不存库：学生改完点“保存”才写入。"""
    project, tool = get_tool_project(project_id, "planner")
    inputs = planning_inputs(project)
    if inputs is None:
        flash("Confirm a framework in the Prompt Generator first. The plan is built from it.", "error")
        return redirect(default_page(project))
    ps, aspects, conflicts = inputs
    try:
        plan = task_planner.generate_plan(project, date.today(), aspects, conflicts, ps.framework)
    except task_planner.DeadlinePassed:
        flash("The deadline has already passed, so there is no time left to plan. "
              "Update the deadline if you have an extension.", "error")
        return redirect(default_page(project))
    except AIServiceError as e:
        flash(e.user_message, "error")
        return redirect(default_page(project))
    has_planned = any(t.content_fingerprint and not t.done for t in project.tasks)
    return render_template("pages/plan_draft.html", project=project, tool=tool, plan=plan, has_planned=has_planned)


@bp.route("/save", methods=["POST"])
@login_required
def save(project_id):
    project, _ = get_tool_project(project_id, "planner")
    rows = zip(request.form.getlist("title"), request.form.getlist("due_date"), request.form.getlist("minutes"),
               request.form.getlist("detail"), request.form.getlist("assumed"))
    new_tasks = []
    for title, due_raw, minutes_raw, detail, assumed in list(rows)[:task_planner.MAX_PLAN_STEPS * 2]:
        title = title.strip()[:TASK_TITLE_MAX_CHARS]
        if not title:
            continue  # 学生清空了内容的行直接跳过
        due, ok = parse_date(due_raw)
        new_tasks.append(Task(project_id=project.id, title=title, due_date=due if ok else None,
                              minutes=parse_minutes(minutes_raw), detail=detail.strip()[:400] or None,
                              based_on_assumption=assumed == "1", content_fingerprint=project.fingerprint))
    if not new_tasks:
        flash("There are no tasks to save.", "error")
        return redirect(default_page(project))
    replaced = 0
    if request.form.get("mode") == "replace":
        for t in [t for t in project.tasks if t.content_fingerprint and not t.done]:
            db.session.delete(t)  # 只替换之前 AI 规划、还没完成的任务
            replaced += 1
        db.session.flush()
        db.session.refresh(project)
    position = next_position(project)
    for i, task in enumerate(new_tasks):
        task.position = position + i
        db.session.add(task)
    db.session.flush()
    db.session.refresh(project)
    sync_status(project)
    db.session.commit()
    message = f"Added {len(new_tasks)} task{'s' if len(new_tasks) != 1 else ''}."
    if replaced:
        message += f" Replaced {replaced} earlier planned task{'s' if replaced != 1 else ''}."
    flash(message, "success")
    return redirect(default_page(project))
