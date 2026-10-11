"""Task Planner：把 framework 拆成截止日期前每天可以完成的任务（spec §7.3）。

AI 只给“草稿”：学生在页面上修改、删减后才保存。日期一律由代码校验，不信任 AI。
时间明显不够时，代码和 AI 都会给出判断，取更严重的那个，并如实告诉学生。
"""
from datetime import date

from . import ai_client
from .ai_client import AIServiceError
from .common import check_input_size, project_block, text
from .requirements_checker import context_block

MIN_PLAN_STEPS, MAX_PLAN_STEPS = 2, 20
FEASIBILITY = ("ok", "tight", "too_short")
# 每天大概能投入多少分钟：超过 TIGHT 就算紧，超过 TOO_SHORT 就算时间不够（学生还有别的课）
TIGHT_MINUTES_PER_DAY, TOO_SHORT_MINUTES_PER_DAY = 180, 360


class DeadlinePassed(Exception):
    """截止日期已过：不调用 AI，直接告诉学生。"""


def _framework_block(framework):
    lines = [f"Goal: {framework.get('goal') or '(not stated)'}"]
    for i, p in enumerate(framework.get("phases") or [], 1):
        flag = " [relies on an assumption]" if p.get("based_on_assumption") else ""
        lines.append(f"Phase {i}: {p['name']}{flag}")
        lines += [f"  - {s}" for s in p.get("steps") or []]
    return "<framework>\n" + "\n".join(lines) + "\n</framework>"


def generate_plan(project, today, aspects, conflicts, framework):
    """1 次 AI：按天拆任务。返回 {"feasibility", "message", "steps"}。"""
    deadline = project.deadline.date()
    if deadline < today:
        raise DeadlinePassed()
    check_input_size(project)
    days = (deadline - today).days + 1
    prompt = f"""[TASK:PLAN]
{project_block(project)}

{context_block(aspects, conflicts)}

{_framework_block(framework)}

Today is {today.isoformat()} and the deadline is {deadline.isoformat()} ({days} day(s) including today).

Turn the framework into a day-by-day task list that ends before the deadline:
1. Each task starts with a verb and is concrete enough to start right away (not "start researching").
2. Each task takes 15 to 180 minutes; split bigger work.
3. due_date is between today and the deadline, in order. Leave time at the end to check and submit.
   Spread the work out; don't put everything on the last days.
4. detail: one sentence on what "done" looks like for this task.
5. based_on_assumption: true if the task depends on an [ASSUMED] requirement or a phase that relies on one.
6. feasibility: "ok", "tight" (possible with steady daily work) or "too_short" (the work clearly does not fit).
   message: one honest sentence to the student about the time available.

Return JSON only:
{{"feasibility": "ok", "message": "...",
  "steps": [{{"title": "...", "detail": "...", "due_date": "YYYY-MM-DD", "minutes": 60, "based_on_assumption": false}}]}}
Write everything in English."""
    data = ai_client.ask_gemini_json(prompt)
    try:
        return parse_plan(data, today, deadline)
    except ValueError as e:
        raise AIServiceError("The AI task plan was in the wrong format. Please try again.") from e


def _clamp_date(raw, today, deadline):
    """解析 AI 给的日期并限制在 [今天, 截止日] 之内；截止日已过或日期无效时返回 None。"""
    if deadline < today:
        return None
    try:
        d = date.fromisoformat(str(raw or "")[:10])
    except ValueError:
        return None
    return min(max(d, today), deadline)


def parse_plan(data, today, deadline):
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ValueError("缺少 steps 列表")
    steps = []
    for item in data["steps"]:
        if not isinstance(item, dict):
            continue
        title = text(item.get("title"), 200)
        if not title:
            continue
        try:
            minutes = int(item.get("minutes"))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None and not 5 <= minutes <= 600:
            minutes = None
        steps.append({"title": title, "detail": text(item.get("detail"), 400),
                      "due_date": _clamp_date(item.get("due_date"), today, deadline), "minutes": minutes,
                      "based_on_assumption": bool(item.get("based_on_assumption"))})
        if len(steps) == MAX_PLAN_STEPS:
            break
    if len(steps) < MIN_PLAN_STEPS:
        raise ValueError("步骤太少")
    feasibility = data.get("feasibility") if data.get("feasibility") in FEASIBILITY else "ok"
    message = text(data.get("message"), 300)
    # 代码自己也算一遍：每天平均要投入多少分钟
    days = max(1, (deadline - today).days + 1) if deadline >= today else 1
    per_day = sum(s["minutes"] or 0 for s in steps) / days
    code_level = "too_short" if per_day > TOO_SHORT_MINUTES_PER_DAY else ("tight" if per_day > TIGHT_MINUTES_PER_DAY else "ok")
    if FEASIBILITY.index(code_level) > FEASIBILITY.index(feasibility):
        feasibility = code_level
        message = (f"This plan needs about {round(per_day / 60, 1)} hours a day until the deadline. "
                   + ("That is very hard to fit: cut the scope or ask about an extension." if code_level == "too_short"
                      else "It fits only with steady daily work."))
    return {"feasibility": feasibility, "message": message, "steps": steps}
