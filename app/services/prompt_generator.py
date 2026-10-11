"""Prompt Generator：把确认过的需求变成项目 framework，再拼出可以粘贴到其他 AI 聊天窗口的 prompt（spec §7.2）。

- 没有单独的提问阶段：输入是 Requirements Checklist 的结果（已确认 / 推荐 / 假设）+ 描述 + guideline。
- framework = 怎么做这个项目（阶段、方法、交付物），不是文档大纲。
- framework 需要学生拍板的地方（例如两种可行的结构），放在 decisions_needed 里，在同一页让学生选。
- 最终 prompt 由代码拼接：安全部分（区分已确认/推荐/假设、执行前检查、禁止编造来源）是固定的，不交给模型。
  prompt 要求对方 AI 一步一步做、每步等学生确认；不加“只讲解、不替我写”之类的限制。
"""
from . import ai_client
from ..constants import TYPE_KNOWLEDGE
from .ai_client import AIServiceError
from .common import check_input_size, project_block, read_skill, str_list, text
from .privacy import redact
from .requirements_checker import context_block

MIN_PHASES, MAX_PHASES = 2, 8
MAX_DECISIONS = 3
DEFAULT_ROLE = ("You are an experienced academic mentor and practitioner in this subject, "
                "helping a university student complete this assignment to a high standard.")


def best_practices(project_type):
    bank = TYPE_KNOWLEDGE.get(project_type)
    files = ["best_practices/common.md", f"best_practices/{bank}.md"] if bank else ["best_practices/general.md"]
    return "\n".join(x for x in (read_skill(f"prompt_generator/{f}") for f in files) if x)


def generate_framework(project, aspects, conflicts, notes=None, decisions=None):
    """1 次 AI：根据需求生成项目 framework。notes 是学生写的修改意见，decisions 是学生已经选好的方案。"""
    check_input_size(project)
    notes_block = "\n".join(f"- {redact(n)}" for n in notes or []) or "(none)"
    decided = "\n".join(f"- {d['question']} -> {d['choice']}" for d in (decisions or {}).values()) or "(none)"
    prompt = f"""[TASK:FRAMEWORK]
{project_block(project)}

{context_block(aspects, conflicts)}

Good practice for this type of assignment:
{best_practices(getattr(project, "type", None))}

The student's corrections to earlier versions (follow them):
{notes_block}

Decisions the student has already made (follow them, do not ask again):
{decided}

Write the project framework: HOW to do this project from now until submission (phases, methods, deliverables).
It is not the outline of the final document. Base it only on the material and requirements above.
If a phase relies on an [ASSUMED] requirement, set based_on_assumption to true.
If there is a genuine fork that only the student can decide (for example two different valid structures or methods
that change the work a lot) and it is not already decided, add it to decisions_needed (at most {MAX_DECISIONS}).
Do not put trivial choices there.

Return JSON only:
{{"goal": "one sentence",
  "approach": "two to four sentences on the overall approach",
  "phases": [{{"name": "...", "goal": "...", "steps": ["concrete action", "..."], "deliverables": ["..."], "based_on_assumption": false}}],
  "methods": ["..."],
  "deliverables": ["final things handed in"],
  "risks": ["risk and how to avoid it"],
  "decisions_needed": [{{"id": "D1", "question": "...", "options": [{{"label": "...", "effect": "what changes if chosen"}}]}}],
  "ai_role": "who the other AI chat should act as for this project, one or two sentences, no invented credentials; do not limit it to guiding only or forbid it from writing (the student decides how much help to take)",
  "assumptions_used": ["which assumed requirements the framework relies on"]}}
{MIN_PHASES} to {MAX_PHASES} phases, each with 2 to 6 steps. Write everything in English."""
    data = ai_client.ask_gemini_json(prompt)
    try:
        return parse_framework(data, decisions or {})
    except ValueError as e:
        raise AIServiceError("The AI framework was in the wrong format. Please try again.") from e


