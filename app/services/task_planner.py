"""任务拆解：把项目拆成每天可以完成的小步骤。

AI 只给“草稿”：学生在页面上修改、删减后才保存。日期一律由代码校验，不信任 AI。
"""
from datetime import date

from . import ai_client
from .ai_client import AIServiceError
from .prompt_builder import project_block, _text

MIN_PLAN_STEPS, MAX_PLAN_STEPS = 2, 12


def generate_plan(project, today):
    """把项目拆成可以逐个打勾的小步骤，每步有建议完成日期和预计用时。"""
    deadline = project.deadline.date()
    prompt = f"""[TASK:PLAN]
{project_block(project)}

今天是 {today.isoformat()}，截止日期是 {deadline.isoformat()}。

请把这个项目拆成 {MIN_PLAN_STEPS + 2} 到 {MAX_PLAN_STEPS - 2} 个可以直接动手的小步骤，帮学生按时完成：
1. 每一步以动词开头，具体到“坐下来就知道做什么”，例如“列出报告的三个小标题”，不要写“开始研究”这种空话。
2. 每一步用时 15 到 180 分钟；太大的步骤继续拆小。
3. due_date 必须在今天和截止日期之间，按先后顺序排列；最后一步留出检查和提交的时间，不要全部挤在最后一天。
4. 描述里信息不足时，按这类作业的常见做法拆解，不要编造老师的具体要求。

只返回 JSON，格式：
{{"steps": [{{"title": "...", "due_date": "YYYY-MM-DD", "minutes": 60}}]}}"""
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
        title = _text(item.get("title"), 200)
        if not title:
            continue
        try:
            minutes = int(item.get("minutes"))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None and not 5 <= minutes <= 600:
            minutes = None
        steps.append({"title": title, "due_date": _clamp_date(item.get("due_date"), today, deadline),
                      "minutes": minutes})
        if len(steps) == MAX_PLAN_STEPS:
            break
    if len(steps) < MIN_PLAN_STEPS:
        raise ValueError("步骤太少")
    return steps
