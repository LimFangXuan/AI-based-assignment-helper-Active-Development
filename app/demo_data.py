"""示例数据：一个项目走完全部五个工具，其余项目让 Overview、日历、Today 都有内容。

全部是虚构的：人名、论文、期刊都不存在，DOI 用的是留给示例的 10.5555 前缀。
seed_demo.py（本机演示）和演示模式（DEMO_MODE=1，启动时和点 “Reset demo data” 时）共用这一份。
"""
import json
from datetime import date, datetime, timedelta

from .extensions import db
from .models import (Paper, PaperSearch, Project, PromptSession, ReportDraft, ReportSection,
                        RequirementsCheck, Task, User)
from .services import prompt_generator as pg
from .services import requirements_checker as rc

DEMO_USERNAME = "demo"


def dt(days, hour=23, minute=59):
    today = date.today()
    return datetime.combine(today + timedelta(days=days), datetime.min.time()).replace(hour=hour, minute=minute)


def aspects_for(work_mode, spec):
    """spec: {key: (state, summary, source)}；没写的方面默认 clear。"""
    out = []
    for a in rc.initial_aspects(work_mode):
        state, summary, source = spec.get(a["key"], ("clear", "", "brief"))
        a.update(state=state, summary=summary, source=source)
        out.append(a)
    return out


def reset(password=None):
    """删掉旧的演示账号（连同它的全部数据）并重新创建。password 为空时账号没有可用的密码（演示模式只能点按钮进入）。"""
    old = User.query.filter_by(username=DEMO_USERNAME).first()
    if old:
        db.session.delete(old)
        db.session.flush()
    user = User(username=DEMO_USERNAME, email="demo@example.com", email_verified=True, timezone="Asia/Kuala_Lumpur")
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    db.session.add(user)
    db.session.flush()
    _fill(user)
    db.session.commit()
    return user