def parse_framework(data, decided):
    if not isinstance(data, dict) or not isinstance(data.get("phases"), list):
        raise ValueError("缺少 phases")
    phases = []
    for p in data["phases"][:MAX_PHASES]:
        if not isinstance(p, dict):
            continue
        name, steps = text(p.get("name"), 120), str_list(p.get("steps"), 6, 300)
        if name and steps:
            phases.append({"name": name, "goal": text(p.get("goal"), 300), "steps": steps,
                           "deliverables": str_list(p.get("deliverables"), 5, 200),
                           "based_on_assumption": bool(p.get("based_on_assumption"))})
    if len(phases) < MIN_PHASES:
        raise ValueError("阶段太少")
    decisions = []
    for d in data.get("decisions_needed") if isinstance(data.get("decisions_needed"), list) else []:
        if not isinstance(d, dict):
            continue
        options = [{"label": text(o.get("label"), 150), "effect": text(o.get("effect"), 250)}
                   for o in d.get("options") or [] if isinstance(o, dict) and text(o.get("label"))]
        question = text(d.get("question"), 250)
        if question and len(options) >= 2 and question not in {x["question"] for x in decided.values()}:
            decisions.append({"id": f"D{len(decisions) + 1}", "question": question, "options": options[:4]})
        if len(decisions) == MAX_DECISIONS:
            break
    return {
        "goal": text(data.get("goal"), 300),
        "approach": text(data.get("approach"), 800),
        "phases": phases,
        "methods": str_list(data.get("methods"), 8, 200),
        "deliverables": str_list(data.get("deliverables"), 8, 200),
        "risks": str_list(data.get("risks"), 6, 250),
        "decisions_needed": decisions,
        "ai_role": text(data.get("ai_role"), 400) or DEFAULT_ROLE,
        "assumptions_used": str_list(data.get("assumptions_used"), 8, 250),
    }


# ======================= 最终 prompt（纯代码，不调用 AI） =======================
def _bullets(items, empty="- none"):
    return "\n".join(f"- {x}" for x in items) or empty


def build_prompt(project, aspects, conflicts, framework, decisions):
    """把已校验的部分拼成最终 prompt。安全规则固定写在这里，不依赖模型。"""
    confirmed = [f"{a['name']}: {a['summary']}" for a in aspects if a["state"] == "clear" and a.get("source") != "recommended"]
    recommended = [f"{a['name']}: {a['summary']}" for a in aspects if a["state"] == "clear" and a.get("source") == "recommended"]
    assumed = [f"{a['name']}: {a.get('assumption')}" for a in aspects if a["state"] in ("assumed", "unclear")]
    resolved = [f"{c['issue']} -> {c['resolution']}" for c in conflicts if c["status"] == "resolved"]
    chosen = [f"{d['question']} -> {d['choice']}" for d in decisions.values()]

    phases = []
    for i, p in enumerate(framework["phases"], 1):
        label = " [relies on an assumption]" if p.get("based_on_assumption") else ""
        lines = [f"### Phase {i}: {p['name']}{label}"]
        if p.get("goal"):
            lines.append(f"Goal: {p['goal']}")
        lines += [f"{j}. {s}" for j, s in enumerate(p["steps"], 1)]
        if p.get("deliverables"):
            lines.append("Output of this phase: " + "; ".join(p["deliverables"]))
        phases.append("\n".join(lines))

    guideline = redact(getattr(project, "guideline", "") or "")
    sections = [
        "# Your role\n" + framework["ai_role"],
        "# The project\n"
        f"- Name: {project.name}\n- Deadline: {project.deadline.strftime('%Y-%m-%d %H:%M')}\n"
        f"- Individual or group: {getattr(project, 'work_mode', 'individual')}\n"
        f"- Citation style: {getattr(project, 'citation_style', None) or 'not specified'}\n"
        f"- Goal: {framework['goal'] or 'see the requirements below'}",
        "# The brief (written by me)\n" + (redact(project.description) or "(none)")
        + ("\n\n## Guideline / marking rubric\n" + guideline if guideline else ""),
        "# Requirements\n"
        "## [CONFIRMED]\n" + _bullets(confirmed)
        + "\n\n## [RECOMMENDED] (I wasn't sure; this is the usual choice, not confirmed)\n" + _bullets(recommended)
        + "\n\n## [ASSUMED] (never confirmed; tell me if anything you do depends on these)\n" + _bullets(assumed)
        + ("\n\n## Decisions already made\n" + _bullets(resolved + chosen) if resolved or chosen else ""),
        "# Project framework\n" + (framework["approach"] + "\n\n" if framework["approach"] else "") + "\n\n".join(phases)
        + ("\n\nMethods: " + "; ".join(framework["methods"]) if framework["methods"] else "")
        + ("\nFinal deliverables: " + "; ".join(framework["deliverables"]) if framework["deliverables"] else "")
        + ("\nRisks to watch: " + "; ".join(framework["risks"]) if framework["risks"] else ""),
        "# How we will work\n"
        "1. Before doing anything, restate the task in your own words and list anything that is unclear, "
        "contradictory or missing. Then wait for my reply.\n"
        "2. Work through the framework one step at a time. For each step, do the work, show me the result, "
        "and stop. Wait for my confirmation or corrections before moving to the next step.\n"
        "3. Clearly mark anything that depends on an [ASSUMED] or [RECOMMENDED] item.\n"
        "4. Never invent sources, citations, quotations, data or facts. If something needs a source, say what kind of "
        "source is needed and let me provide it.\n"
        "5. If anything I ask for conflicts with the requirements or the guideline above, tell me before doing it.\n"
        "6. Reply in the language I write in.",
    ]
    return "\n\n".join(sections) + "\n"
