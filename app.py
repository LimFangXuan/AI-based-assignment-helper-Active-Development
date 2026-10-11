import hmac
import json
import os
import secrets
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

import openalex_client
import prompt_builder
from ai_client import AIServiceError

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
# DATABASE_URL 默认指向本地 SQLite 文件；测试时可以换成临时数据库
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///app.db")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

if not app.config["SECRET_KEY"]:
    raise RuntimeError("没有找到 SECRET_KEY，请检查 .env 文件")

db = SQLAlchemy(app)

# 状态：数据库里存英文，页面上显示中文。"submitted" 表示已提交（软删除：数据还在，只是不再显示）
STATUS_LABELS = {
    "not_started": "未开始",
    "in_progress": "进行中",
    "done": "已完成（未提交）",
    "submitted": "已提交",
}
EDITABLE_STATUSES = ("not_started", "in_progress", "done")


# ======================= 数据库模型 =======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    deadline = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="not_started")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    prompt_sessions = db.relationship(
        "PromptSession",
        backref="project",
        cascade="all, delete-orphan",
        order_by="PromptSession.created_at.desc()",
    )
    paper_searches = db.relationship(
        "PaperSearch",
        backref="project",
        cascade="all, delete-orphan",
        order_by="PaperSearch.created_at.desc()",
    )


class PromptSession(db.Model):
    """一次"生成 prompt"的完整记录：AI 提的问题 → 学生的回答 → 摘要 → 最终 prompt。"""

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    diagnosis_json = db.Column(db.Text)
    questions_json = db.Column(db.Text, nullable=False)
    answers_json = db.Column(db.Text)
    summary_json = db.Column(db.Text)
    final_prompt = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    @property
    def questions(self):
        return json.loads(self.questions_json)

    @property
    def summary(self):
        return json.loads(self.summary_json) if self.summary_json else None

    @property
    def answers(self):
        return json.loads(self.answers_json) if self.answers_json else []

    @property
    def diagnosis(self):
        return json.loads(self.diagnosis_json) if self.diagnosis_json else None

    @property
    def blocked(self):
        return prompt_builder.is_blocked(self.summary)


class PaperSearch(db.Model):
    """一次论文检索：记录检索词、候选数量和依据的摘要，让每篇推荐都能追溯来源。"""

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("prompt_session.id"))  # 检索依据的那次已确认摘要
    queries_json = db.Column(db.Text, nullable=False)
    requested_count = db.Column(db.Integer, nullable=False, default=5)
    oa_only = db.Column(db.Boolean, nullable=False, default=True)
    candidate_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    papers = db.relationship("Paper", backref="search", cascade="all, delete-orphan", order_by="Paper.rank")

    @property
    def queries(self):
        return json.loads(self.queries_json)


class Paper(db.Model):
    """AI 从候选中选出的一篇论文。除了 reason 和 relevance，所有字段都来自 OpenAlex。"""

    id = db.Column(db.Integer, primary_key=True)
    search_id = db.Column(db.Integer, db.ForeignKey("paper_search.id"), nullable=False)
    openalex_id = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    authors = db.Column(db.String(500), nullable=False, default="")
    author_list_json = db.Column(db.Text, nullable=False, default="[]")
    year = db.Column(db.Integer)
    venue = db.Column(db.String(300))
    doi = db.Column(db.String(200))
    url = db.Column(db.String(500))       # 只允许 http/https，在 openalex_client 里检查过
    oa_url = db.Column(db.String(500))
    is_oa = db.Column(db.Boolean, nullable=False, default=False)
    cited_by_count = db.Column(db.Integer, nullable=False, default=0)
    work_type = db.Column(db.String(40))
    volume = db.Column(db.String(20))
    issue = db.Column(db.String(20))
    pages = db.Column(db.String(40))
    abstract_snippet = db.Column(db.Text, nullable=False, default="")
    reason = db.Column(db.Text, nullable=False)  # AI 的推荐理由（只依据标题和摘要）
    relevance = db.Column(db.Integer)            # AI 给的相关度 1-10，仅供个人筛选
    rank = db.Column(db.Integer, nullable=False)

    @property
    def author_list(self):
        return json.loads(self.author_list_json or "[]")

    @property
    def citation(self):
        return prompt_builder.format_citation(self)


def _add_column_if_missing(table, column, ddl):
    """表里没有这一列就补上，返回是否新加。table / column 只能是代码里的常量，绝不能来自用户输入。"""
    columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
    if column in columns:
        return False
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    return True


