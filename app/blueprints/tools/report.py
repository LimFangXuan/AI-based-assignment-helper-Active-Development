"""Report Drafter：先生成大纲，再一节一节写（spec §7.5）。

- 大纲：guideline 规定的结构优先，其次是类型模板（第一版只有 FYP 和 Report）。
- 每节：学生可以阅读、修改、写意见重新生成、批准。批准当前这一节之后，下一节才解锁。
- 引用只能来自 Paper Finder 找到的论文；没有有效引用的段落标 “needs source”。没有 AI 使用记录（spec 不要求）。
"""
import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import ReportDraft, ReportSection, RequirementsCheck
from ...security import get_own_child, login_required
from ...services import report_drafter as rd
from ...services.ai_client import AIServiceError
from . import confirmed_framework, finished_requirements, get_tool_project

bp = Blueprint("report", __name__, url_prefix="/projects/<int:project_id>/tools/report")


def page(project, anchor=""):
    return redirect(url_for("report.index", project_id=project.id) + anchor)


def all_papers(project):
    """这个项目在 Paper Finder 里的全部论文记录（同一篇论文被多次检索到时会有多条记录）。"""
    return [p for search in project.paper_searches for p in search.papers]


def project_papers(project):
    """给 AI 看的论文：同一篇只列一次，保留最早找到的那条记录（之前写的引用一直有效）。"""
    seen, papers = set(), []
    for p in reversed(all_papers(project)):  # paper_searches 按时间倒序，反过来就是从旧到新
        if p.openalex_id not in seen:
            seen.add(p.openalex_id)
            papers.append(p)
    return papers


def citation_style(project):
    """没选、选了 “Follow the guideline” 或 “Not required” 时用 APA 7，页面会提醒学生核对。"""
    return project.citation_style if project.citation_style in ("apa7", "harvard", "ieee", "mla", "chicago") else "apa7"


def current_index(draft):
    """第一个还没批准的章节：只有它和已批准的章节可以操作，后面的都锁住。"""
    return next((i for i, s in enumerate(draft.sections) if s.status != "approved"), len(draft.sections))


def load_section(project, draft_id, section_id, allow_locked=False):
    draft = get_own_child(ReportDraft, draft_id, project)
    section = get_own_child(ReportSection, section_id, draft, field="draft_id")
    index = draft.sections.index(section)
    if not allow_locked and index > current_index(draft):
        abort(400)  # 上一节还没批准
    return draft, section, index


def inputs(project):
    """写报告的输入：需求（必需）+ framework（可选）。"""
    ps = confirmed_framework(project)
    check = None
    if ps and ps.requirements_check_id:
        check = db.session.get(RequirementsCheck, ps.requirements_check_id)
    check = check or finished_requirements(project)
    return check, (ps.framework if ps else None)


@bp.route("")
@login_required
def index(project_id):
    project, tool = get_tool_project(project_id, "report")
    draft = project.report_drafts[0] if project.report_drafts else None
    check, framework = inputs(project)
    papers = project_papers(project)
    by_id = {p.id: p for p in all_papers(project)}  # 引用标记可能指向任何一条记录
    style = citation_style(project)
    rendered, refs, export = {}, [], ""
    if draft:
        numbers = rd.citation_numbers(draft.sections)
        rendered = {s.id: rd.render(s.content, by_id, style, numbers) for s in draft.sections if s.content}
        approved = [s for s in draft.sections if s.status == "approved"]
        refs = rd.references(draft.sections, by_id, style)
        export = rd.export_text(approved, by_id, style) if approved else ""
    return render_template("pages/report.html", project=project, tool=tool, draft=draft, check=check,
                           framework=framework, papers=papers, rendered=rendered, references=refs, export=export,
                           style=style, current=current_index(draft) if draft else 0,
                           stale=bool(draft and draft.content_fingerprint != project.fingerprint),
                           template_name=rd.load_template(rd.template_key(project.type))["name"])


