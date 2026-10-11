"""Requirements Checklist：问到任务的每个方面都清楚为止（spec §7.1）。

流程：
  1. prescan        → 1 次 AI：读描述 + guideline + 类型，把能判断的方面标成 clear / na，
                       只有真正的缺口留 unclear，并给出第 1 轮问题
  2. evaluate_round → 每轮 1 次 AI：根据学生的回答更新各方面，再给出下一轮问题（每轮最多 3 题）
  3. 最多 5 轮（内部上限，不显示给学生）；第 5 轮的回答评估完就不再出题。总 AI 调用 ≤ 6 次
  4. 学生随时可以 "Finish with what we have"：剩下的 unclear 变成 assumed（假设），不调用 AI

AI 的输出一律先过代码校验：方面的 key 和状态只能是已知值，冲突的证据必须真的出现在资料里，
问题只能问还没清楚的方面或还没解决的冲突。
"""
from . import ai_client
from ..constants import TYPE_KNOWLEDGE
from .ai_client import AIServiceError
from .common import check_input_size, load_skill_json, project_block, quote_is_in, read_skill, str_list, text
from .privacy import redact

QUESTIONS_PER_ROUND = 3
MAX_ROUNDS = 5
STATES = ("clear", "unclear", "na")
SOURCES = ("brief", "student", "recommended")
UNKNOWN_OPTION = "I don't know"
UNANSWERED = "(no answer)"
DEFAULT_ASSUMPTION = "Not specified; the tools will follow common practice for this type of assignment."


# ======================= 方面列表 =======================
def aspect_definitions(work_mode):
    """从 skills/requirements/aspects.json 读取；个人项目不需要 “Roles”。"""
    return [a for a in load_skill_json("requirements/aspects.json")
            if not (a.get("group_only") and work_mode != "group")]


def initial_aspects(work_mode):
    return [{"key": a["key"], "name": a["name"], "hint": a["hint"], "state": "unclear",
             "summary": "", "source": "", "assumption": DEFAULT_ASSUMPTION}
            for a in aspect_definitions(work_mode)]


def question_bank(project_type):
    """按学生选的类型加载问题库：通用的作业问题 + 该类型专属的问题；没有专属的类型用 general。"""
    bank = TYPE_KNOWLEDGE.get(project_type)
    files = ["question_banks/common.md", f"question_banks/{bank}.md"] if bank else ["question_banks/general.md"]
    return "\n\n".join(x for x in (read_skill(f"prompt_generator/{f}") for f in files) if x)


# ======================= 给 AI 的说明 =======================
def _aspects_block(aspects):
    lines = []
    for a in aspects:
        line = f"- {a['key']} ({a['name']}): {a['hint']} | current state: {a['state']}"
        if a.get("summary"):
            line += f" | known: {a['summary']}"
        lines.append(line)
    return "\n".join(lines)


def _conflicts_block(conflicts):
    if not conflicts:
        return "(none)"
    return "\n".join(f"- {c['id']} [{c['status']}]: {c['issue']} (evidence: \"{c['evidence']}\")"
                     + (f" resolution: {c['resolution']}" if c.get("resolution") else "") for c in conflicts)


def _history_block(history):
    if not history:
        return "(no rounds yet)"
    parts = []
    for r in history:
        for qa in r["answers"]:
            parts.append(f"- Q ({qa['aspect']}): {qa['question']}\n  A: {redact(qa['answer'])}")
    return "\n".join(parts)


OUTPUT_FORMAT = """Return JSON only, in this shape:
{"aspects": [{"key": "...", "state": "clear|unclear|na", "summary": "...", "source": "brief|student|recommended", "assumption": "..."}],
 "conflicts": [{"id": "C1", "issue": "...", "evidence": "exact words copied from the student's material", "options": ["...", "..."], "status": "open|resolved", "resolution": "..."}],
 "questions": [{"ref": "aspect key or conflict id", "question": "...", "why": "...", "options": ["...", "..."]}]}

Field rules:
- aspects: one entry for every aspect listed above, using exactly those keys.
  - clear: the material or the student's answers settle it. summary = what is known, in one or two sentences.
  - na: it genuinely does not apply to this task. summary = why, in a few words.
  - unclear: still a real gap that would change the work. summary = what is known so far (may be empty).
    assumption = what the tools will assume if it is never answered (concrete, one sentence).
  - source: brief = from the description or guideline; student = from the student's answers;
    recommended = the student answered "I don't know" and you recommend the usual choice (summary must say it is a recommendation).
- conflicts: real contradictions only (the plan breaks a guideline rule, scope vs time or group size, facts that contradict each other).
  evidence MUST be copied word for word from the student's material; never invent guideline rules.
  Keep the same id for a conflict across rounds. Mark it resolved only when an answer settles it, and say how in resolution.
- questions: at most {limit}. Ask about open conflicts first, then the unclear aspects that change the work the most.
  Each question: 2 to 4 short concrete options, why = how the answer changes the work.
  Do not ask about anything that is already clear. Do not include an "I don't know" option (the app adds it).
- Write everything in English."""