def ensure_schema():
    """db.create_all() 不会给已有的表加新列，这里手动补上，旧数据库也能升级。"""
    db.create_all()  # 新表（paper_search、paper）会在这里自动创建
    _add_column_if_missing("prompt_session", "diagnosis_json", "TEXT")
    db.session.commit()


# ======================= 通用工具 =======================
def login_required(view):
    """需要登录的页面都套上这个装饰器，不用每个函数重复写检查。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id is not None else None
        if user is None:
            session.clear()  # session 里的用户已不存在（比如数据库被重建）
            return redirect(url_for("login"))
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def get_own_project(project_id):
    """取项目；不存在或不属于当前用户都返回 404，不暴露别人的项目是否存在。"""
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != g.user.id:
        abort(404)
    return project


def get_own_prompt_session(project, session_id):
    ps = db.session.get(PromptSession, session_id)
    if ps is None or ps.project_id != project.id:
        abort(404)
    return ps


def parse_deadline(raw):
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


# ---- CSRF 防护：所有 POST 表单必须带上服务器发的随机令牌 ----
def get_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = get_csrf_token


@app.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf_token", "").encode()
        expected = session.get("_csrf_token", "").encode()
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, "表单已过期，请刷新页面后重试。")


@app.context_processor
def inject_globals():
    return {"now": datetime.now(), "STATUS_LABELS": STATUS_LABELS}


# ======================= 账号：注册 / 登录 / 登出 =======================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        error = None
        if not 3 <= len(username) <= 80:
            error = "用户名长度需要在 3 到 80 个字符之间"
        elif len(password) < 6:
            error = "密码至少需要 6 个字符"
        elif User.query.filter_by(username=username).first():
            error = "用户名已被使用"

        if error is None:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:  # 两个人同时注册同名时，数据库的 unique 兜底
                db.session.rollback()
                error = "用户名已被使用"

        if error:
            return render_template("register.html", error=error, username=username)

        session.clear()
        session["user_id"] = user.id
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        # 用户名不存在和密码错误提示同一句，避免被人用来试探哪些用户名已注册
        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="用户名或密码错误", username=username)

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ======================= Dashboard / 项目 =======================
@app.route("/")
@login_required
def dashboard():
    projects = (
        Project.query.filter(Project.user_id == g.user.id, Project.status != "submitted")
        .order_by(Project.deadline.asc())
        .all()
    )
    return render_template("dashboard.html", projects=projects)


@app.route("/projects/new", methods=["GET", "POST"])
@login_required
def new_project():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        deadline = parse_deadline(request.form.get("deadline", ""))

        error = None
        if not 1 <= len(name) <= 120:
            error = "项目名称需要在 1 到 120 个字符之间"
        elif deadline is None:
            error = "请选择有效的截止日期和时间"
        elif len(description) > 5000:
            error = "描述最多 5000 个字符"

        if error:
            return render_template("new_project.html", error=error, name=name,
                                   description=description, deadline=request.form.get("deadline", ""))

        project = Project(user_id=g.user.id, name=name, description=description, deadline=deadline)
        db.session.add(project)
        db.session.commit()
        flash("项目已创建", "success")
        return redirect(url_for("project_detail", project_id=project.id))

    return render_template("new_project.html")


@app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    """修改项目资料：例如补充老师的书面许可，或改变方向后重新生成 prompt。"""
    project = get_own_project(project_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        deadline = parse_deadline(request.form.get("deadline", ""))

        error = None
        if not 1 <= len(name) <= 120:
            error = "项目名称需要在 1 到 120 个字符之间"
        elif deadline is None:
            error = "请选择有效的截止日期和时间"
        elif len(description) > 5000:
            error = "描述最多 5000 个字符"

        if error:
            return render_template("new_project.html", error=error, editing=project, name=name,
                                   description=description, deadline=request.form.get("deadline", ""))

        project.name, project.description, project.deadline = name, description, deadline
        db.session.commit()
        flash("项目已更新", "success")
        return redirect(url_for("project_detail", project_id=project.id))

    return render_template("new_project.html", editing=project, name=project.name,
                           description=project.description,
                           deadline=project.deadline.strftime("%Y-%m-%dT%H:%M"))


@app.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = get_own_project(project_id)
    paper_ps, paper_hint = paper_module_status(project)
    return render_template("project.html", project=project, editable=EDITABLE_STATUSES,
                           paper_ps=paper_ps, paper_hint=paper_hint)


@app.route("/projects/<int:project_id>/status", methods=["POST"])
@login_required
def update_status(project_id):
    project = get_own_project(project_id)
    status = request.form.get("status", "")
    if status not in EDITABLE_STATUSES:  # 不允许通过这个入口直接改成 submitted
        abort(400)
    project.status = status
    db.session.commit()
    flash("状态已更新", "success")
    return redirect(url_for("project_detail", project_id=project.id))


@app.route("/projects/<int:project_id>/submit", methods=["POST"])
@login_required
def submit_project(project_id):
    """软删除：只把状态改成 submitted，数据保留，Dashboard 不再显示。"""
    project = get_own_project(project_id)
    project.status = "submitted"
    db.session.commit()
    flash(f"「{project.name}」已标记为提交", "success")
    return redirect(url_for("dashboard"))


@app.route("/submitted")
@login_required
def submitted():
    projects = (
        Project.query.filter(Project.user_id == g.user.id, Project.status == "submitted")
        .order_by(Project.deadline.desc())
        .all()
    )
    return render_template("submitted.html", projects=projects)


# ======================= Prompt 生成模块 =======================
@app.route("/projects/<int:project_id>/prompt/new", methods=["POST"])
@login_required
def prompt_new(project_id):
    project = get_own_project(project_id)
    if not project.description:
        flash("请先在项目里补充描述，AI 才知道要问什么", "error")
        return redirect(url_for("project_detail", project_id=project.id))

    try:
        diagnosis = prompt_builder.diagnose(project)                      # 阶段1：诊断
        questions = prompt_builder.generate_questions(project, diagnosis)  # 阶段2：提问
    except AIServiceError as e:
        flash(e.user_message, "error")  # 503 等失败：只提示，不崩溃，也不留下半成品
        return redirect(url_for("project_detail", project_id=project.id))

    ps = PromptSession(
        project_id=project.id,
        diagnosis_json=json.dumps(diagnosis, ensure_ascii=False),
        questions_json=json.dumps(questions, ensure_ascii=False),
    )
    db.session.add(ps)
    db.session.commit()
    return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))


@app.route("/projects/<int:project_id>/prompt/<int:session_id>")
@login_required
def prompt_view(project_id, session_id):
    """根据这次记录走到哪一步，显示对应的页面：提问 → 确认（或被冲突拦截）→ 结果。"""
    project = get_own_project(project_id)
    ps = get_own_prompt_session(project, session_id)
    if ps.final_prompt:
        return render_template("prompt_result.html", project=project, ps=ps)
    if request.args.get("retry"):  # 学生想重新回答这组问题
        return render_template("prompt_questions.html", project=project, ps=ps)
    if ps.summary:
        template = "prompt_blocked.html" if ps.blocked else "prompt_confirm.html"
        return render_template(template, project=project, ps=ps)
    return render_template("prompt_questions.html", project=project, ps=ps)


@app.route("/projects/<int:project_id>/prompt/<int:session_id>/answers", methods=["POST"])
@login_required
def prompt_answers(project_id, session_id):
    project = get_own_project(project_id)
    ps = get_own_prompt_session(project, session_id)
    if ps.final_prompt:  # 已经生成过的记录不再覆盖
        return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))
    qa = prompt_builder.collect_answers(ps.questions, request.form)
    diagnosis = ps.diagnosis or prompt_builder.empty_diagnosis()

    try:
        summary = prompt_builder.generate_summary(project, diagnosis, qa)
    except AIServiceError as e:
        flash(e.user_message, "error")  # 回答不会丢：回到问题页，学生可以直接再点一次
        return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))

    ps.answers_json = json.dumps(qa, ensure_ascii=False)
    ps.summary_json = json.dumps(summary, ensure_ascii=False)
    ps.final_prompt = None  # 先让学生在确认页检查，确认后才生成 prompt
    db.session.commit()
    return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))


@app.route("/projects/<int:project_id>/prompt/<int:session_id>/revise", methods=["POST"])
@login_required
def prompt_revise(project_id, session_id):
    """学生看过摘要后提出修改意见：把意见加进问答记录，重新整理一次摘要。"""
    project = get_own_project(project_id)
    ps = get_own_prompt_session(project, session_id)
    if ps.final_prompt or not ps.summary:
        return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))
    notes = request.form.get("notes", "").strip()
    if not notes:
        flash("请先写下需要修改或补充的地方", "error")
        return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))

    qa = prompt_builder.add_revision(ps.answers, notes)
    diagnosis = ps.diagnosis or prompt_builder.empty_diagnosis()
    try:
        summary = prompt_builder.generate_summary(project, diagnosis, qa)
    except AIServiceError as e:
        flash(e.user_message, "error")  # 失败时保留上一版摘要，学生的意见还在输入框里可以重试
        return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))

    ps.answers_json = json.dumps(qa, ensure_ascii=False)
    ps.summary_json = json.dumps(summary, ensure_ascii=False)
    db.session.commit()
    flash("已根据你的意见更新摘要，请再检查一遍", "success")
    return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))


@app.route("/projects/<int:project_id>/prompt/<int:session_id>/confirm", methods=["POST"])
@login_required
def prompt_confirm(project_id, session_id):
    """学生确认摘要后生成最终 prompt。这一步只是用模板拼接，不调用 AI。"""
    project = get_own_project(project_id)
    ps = get_own_prompt_session(project, session_id)
    if ps.final_prompt or not ps.summary or ps.blocked:  # 已生成 / 还没摘要 / 冲突未解决
        return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))
    diagnosis = ps.diagnosis or prompt_builder.empty_diagnosis()
    ps.final_prompt = prompt_builder.build_final_prompt(project, ps.answers, ps.summary, diagnosis)
    db.session.commit()
    return redirect(url_for("prompt_view", project_id=project.id, session_id=ps.id))


# ======================= 论文推荐 =======================
def latest_confirmed_session(project):
    """论文检索的依据：最近一次已确认（已生成 prompt）的摘要。prompt_sessions 已按时间倒序。"""
    for ps in project.prompt_sessions:
        if ps.final_prompt and ps.summary:
            return ps
    return None


def paper_module_status(project):
    """返回 (依据的 session, 提示文字)。两者都是 None，表示这类项目不显示论文模块。"""
    ps = latest_confirmed_session(project)
    if ps is None:
        return None, "先完成一次 Prompt 生成并确认，系统才知道项目类型和要检索什么。"
    if ps.summary["project_type"] not in prompt_builder.PAPER_TYPES:
        return None, None
    return ps, None


def get_own_paper(project, paper_id):
    paper = db.session.get(Paper, paper_id)
    if paper is None or paper.search.project_id != project.id:
        abort(404)
    return paper


@app.route("/projects/<int:project_id>/papers")
@login_required
def papers(project_id):
    project = get_own_project(project_id)
    ps, hint = paper_module_status(project)
    if ps is None and hint is None:
        abort(404)  # 面试准备、技能学习等类型没有论文模块
    return render_template("papers.html", project=project, hint=hint,
                           min_papers=prompt_builder.MIN_PAPERS, max_papers=prompt_builder.MAX_PAPERS)


@app.route("/projects/<int:project_id>/papers/new", methods=["POST"])
@login_required
def papers_new(project_id):
    project = get_own_project(project_id)
    ps, hint = paper_module_status(project)
    if ps is None:
        if hint is None:
            abort(404)
        flash(hint, "error")
        return redirect(url_for("papers", project_id=project.id))

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
            flash("没有检索到相关论文。可以补充项目描述后重新确认摘要，或取消“只要开放获取”再试。", "error")
            return redirect(url_for("papers", project_id=project.id))
        selected = prompt_builder.select_papers(project, ps.summary, candidates, count)  # 3. AI 挑选 + 代码校验
    except (AIServiceError, openalex_client.OpenAlexError) as e:
        flash(e.user_message, "error")  # 任何一步失败：只提示，不写入数据库
        return redirect(url_for("papers", project_id=project.id))

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
        flash(f"你要了 {count} 篇，AI 只找到 {len(selected)} 篇足够相关的（宁缺毋滥）。", "success")
    return redirect(url_for("papers", project_id=project.id))


@app.route("/projects/<int:project_id>/papers/<int:paper_id>")
@login_required
def paper_detail(project_id, paper_id):
    project = get_own_project(project_id)
    paper = get_own_paper(project, paper_id)
    return render_template("paper_detail.html", project=project, paper=paper)


# 导入时就建表：无论用 python app.py、flask run 还是 gunicorn 启动，数据库都已经准备好
with app.app_context():
    ensure_schema()  # 建新表 + 给旧表补新列，已有数据不会动

if __name__ == "__main__":
    # 调试模式会开启 Werkzeug 调试器（可以在网页上执行代码），只能在本机开发时打开
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