@bp.route("/outline", methods=["POST"])
@login_required
def outline(project_id):
    """第 1 步（1 次 AI）：生成文档大纲，建立一份新的草稿。旧草稿保留在数据库里。"""
    project, _ = get_tool_project(project_id, "report")
    check, framework = inputs(project)
    if check is None:
        flash("Finish the Requirements Checklist first. The outline is built from it.", "error")
        return page(project)
    key = rd.template_key(project.type)
    try:
        result = rd.generate_outline(project, check.aspects, check.conflicts, framework, key)
    except AIServiceError as e:
        flash(e.user_message, "error")
        return page(project)
    draft = ReportDraft(project_id=project.id, template_key=key, content_fingerprint=project.fingerprint,
                        outline_json=json.dumps(result, ensure_ascii=False))
    for i, s in enumerate(result["sections"]):
        draft.sections.append(ReportSection(position=i, title=s["title"]))
    db.session.add(draft)
    db.session.commit()
    return page(project)


@bp.route("/<int:draft_id>/sections/<int:section_id>/write", methods=["POST"])
@login_required
def write(project_id, draft_id, section_id):
    """第 2 步（1 次 AI）：写当前这一节；带着学生的意见可以重写。"""
    project, _ = get_tool_project(project_id, "report")
    draft, section, index = load_section(project, draft_id, section_id)
    if section.status == "approved":
        return page(project, f"#s{section.id}")
    check, framework = inputs(project)
    if check is None:
        flash("Finish the Requirements Checklist first.", "error")
        return page(project)
    notes = request.form.get("notes", "").strip()[:1000]
    approved = [(s.title, s.content) for s in draft.sections[:index] if s.status == "approved"]
    try:
        result = rd.draft_section(project, check.aspects, check.conflicts, framework, draft.outline, index,
                                  project_papers(project), approved, notes)
    except AIServiceError as e:
        flash(e.user_message, "error")
        return page(project, f"#s{section.id}")
    section.content = result["content"]
    section.cited_paper_ids_json = json.dumps(result["cited_ids"])
    section.assumptions_json = json.dumps(result["assumptions"], ensure_ascii=False)
    section.student_notes = notes
    section.status = "draft"
    db.session.commit()
    return page(project, f"#s{section.id}")


@bp.route("/<int:draft_id>/sections/<int:section_id>/save", methods=["POST"])
@login_required
def save(project_id, draft_id, section_id):
    """学生自己修改内容。引用标记同样要核对：不属于本项目论文的 [P..] 会被去掉。"""
    project, _ = get_tool_project(project_id, "report")
    draft, section, _ = load_section(project, draft_id, section_id)
    content, cited = rd.clean_markers(request.form.get("content", "")[:20000], {p.id for p in all_papers(project)})
    if not content:
        flash("The section can't be empty.", "error")
        return page(project, f"#s{section.id}")
    section.content = content
    section.cited_paper_ids_json = json.dumps(cited)
    section.status = "draft"  # 改过的内容需要重新批准
    db.session.commit()
    flash("Section saved. Approve it when you're happy with it.", "success")
    return page(project, f"#s{section.id}")


@bp.route("/<int:draft_id>/sections/<int:section_id>/approve", methods=["POST"])
@login_required
def approve(project_id, draft_id, section_id):
    project, _ = get_tool_project(project_id, "report")
    draft, section, _ = load_section(project, draft_id, section_id)
    if section.status == "draft" and section.content:
        section.status = "approved"
        db.session.commit()
        nxt = next((s for s in draft.sections if s.status != "approved"), None)
        flash(f"“{section.title}” approved." + (f" Next: {nxt.title}." if nxt else " Every section is approved."), "success")
        return page(project, f"#s{nxt.id}" if nxt else "#export")
    return page(project, f"#s{section.id}")


@bp.route("/<int:draft_id>/sections/<int:section_id>/reopen", methods=["POST"])
@login_required
def reopen(project_id, draft_id, section_id):
    """把已批准的章节改回草稿，可以再修改。"""
    project, _ = get_tool_project(project_id, "report")
    draft, section, _ = load_section(project, draft_id, section_id, allow_locked=True)
    if section.status == "approved":
        section.status = "draft"
        db.session.commit()
    return page(project, f"#s{section.id}")