def _base_prompt(task_marker, project, aspects, conflicts):
    return f"""[{task_marker}]
{read_skill("prompt_generator/rules.md")}

{project_block(project)}

Aspects of the task to check:
{_aspects_block(aspects)}

Known conflicts:
{_conflicts_block(conflicts)}

Question bank for this type of assignment (material to draw on, not a script):
{question_bank(getattr(project, "type", None))}
"""


# ======================= 两种 AI 调用 =======================
def prescan(project, work_mode=None):
    """第 1 次调用：先判断资料里已经能确定的方面，再出第 1 轮问题。"""
    check_input_size(project)
    aspects = initial_aspects(work_mode or project.work_mode)
    prompt = (_base_prompt("TASK:REQ_PRESCAN", project, aspects, [])
              + "\nJudge every aspect from the material alone. Mark aspects you can already judge as clear or na; "
                "leave only real gaps as unclear. Then write the first round of questions.\n\n"
              + OUTPUT_FORMAT.replace("{limit}", str(QUESTIONS_PER_ROUND)))
    data = ai_client.ask_gemini_json(prompt)
    try:
        return parse_result(data, aspects, [], [project.description, getattr(project, "guideline", "")],
                            default_source="brief", ask=True)
    except ValueError as e:
        raise AIServiceError("The AI requirements check was in the wrong format. Please try again.") from e


def evaluate_round(project, aspects, conflicts, history, ask_more):
    """每轮 1 次调用：根据目前为止的全部回答更新状态；ask_more=False 时（最后一轮）不再出题。"""
    check_input_size(project)
    instruction = ("Update every aspect and conflict using the student's answers so far. "
                   + ("Then write the next round of questions about what is still unclear."
                      if ask_more else "This was the last round: return an empty questions list."))
    prompt = (_base_prompt("TASK:REQ_ROUND", project, aspects, conflicts)
              + f"\nThe student's answers so far:\n{_history_block(history)}\n\n{instruction}\n\n"
              + OUTPUT_FORMAT.replace("{limit}", str(QUESTIONS_PER_ROUND if ask_more else 0)))
    data = ai_client.ask_gemini_json(prompt)
    answers_text = "\n".join(qa["answer"] for r in history for qa in r["answers"])
    try:
        return parse_result(data, aspects, conflicts,
                            [project.description, getattr(project, "guideline", ""), answers_text],
                            default_source="student", ask=ask_more)
    except ValueError as e:
        raise AIServiceError("The AI requirements check was in the wrong format. Please try again.") from e


# ======================= 校验 AI 的输出 =======================
def parse_result(data, previous_aspects, previous_conflicts, evidence_sources, default_source, ask):
    """返回 {"aspects", "conflicts", "questions"}。AI 漏掉的方面保留原状态，冲突只能用资料里真实存在的证据。"""
    if not isinstance(data, dict) or not isinstance(data.get("aspects"), list):
        raise ValueError("缺少 aspects 列表")
    by_key = {a.get("key"): a for a in data["aspects"] if isinstance(a, dict)}
    if not any(k in by_key for k in (a["key"] for a in previous_aspects)):
        raise ValueError("没有一个已知的方面")  # 答非所问

    aspects = []
    for old in previous_aspects:
        item, new = by_key.get(old["key"]), dict(old)
        if old["state"] == "na" and old["key"] == "roles":
            aspects.append(new)  # 个人项目的 Roles 由代码决定，不让 AI 改
            continue
        if item:
            state = item.get("state") if item.get("state") in STATES else old["state"]
            summary = text(item.get("summary"), 400)
            if state in ("clear", "na") and not summary:
                state = "unclear"  # 说“清楚”却说不出清楚了什么，不算数
            new["state"] = state
            new["summary"] = summary or old.get("summary", "")
            new["source"] = item.get("source") if item.get("source") in SOURCES else (old.get("source") or default_source)
            new["assumption"] = text(item.get("assumption"), 300) or old.get("assumption") or DEFAULT_ASSUMPTION
        aspects.append(new)

    conflicts = parse_conflicts(data.get("conflicts"), previous_conflicts, evidence_sources)
    open_ids = {c["id"] for c in conflicts if c["status"] == "open"}
    unclear_keys = {a["key"] for a in aspects if a["state"] == "unclear"}
    questions = parse_questions(data.get("questions"), unclear_keys | open_ids, open_ids) if ask else []
    return {"aspects": aspects, "conflicts": conflicts, "questions": questions}


