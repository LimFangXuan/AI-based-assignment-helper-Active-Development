"""Paper Finder：固定流程的 RAG 流水线（AI 生成检索词 → OpenAlex → AI 只能从候选中挑选 → 代码校验 ID → 存库）。

是否显示由学生选的项目类型决定（tools_registry 的 hidden_for_types），不再由 AI 判断。
输入是最新一次已结束的 Requirements Checklist，以及（如果有）已确认的 framework（spec §7.4）。
"""
import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Paper, PaperSearch
from ...security import login_required
from ...services import openalex_client, paper_finder
from ...services.requirements_checker import context_block
from ...services.ai_client import AIServiceError
from . import confirmed_framework, finished_requirements, get_tool_project

bp = Blueprint("papers", __name__, url_prefix="/projects/<int:project_id>/tools/papers")

NEEDS_REQUIREMENTS_HINT = "Finish the Requirements Checklist first, so the search knows what your topic is."


@bp.route("")
@login_required
def index(project_id):
    project, tool = get_tool_project(project_id, "papers")
    hint = None if finished_requirements(project) else NEEDS_REQUIREMENTS_HINT
    return render_template("pages/papers.html", project=project, tool=tool, hint=hint,
                           has_framework=confirmed_framework(project) is not None,
                           min_papers=paper_finder.MIN_PAPERS, max_papers=paper_finder.MAX_PAPERS)


@bp.route("/new", methods=["POST"])
@login_required
def new(project_id):
    project, _ = get_tool_project(project_id, "papers")
    check = finished_requirements(project)
    if check is None:
        flash(NEEDS_REQUIREMENTS_HINT, "error")
        return redirect(url_for("papers.index", project_id=project.id))
    ps = confirmed_framework(project)
    context = paper_finder.search_context(context_block(check.aspects, check.conflicts), ps.framework if ps else None)

    try:
        count = int(request.form.get("count", 5))
    except ValueError:
        count = 5
    count = max(paper_finder.MIN_PAPERS, min(paper_finder.MAX_PAPERS, count))
    oa_only = request.form.get("oa_only") == "1"
    target = min(30, max(15, count * 3))  # 候选数量：约为要推荐篇数的 3 倍，15 到 30 篇

    try:
        queries = paper_finder.paper_queries(project, context)           # 1. AI：生成检索词
        per_query = min(25, -(-target // len(queries)))                       # 向上取整
        found = {}
        for query in queries:                                                 # 2. 代码：检索并去重
            for work in openalex_client.search_works(query, per_page=per_query, oa_only=oa_only):
                found.setdefault(work["openalex_id"], work)
        candidates = list(found.values())[:target]
        if not candidates:
            flash("No papers found. Untick “Open access only”, or add more detail about the topic "
                  "and run the Requirements Checklist again.", "error")
            return redirect(url_for("papers.index", project_id=project.id))
        selected = paper_finder.select_papers(project, context, candidates, count)  # 3. AI 挑选 + 代码校验
    except (AIServiceError, openalex_client.OpenAlexError) as e:
        flash(e.user_message, "error")  # 任何一步失败：只提示，不写入数据库
        return redirect(url_for("papers.index", project_id=project.id))

    by_id = {c["openalex_id"]: c for c in candidates}
    search = PaperSearch(project_id=project.id, session_id=ps.id if ps else None, requested_count=count, oa_only=oa_only,
                         queries_json=json.dumps(queries, ensure_ascii=False), candidate_count=len(candidates))
    for item in selected:
        c = by_id[item["openalex_id"]]
        search.papers.append(Paper(
            openalex_id=c["openalex_id"], title=c["title"], authors=c["authors"],
            author_list_json=json.dumps(c["author_list"], ensure_ascii=False),
            year=c["year"], venue=c["venue"], doi=c["doi"], url=c["url"], oa_url=c["oa_url"],
            is_oa=c["is_oa"], cited_by_count=c["cited_by_count"], work_type=c["work_type"],
            volume=c["volume"], issue=c["issue"], pages=c["pages"],
            abstract_snippet=(c["abstract"] or "")[:600],
            reason=item["reason"], relevance=item["relevance"], rank=item["rank"],
        ))
    db.session.add(search)
    db.session.commit()  # 4. 全部成功才一次性写入
    if len(selected) < count:
        flash(f"You asked for {count} papers; the AI found only {len(selected)} relevant enough "
              "(no padding with weak matches).", "success")
    return redirect(url_for("papers.index", project_id=project.id))


@bp.route("/<int:paper_id>")
@login_required
def detail(project_id, paper_id):
    project, tool = get_tool_project(project_id, "papers")
    paper = db.session.get(Paper, paper_id)
    if paper is None or paper.search.project_id != project.id:
        abort(404)
    return render_template("pages/paper_detail.html", project=project, tool=tool, paper=paper)
