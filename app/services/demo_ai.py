"""演示模式下代替 Gemini 的离线回答器：根据请求里的任务标记，返回格式正确的样本 JSON。

它只读取请求本身（项目名称、方面列表、日期、候选论文编号等），所以返回的内容和当前项目对得上；
回答会照常经过代码的校验，演示的就是真实的流程。这里不发出任何网络请求。
"""
import json
import re
from datetime import date, timedelta

SUMMARIES = {
    "deliverable": "A written submission for “{name}”, as described in the brief.",
    "audience": "The lecturer who marks it against the rubric.",
    "topic_scope": "The topic and scope set out in the description, nothing beyond it.",
    "required_content": "The sections and elements listed in the brief.",
    "guideline_constraints": "The format, length and rules given in the guideline.",
    "evaluation_criteria": "Marked against the rubric in the guideline.",
    "methods_tools": "Methods that suit this type of assignment, as the description suggests.",
    "data_resources": "Published sources plus the material provided with the brief.",
    "roles": "Each group member owns one part; the parts are merged a few days before the deadline.",
    "citation_sources": "Academic sources, cited in the chosen style.",
    "timeline_concerns": "One final submission before the deadline.",
    "success_definition": "Aiming for a high mark, so analysis matters more than coverage.",
}
QUESTIONS = {
    "audience": ("Who is the main reader of this work?", "Sets the tone and how much background to explain.",
                 ["The lecturer marking it", "Industry readers", "Fellow students"]),
    "success_definition": ("What result are you aiming for?", "Decides where to spend the extra effort.",
                           ["A distinction", "A solid pass", "Mainly to learn the topic"]),
}
UNCLEAR_FIRST = ("success_definition", "audience")


def _name(prompt):
    found = re.search(r"^Name: (.+)$", prompt, re.M)
    return found.group(1).strip() if found else "this project"


def _aspect_keys(prompt):
    return re.findall(r"^- ([a-z_]+) \(.+?\): .*\| current state: \w+", prompt, re.M)


def _requirements_prescan(prompt):
    keys, name = _aspect_keys(prompt), _name(prompt)
    unclear = [k for k in UNCLEAR_FIRST if k in keys]
    aspects = [{"key": k, "state": "unclear", "summary": "", "assumption": SUMMARIES.get(k, "Common practice.")}
               if k in unclear else {"key": k, "state": "clear", "summary": SUMMARIES.get(k, "Clear from the brief.").format(name=name),
                                     "source": "brief"} for k in keys]
    questions = [{"ref": k, "question": QUESTIONS[k][0], "why": QUESTIONS[k][1], "options": QUESTIONS[k][2]} for k in unclear]
    return {"aspects": aspects, "conflicts": [], "questions": questions}


def _requirements_round(prompt):
    keys, name = _aspect_keys(prompt), _name(prompt)
    answers = dict(re.findall(r"^- Q \(([a-z_]+)\): .+\n  A: (.+)$", prompt, re.M))
    aspects = []
    for k in keys:
        answer = answers.get(k, "").strip()
        if answer and answer not in ("I don't know", "(no answer)"):
            aspects.append({"key": k, "state": "clear", "summary": f"You said: {answer}.", "source": "student"})
        elif answer:
            aspects.append({"key": k, "state": "clear", "summary": "Recommended: " + SUMMARIES.get(k, "the usual choice.").format(name=name),
                            "source": "recommended"})
        else:
            aspects.append({"key": k, "state": "clear", "summary": SUMMARIES.get(k, "Clear from the brief.").format(name=name), "source": "brief"})
    return {"aspects": aspects, "conflicts": [], "questions": []}


def _framework(prompt):
    name = _name(prompt)
    decided_block = prompt.split("Decisions the student has already made", 1)[-1].split("Write the project framework", 1)[0]
    notes = re.findall(r"^- (.+)$", prompt.split("The student's corrections to earlier versions (follow them):", 1)[-1]
                       .split("Decisions the student has already made", 1)[0], re.M)
    approach = "Pin down what is marked, gather a small set of strong sources, build the core work, then check it against the rubric."
    if notes:
        approach += " Updated with your notes: " + "; ".join(notes) + "."
    decisions = [] if "(none)" not in decided_block else [{
        "id": "D1", "question": "How should the main part of the work be organised?",
        "options": [{"label": "One section per marking criterion", "effect": "Easy for the marker to find each criterion"},
                    {"label": "One section per theme", "effect": "Reads more naturally, needs a clear map to the rubric"}]}]
    return {
        "goal": f"Complete “{name}” to a high standard before the deadline.",
        "approach": approach,
        "phases": [
            {"name": "Understand the brief", "goal": "Know exactly what earns marks.",
             "steps": ["List every marking criterion", "Note word limits and format rules"], "deliverables": ["Checklist of criteria"]},
            {"name": "Gather sources", "goal": "A small set of strong, recent sources.",
             "steps": ["Search for recent academic papers", "Summarise each source in two lines"], "deliverables": ["Source table"]},
            {"name": "Build the core work", "goal": "A complete first version.",
             "steps": ["Outline the structure", "Write the main sections", "Add evidence for every claim"],
             "deliverables": ["First full draft"], "based_on_assumption": True},
            {"name": "Check and submit", "goal": "No marks lost on avoidable mistakes.",
             "steps": ["Audit the draft against the rubric", "Proofread and check references"], "deliverables": ["Final submission"]},
        ],
        "methods": ["Secondary research", "Structured comparison"], "deliverables": ["Final submission"],
        "risks": ["Running out of time for the last check: finish the draft two days early."],
        "decisions_needed": decisions,
        "ai_role": "An experienced tutor in this subject who works through the project with the student step by step.",
        "assumptions_used": ["About ten hours a week are available."],
    }


