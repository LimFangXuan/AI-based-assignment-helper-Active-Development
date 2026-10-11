"""Paper Finder：固定流程的 RAG 流水线（AI 生成检索词 → OpenAlex → AI 只能从候选中挑选 → 代码校验 ID → 存库）。

是否显示由学生选的项目类型决定（tools_registry 的 hidden_for_types），不再由 AI 判断。
现在的输入仍是旧 Prompt Generator 的已确认摘要；阶段 5 会改成 Requirements / framework。
"""
import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Paper, PaperSearch
from ...security import login_required
from ...services import openalex_client, prompt_builder
from ...services.ai_client import AIServiceError
from . import get_tool_project

bp = Blueprint("papers", __name__, url_prefix="/projects/<int:project_id>/tools/papers")

NEEDS_PROMPT_HINT = "Finish and confirm the Prompt Generator first, so the search knows what to look for."


def latest_confirmed_session(project):
    """检索依据：最近一次已确认（已生成 prompt）的摘要。prompt_sessions 已按时间倒序。"""
    return next((ps for ps in project.prompt_sessions if ps.final_prompt and ps.summary), None)


@bp.route("")
@login_required
def index(project_id):
    project, tool = get_tool_project(project_id, "papers")
    hint = None if latest_confirmed_session(project) else NEEDS_PROMPT_HINT
    return render_template("pages/papers.html", project=project, tool=tool, hint=hint,
                           min_papers=prompt_builder.MIN_PAPERS, max_papers=prompt_builder.MAX_PAPERS)


@bp.route("/new", methods=["POST"])
@login_required
def new(project_id):
    project, _ = get_tool_project(project_id, "papers")
    ps = latest_confirmed_session(project)
    if ps is None:
        flash(NEEDS_PROMPT_HINT, "error")
        return redirect(url_for("papers.index", project_id=project.id))

    try:
        count = int(request.form.get("count", 5))
    except ValueError:
        count = 5
    count = max(prompt_builder.MIN_PAPERS, min(prompt_builder.MAX_PAPERS, count))
    oa_only = request.form.get("oa_only") == "1"
    target = min(30, max(15, count * 3))  # 候选数量：约为要推荐篇数的 3 倍，15 到 30 篇

    try:
        queries = prompt_builder.paper_queries(project, ps.summary)           # 1. AI：生成检索词
        per_query = min(25, -(-target // len(queries)))                       # 向上取整
        found = {}
        for query in queries:                                                 # 2. 代码：检索并去重
            for work in openalex_client.search_works(query, per_page=per_query, oa_only=oa_only):
                found.setdefault(work["openalex_id"], work)
        candidates = list(found.values())[:target]
        if not candidates:
            flash("No papers found. Add more detail to the project and confirm a new prompt, "
                  "or untick “Open access only” and try again.", "error")
            return redirect(url_for("papers.index", project_id=project.id))
        selected = prompt_builder.select_papers(project, ps.summary, candidates, count)  # 3. AI 挑选 + 代码校验
    except (AIServiceError, openalex_client.OpenAlexError) as e:
        flash(e.user_message, "error")  # 任何一步失败：只提示，不写入数据库
        return redirect(url_for("papers.index", project_id=project.id))

    by_id = {c["openalex_id"]: c for c in candidates}
    search = PaperSearch(project_id=project.id, session_id=ps.id, requested_count=count, oa_only=oa_only,
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