def parse_conflicts(raw, previous, evidence_sources):
    """旧冲突沿用 id；新冲突必须带上能在资料里找到的原文证据，否则丢弃（防止编造 guideline 要求）。"""
    conflicts = {c["id"]: dict(c) for c in previous}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        cid = text(item.get("id"), 10) or f"C{len(conflicts) + 1}"
        issue, evidence = text(item.get("issue"), 300), text(item.get("evidence"), 300)
        if cid in conflicts:
            old = conflicts[cid]
            if item.get("status") == "resolved" and text(item.get("resolution")):
                old.update(status="resolved", resolution=text(item.get("resolution"), 300))
            continue
        if not issue or not quote_is_in(evidence, *evidence_sources):
            ai_client.logger.warning("丢弃没有真实证据的冲突：%s", issue[:60])
            continue
        status = "resolved" if item.get("status") == "resolved" and text(item.get("resolution")) else "open"
        conflicts[cid] = {"id": cid, "issue": issue, "evidence": evidence, "options": str_list(item.get("options"), 4, 200),
                          "status": status, "resolution": text(item.get("resolution"), 300) if status == "resolved" else ""}
        if len(conflicts) >= 6:
            break
    return list(conflicts.values())


def parse_questions(raw, allowed_refs, conflict_ids):
    questions = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or text(item.get("ref"), 40) not in allowed_refs:
            continue
        question = text(item.get("question"), 300)
        if not question:
            continue
        options = [o for o in str_list(item.get("options"), 4, 120) if o.lower() != UNKNOWN_OPTION.lower()]
        questions.append({"ref": text(item.get("ref"), 40), "question": question, "why": text(item.get("why"), 300),
                          "options": options + [UNKNOWN_OPTION]})
    questions.sort(key=lambda q: q["ref"] not in conflict_ids)  # 冲突先问（sort 是稳定的，其余顺序不变）
    return questions[:QUESTIONS_PER_ROUND]


def fallback_questions(aspects, conflicts):
    """AI 一道合格的题都没给、但还有缺口时，用方面的说明直接问（只有手写框和 “I don't know”）。"""
    refs = [(c["id"], c["issue"], "This conflicts with your material; how do you want to resolve it?")
            for c in conflicts if c["status"] == "open"]
    refs += [(a["key"], f"{a['name']}: {a['hint']}", "This aspect is still unclear.")
             for a in aspects if a["state"] == "unclear"]
    return [{"ref": ref, "question": q, "why": why, "options": [UNKNOWN_OPTION]} for ref, q, why in refs[:QUESTIONS_PER_ROUND]]


# ======================= 回答与结束 =======================
def collect_answers(questions, form):
    """手写回答优先；没写就用选中的选项；都没有就记为未回答。"""
    answers = []
    for i, q in enumerate(questions):
        custom = form.get(f"q{i}_text", "").strip()
        chosen = form.get(f"q{i}", "").strip()
        answer = custom[:500] if custom else (chosen if chosen in q["options"] else UNANSWERED)
        answers.append({"aspect": q["ref"], "question": q["question"], "answer": answer})
    return answers


def finish_with_assumptions(aspects):
    """还没清楚的方面全部变成假设。返回新的列表，不修改原列表。"""
    return [dict(a, state="assumed") if a["state"] == "unclear" else dict(a) for a in aspects]


def is_settled(aspects, conflicts):
    return all(a["state"] != "unclear" for a in aspects) and all(c["status"] != "open" for c in conflicts)


def context_block(aspects, conflicts):
    """给下游工具（Prompt Generator、Task Planner、Paper Finder、Report Drafter）用的需求摘要。
    已确认、推荐、假设分开写，下游必须把基于假设的内容标出来。"""
    groups = {"confirmed": [], "recommended": [], "assumed": [], "na": []}
    for a in aspects:
        if a["state"] == "clear":
            groups["recommended" if a.get("source") == "recommended" else "confirmed"].append(f"- {a['name']}: {a['summary']}")
        elif a["state"] in ("assumed", "unclear"):
            groups["assumed"].append(f"- {a['name']}: {a.get('assumption') or DEFAULT_ASSUMPTION}")
        elif a["state"] == "na":
            groups["na"].append(f"- {a['name']}")
    decided = [f"- {c['issue']} -> decided: {c['resolution']}" for c in conflicts if c["status"] == "resolved"]
    sections = [
        "<requirements>",
        "[CONFIRMED] (from the brief or the student's answers):\n" + ("\n".join(groups["confirmed"]) or "- none"),
        "[RECOMMENDED] (the student did not know; usual choice, not confirmed):\n" + ("\n".join(groups["recommended"]) or "- none"),
        "[ASSUMED] (never answered; anything based on these must be labelled as an assumption):\n"
        + ("\n".join(groups["assumed"]) or "- none"),
        "[NOT APPLICABLE]:\n" + ("\n".join(groups["na"]) or "- none"),
        "[DECISIONS ON CONFLICTS]:\n" + ("\n".join(decided) or "- none"),
        "</requirements>",
    ]
    return "\n".join(sections)