PLAN_STEPS = [("Re-read the brief and list every marking criterion", "A checklist of what is marked.", 30),
              ("Collect and read the key sources", "Five sources with one-line notes.", 120),
              ("Outline the structure", "Headings with two bullet points each.", 60),
              ("Draft the main sections", "A complete first draft.", 180),
              ("Revise against the rubric", "Every criterion mapped to a paragraph.", 90),
              ("Proofread and submit", "References checked, file submitted.", 45)]


def _plan(prompt):
    found = re.search(r"Today is (\d{4}-\d{2}-\d{2}) and the deadline is (\d{4}-\d{2}-\d{2})", prompt)
    today, deadline = (date.fromisoformat(found.group(1)), date.fromisoformat(found.group(2))) if found else (date.today(), date.today())
    span = max(0, (deadline - today).days)
    steps = [{"title": t, "detail": d, "minutes": m, "due_date": (today + timedelta(days=round(span * i / (len(PLAN_STEPS) - 1)))).isoformat(),
              "based_on_assumption": i == 3} for i, (t, d, m) in enumerate(PLAN_STEPS)]
    feasibility = "tight" if span < 4 else "ok"
    message = ("The time is short, so start today and keep each task small." if feasibility == "tight"
               else f"{span} days is enough if you do a little each day.")
    return {"feasibility": feasibility, "message": message, "steps": steps}


def _paper_select(prompt):
    count = int((re.search(r"Pick at most (\d+)", prompt) or [None, "5"])[1])
    picks = re.findall(r"^\[(W\d+)\] (.+?) \(", prompt, re.M)[:count]
    return {"selected": [{"id": wid, "relevance": 9 - i, "reason": f"Background for this project: it covers {title[:70].lower()}."}
                         for i, (wid, title) in enumerate(picks)]}


def _outline(prompt):
    block = prompt.split("Default template (", 1)[-1].split("\n\n", 1)[0]
    sections = [{"title": t.strip(), "purpose": p.strip(), "key_points": [], "target_words": None}
                for t, p in re.findall(r"^- (.+?): (.+)$", block, re.M)]
    return {"source": "template", "sections": sections}


def _section(prompt):
    title = (re.search(r'Write section \d+: "(.+?)"', prompt) or [None, "this section"])[1]
    ids = re.findall(r"^\[P(\d+)\]", prompt, re.M)
    first = f" [P{ids[0]}]" if ids else ""
    second = f" [P{ids[1] if len(ids) > 1 else ids[0]}]" if ids else ""
    return {"paragraphs": [
        {"text": f"This section, {title}, sets out the main argument and connects it to recent research.{first}"},
        {"text": f"Studies of comparable settings report consistent findings, which supports the approach taken here.{second}"},
        {"text": "The practical implications for this project are summarised below and revisited in the conclusion.",
         "based_on_assumption": True},
    ], "assumptions_used": ["About ten hours a week are available."]}


HANDLERS = {
    "[TASK:REQ_PRESCAN]": _requirements_prescan,
    "[TASK:REQ_ROUND]": _requirements_round,
    "[TASK:FRAMEWORK]": _framework,
    "[TASK:PLAN]": _plan,
    "[TASK:PAPER_QUERIES]": lambda prompt: {"queries": ["student study planning", "academic writing support"]},
    "[TASK:PAPER_SELECT]": _paper_select,
    "[TASK:REPORT_OUTLINE]": _outline,
    "[TASK:REPORT_SECTION]": _section,
}


def respond(prompt):
    for marker, handler in HANDLERS.items():
        if prompt.startswith(marker):
            return json.dumps(handler(prompt))
    return json.dumps({})