def _fill(user):
    today = date.today()

    # ---------------- A. 走完全部工具的报告 ----------------
    a = Project(
        user_id=user.id, name="Chatbots for First-Year Student Support", deadline=dt(12), status="in_progress",
        type="report", work_mode="individual", citation_style="apa7",
        description="Write a 2,000-word report on how a Malaysian university could use chatbots to support first-year "
                    "students. Include a short literature review and practical recommendations. I want to compare "
                    "rule-based and LLM-based chatbots and argue which one suits onboarding questions best.",
        guideline="Marking: literature review 30%, comparative analysis 40%, recommendations 20%, structure and "
                  "presentation 10%. Use at least 8 academic sources from the last 10 years. APA 7th edition. "
                  "Maximum 2,000 words excluding references.")
    db.session.add(a)
    db.session.flush()
    fp = a.fingerprint
    aspects = aspects_for("individual", {
        "audience": ("clear", "The module lecturer, who marks against the rubric and expects a critical argument.", "student"),
        "methods_tools": ("clear", "Secondary desk research and a comparative analysis of rule-based versus LLM chatbots.", "recommended"),
        "timeline_concerns": ("assumed", "", ""),
        "success_definition": ("clear", "Aiming for a distinction (75%+), so rigorous critique matters more than coverage.", "student"),
        "data_resources": ("na", "No primary data collection is required.", "brief"),
    })
    for x in aspects:
        if x["state"] == "clear" and not x["summary"]:
            x["summary"] = {
                "deliverable": "One individual written report of at most 2,000 words, excluding references.",
                "topic_scope": "Chatbot support for first-year students at a Malaysian university, rule-based versus LLM-based.",
                "required_content": "Literature review, comparative analysis, recommendations.",
                "guideline_constraints": "APA 7th edition, at least 8 sources from the last 10 years, 2,000-word cap.",
                "evaluation_criteria": "Literature review 30%, analysis 40%, recommendations 20%, presentation 10%.",
                "citation_sources": "APA 7th edition with at least 8 academic sources.",
            }.get(x["key"], "Clear from the brief.")
        if x["state"] == "assumed":
            x["assumption"] = "About ten focused hours per week are available until the deadline."
    check = RequirementsCheck(
        project_id=a.id, status="complete_with_assumptions", round_number=2, content_fingerprint=fp,
        aspects_json=json.dumps(rc.finish_with_assumptions(aspects)), conflicts_json=json.dumps([{
            "id": "C1", "issue": "A full survey of every chatbot type does not fit into 2,000 words.",
            "evidence": "compare rule-based and LLM-based chatbots", "options": ["Focus on two architectures", "Ask the lecturer to widen the limit"],
            "status": "resolved", "resolution": "Focus on two architectures and one first-year onboarding scenario."}]),
        history_json=json.dumps([{"round": 1, "answers": [
            {"aspect": "success_definition", "question": "What result are you aiming for?", "answer": "A distinction (75%+)"}]}]))
    db.session.add(check)
    db.session.flush()

    framework = {
        "goal": "Argue, with evidence, which chatbot architecture best supports first-year onboarding in a Malaysian university.",
        "approach": "Build a small evidence base first, compare the two architectures on explicit criteria, then turn the comparison into phased recommendations.",
        "phases": [
            {"name": "Build the evidence base", "goal": "Eight to ten strong recent sources.",
             "steps": ["Search for studies on university chatbots and first-year transition", "Select eight to ten papers from 2016 onwards",
                       "Extract findings into a synthesis table"], "deliverables": ["Annotated source table"]},
            {"name": "Compare the architectures", "goal": "A defensible comparison.",
             "steps": ["Define comparison criteria: accuracy, cost, maintenance, multilingual support",
                       "Score rule-based and LLM-based chatbots against each criterion"], "deliverables": ["Comparison matrix"]},
            {"name": "Draft the report", "goal": "A complete draft close to 2,000 words.",
             "steps": ["Write the literature review (about 600 words)", "Write the comparative analysis (about 800 words)",
                       "Write recommendations, introduction and conclusion"], "deliverables": ["Full draft"], "based_on_assumption": True},
            {"name": "Check against the rubric", "goal": "No marks lost on format.",
             "steps": ["Audit each section against the rubric weights", "Check word count and APA 7 formatting"], "deliverables": ["Submission-ready report"]},
        ],
        "methods": ["Secondary desk research", "Multi-criteria comparative analysis"], "deliverables": ["2,000-word report with APA 7 references"],
        "risks": ["Descriptive writing instead of analysis: structure every section around the comparison criteria."],
        "decisions_needed": [], "ai_role": "An academic supervisor who knows higher-education technology research.",
        "assumptions_used": ["About ten hours per week are available until the deadline."]}
    decisions = {"Which structure should the analysis follow?": {"question": "Which structure should the analysis follow?", "choice": "By criterion"}}
    ps = PromptSession(project_id=a.id, requirements_check_id=check.id, content_fingerprint=fp,
                       framework_json=json.dumps(framework), questions_json="[]",
                       answers_json=json.dumps({"notes": [], "decisions": decisions}),
                       final_prompt=pg.build_prompt(a, check.aspects, check.conflicts, framework, decisions))
    db.session.add(ps)
    db.session.flush()

    tasks = [
        ("Search for studies on university chatbots", -3, 60, True, "Ten candidate papers saved with notes."),
        ("Select and read the best eight sources", -2, 120, True, "Eight papers shortlisted, key findings highlighted."),
        ("Build the comparison matrix", -1, 90, True, "A table scoring both architectures on four criteria."),
        ("Draft the literature review (about 600 words)", 0, 120, False, "Themes grouped, every claim tied to a source."),
        ("Draft the comparative analysis (about 800 words)", 1, 150, False, "One subsection per criterion with a verdict."),
        ("Write recommendations, introduction and conclusion", 3, 120, False, "Phased recommendations with risks."),
        ("Audit against the rubric and check APA 7", 6, 90, False, "Each rubric line mapped to a paragraph."),
        ("Final proofread and submit", 11, 45, False, "Word count under 2,000, references complete."),
    ]
    for i, (title, off, minutes, done, detail) in enumerate(tasks):
        db.session.add(Task(project_id=a.id, title=title, due_date=today + timedelta(days=off), minutes=minutes, done=done,
                            detail=detail, position=i, content_fingerprint=fp, based_on_assumption=(i == 5),
                            done_at=datetime.now() - timedelta(days=-off) if done else None))

    search = PaperSearch(project_id=a.id, session_id=ps.id, requested_count=6, oa_only=True, candidate_count=24,
                         queries_json=json.dumps(["university chatbot first-year students", "rule-based versus LLM chatbot higher education",
                                                  "conversational agent student retention"]))
    db.session.add(search)
    db.session.flush()
    papers = [
        ("Conversational agents for student support in higher education: a systematic review", ["Lena Hoffmann", "Arjun Menon", "Cheng Wei Tan"], 2023,
         "Computers & Education", 189, "Chatbots can answer routine administrative questions reliably, but evidence on retention effects is mixed.",
         "Directly reviews student-support chatbots, giving the evidence base for the literature review.", 9),
        ("Large language model assistants in university onboarding: promise and risk", ["Siti Nurhaliza", "Daniel Okafor"], 2024,
         "Journal of Educational Technology", 74, "LLM assistants handle open-ended queries well but hallucinate policy details without retrieval grounding.",
         "Supplies the hallucination and governance angle for the LLM side of the comparison.", 9),
        ("Rule-based dialogue systems in student services: costs and maintenance", ["Priya Raman", "Thomas Eriksson"], 2019,
         "Information Systems Frontiers", 112, "Decision-tree chatbots are cheap to run and predictable, but need constant manual updates.",
         "Evidence for the rule-based side: cost, predictability and maintenance burden.", 8),
        ("Multilingual chatbots for Southeast Asian universities", ["Nur Aisyah Rahman", "Wei Jie Lim"], 2022,
         "Asia-Pacific Education Review", 41, "Code-switching between English and Bahasa Malaysia is the main source of failed queries.",
         "Local context for a Malaysian university, covering the multilingual criterion.", 8),
        ("First-year transition and help-seeking behaviour", ["Rachel Donnelly", "Kofi Mensah"], 2018,
         "Studies in Higher Education", 356, "First-year students often avoid asking staff and prefer anonymous, always-available help.",
         "Explains why an always-available chatbot suits first-year onboarding.", 7),
        ("Evaluating chatbot accuracy and student trust", ["Mei Ling Chong", "Jonas Berg"], 2021,
         "International Journal of Human-Computer Studies", 98, "Trust drops sharply after a single confidently wrong answer.",
         "Supports an accuracy-first recommendation and the case for human hand-off.", 7),
    ]
    paper_rows = []
    for rank, (title, authors, year, venue, cites, abstract, reason, rel) in enumerate(papers, 1):
        p = Paper(search_id=search.id, openalex_id=f"W31{rank}00{rank}", title=title, authors=", ".join(authors[:3]),
                  author_list_json=json.dumps(authors), year=year, venue=venue, doi=f"10.1000/demo.{rank}", is_oa=True,
                  url=f"https://openalex.org/W31{rank}00{rank}", oa_url="https://example.org/paper.pdf", cited_by_count=cites,
                  work_type="article", abstract_snippet=abstract, reason=reason, relevance=rel, rank=rank)
        db.session.add(p)
        paper_rows.append(p)
    db.session.flush()
    pid = [p.id for p in paper_rows]

    outline = {"source": "template", "sections": [
        {"title": "Introduction", "purpose": "Set the context, the question and the structure of the report.", "key_points": ["Why first-year support matters"], "target_words": 200},
        {"title": "Literature Review", "purpose": "What existing research says about support chatbots.", "key_points": ["Effectiveness", "Limits"], "target_words": 600},
        {"title": "Comparative Analysis", "purpose": "Rule-based versus LLM-based against four criteria.", "key_points": ["Accuracy", "Cost", "Maintenance", "Multilingual"], "target_words": 800},
        {"title": "Recommendations", "purpose": "Practical, phased advice for a Malaysian university.", "key_points": [], "target_words": 400},
        {"title": "Conclusion", "purpose": "Answer the question in a few sentences.", "key_points": [], "target_words": 100}]}
    draft = ReportDraft(project_id=a.id, template_key="report", content_fingerprint=fp, outline_json=json.dumps(outline))
    db.session.add(draft)
    db.session.flush()
    bodies = [
        ("approved", f"First-year students are the group most likely to need help and the least likely to ask for it [P{pid[4]}]. "
                     f"Universities have therefore turned to chatbots that answer routine questions at any hour [P{pid[0]}].\n\n"
                     "This report compares rule-based and large language model (LLM) chatbots and argues that a hybrid design suits "
                     "onboarding in a Malaysian university best.", [pid[4], pid[0]]),
        ("approved", f"Systematic evidence shows that support chatbots handle routine administrative questions reliably, although "
                     f"the effect on retention is still unclear [P{pid[0]}]. Rule-based systems are cheap and predictable but demand "
                     f"constant manual updates [P{pid[2]}], while LLM assistants cope with open-ended questions but can invent policy "
                     f"details when they are not grounded in official documents [P{pid[1]}].\n\n"
                     f"Local studies add a third factor: code-switching between English and Bahasa Malaysia is the leading cause of failed "
                     f"queries [P{pid[3]}].", [pid[0], pid[2], pid[1], pid[3]]),
        ("draft", f"Accuracy is the first criterion. Trust in a chatbot falls sharply after one confident wrong answer [P{pid[5]}], "
                  f"which makes ungrounded LLM output a real risk for questions about fees, deadlines and visas [P{pid[1]}].\n\n"
                  "On cost, rule-based chatbots win in the first year but their maintenance burden grows with every policy change. "
                  "A hybrid model keeps rules for high-stakes answers and lets an LLM handle everything else.", [pid[5], pid[1]]),
        ("pending", "", []), ("pending", "", [])]
    for i, (sec, (status, content, cited)) in enumerate(zip(outline["sections"], bodies)):
        db.session.add(ReportSection(draft_id=draft.id, position=i, title=sec["title"], content=content, status=status,
                                     cited_paper_ids_json=json.dumps(cited)))

    # ---------------- B. 需求检查进行中 ----------------
    b = Project(
        user_id=user.id, name="Hash Table Performance Study", deadline=dt(5), status="in_progress", type="software_development",
        work_mode="group", citation_style="ieee",
        description="Our group of three will implement a resizable hash table in C++ and compare linear probing with separate "
                    "chaining. We need to benchmark both and write up the results.",
        guideline="Marks: implementation 50%, performance analysis 30%, report 20%. Standard library only. Each member submits their own report.")
    db.session.add(b)
    db.session.flush()
    b_aspects = aspects_for("group", {
        "roles": ("unclear", "", ""), "evaluation_criteria": ("unclear", "", ""), "timeline_concerns": ("unclear", "", ""),
        "audience": ("na", "Marked by the lecturer; no other audience.", "brief")})
    for x in b_aspects:
        if x["state"] == "clear":
            x["summary"] = {"deliverable": "A C++ implementation, benchmark results and an individual report.",
                            "topic_scope": "Resizable hash table, linear probing against separate chaining.",
                            "guideline_constraints": "Standard library only; individual reports."}.get(x["key"], "Clear from the brief.")
    db.session.add(RequirementsCheck(
        project_id=b.id, status="in_progress", round_number=1, content_fingerprint=b.fingerprint,
        aspects_json=json.dumps(b_aspects),
        questions_json=json.dumps([
            {"ref": "roles", "question": "Who in your group is responsible for which part?", "why": "Splits the implementation, benchmarking and write-up so nothing is duplicated.",
             "options": ["I own the whole implementation", "Each of us owns one module", "We haven't split it yet", "I don't know"]},
            {"ref": "evaluation_criteria", "question": "Does the marking rubric say how performance analysis is scored?", "why": "Decides how deep the benchmarking needs to go.",
             "options": ["It lists specific metrics", "It only says 'analysis'", "I don't know"]},
            {"ref": "timeline_concerns", "question": "Is there an interim submission before the final deadline?", "why": "Changes the order of the work.",
             "options": ["Yes, a checkpoint", "No, final only", "I don't know"]}])))
    for i, (title, off, minutes, done) in enumerate([
            ("Read the brief and list every marking criterion", -1, 20, True), ("Write the hash table interface and test cases", 0, 60, False),
            ("Implement the linear probing version", 1, 90, False), ("Implement the separate chaining version", 2, 90, False),
            ("Run the benchmarks and plot the results", 3, 60, False), ("Write my individual report", 4, 120, False)]):
        db.session.add(Task(project_id=b.id, title=title, due_date=today + timedelta(days=off), minutes=minutes, done=done, position=i,
                            done_at=datetime.now() if done else None))

    # ---------------- C. framework 等你拍板 ----------------
    c = Project(
        user_id=user.id, name="Marketing Group Presentation", deadline=dt(9), status="not_started", type="presentation", work_mode="group",
        description="A ten-minute group presentation analysing the social media strategy of a local coffee brand.",
        guideline="Ten minutes plus three minutes of questions. Slides are marked on clarity and use of data.")
    db.session.add(c)
    db.session.flush()
    c_aspects = aspects_for("group", {})
    for x in c_aspects:
        x["summary"] = "Clear from the brief."
    c_check = RequirementsCheck(project_id=c.id, status="complete", round_number=1, content_fingerprint=c.fingerprint,
                                aspects_json=json.dumps(c_aspects), conflicts_json="[]", questions_json="[]")
    db.session.add(c_check)
    db.session.flush()
    c_fw = {"goal": "Deliver a clear ten-minute analysis of the brand's social media strategy.", "approach": "Collect posts, find patterns, then tell the story in slides.",
            "phases": [{"name": "Collect the data", "steps": ["Pick the brand and platforms", "Collect three months of posts"], "deliverables": ["Post dataset"]},
                       {"name": "Find the story", "steps": ["Group posts by theme", "Measure engagement per theme"], "deliverables": ["Three key findings"]},
                       {"name": "Build and rehearse", "steps": ["Design the slides", "Rehearse to ten minutes"], "deliverables": ["Final deck"]}],
            "methods": ["Content analysis"], "deliverables": ["Slide deck"], "risks": ["Too many slides for ten minutes."],
            "decisions_needed": [{"id": "D1", "question": "How should the group split the speaking time?", "options": [
                {"label": "Each member presents one finding", "effect": "Even workload, but the story can feel disjointed"},
                {"label": "One lead speaker with two supporters", "effect": "Smoother story, uneven workload"}]}],
            "ai_role": "A presentation coach for university students.", "assumptions_used": []}
    db.session.add(PromptSession(project_id=c.id, requirements_check_id=c_check.id, content_fingerprint=c.fingerprint,
                                 framework_json=json.dumps(c_fw), questions_json="[]", answers_json=json.dumps({"notes": [], "decisions": {}})))

    # ---------------- D / E. 逾期、可提交、已提交 ----------------
    d = Project(user_id=user.id, name="Statistics Lab 3", deadline=dt(-1), status="in_progress", type="lab_report", work_mode="individual",
                description="Write up the regression lab: model, residual checks and interpretation.", guideline="")
    e = Project(user_id=user.id, name="Database Design Coursework", deadline=dt(16), status="done", type="system_database_design",
                work_mode="group", description="Design and normalise a database for a campus library system.", guideline="")
    f = Project(user_id=user.id, name="Calculus Problem Set 4", deadline=dt(-8), status="submitted", type="exam_preparation",
                work_mode="individual", description="Chapter 6 exercises 1 to 20.", guideline="")
    db.session.add_all([d, e, f])
    db.session.flush()
    for i, (title, off, minutes, done) in enumerate([("Fit the regression model", -2, 45, True), ("Check the residual plots", -1, 40, False),
                                                      ("Write the interpretation section", 0, 60, False)]):
        db.session.add(Task(project_id=d.id, title=title, due_date=today + timedelta(days=off), minutes=minutes, done=done, position=i,
                            done_at=datetime.now() if done else None))
    for i, (title, off) in enumerate([("Draft the entity-relationship diagram", 2), ("Normalise to third normal form", 5)]):
        db.session.add(Task(project_id=e.id, title=title, due_date=today + timedelta(days=off), minutes=75, done=False, position=i))
    for i, (title, off, minutes) in enumerate([("Agree the brand and split the work", 1, 30), ("Collect the brand's posts", 3, 90),
                                                ("Find three key findings", 5, 90)]):
        db.session.add(Task(project_id=c.id, title=title, due_date=today + timedelta(days=off), minutes=minutes, done=False, position=i))
