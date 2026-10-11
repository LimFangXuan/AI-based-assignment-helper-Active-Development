"""所有可以调整的常量都放在这里：状态、类型、长度限制、阈值。改一个地方，全站生效。"""

# ---------- 项目状态：数据库里存英文 slug，页面显示 label ----------
STATUS_LABELS = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "done": "Ready to submit",
    "submitted": "Submitted",
}
EDITABLE_STATUSES = ("not_started", "in_progress", "done")  # “submitted”只能通过 Submit 按钮进入
ACTIVE_STATUSES = EDITABLE_STATUSES

# ---------- 项目类型（学生自己选，不再由 AI 判断） ----------
TYPE_GROUPS = [
    ("Writing", [
        ("essay", "Essay"),
        ("report", "Report"),
        ("literature_review", "Literature review"),
        ("case_study", "Case study"),
        ("reflective_writing", "Reflective writing"),
        ("research_proposal", "Research proposal"),
        ("thesis", "Thesis / FYP"),
        ("lab_report", "Lab report"),
    ]),
    ("Technical", [
        ("software_development", "Software development"),
        ("data_analysis_ml", "Data analysis / ML"),
        ("system_database_design", "System / database design"),
        ("testing_qa", "Testing / QA"),
    ]),
    ("Other", [
        ("presentation", "Presentation"),
        ("poster", "Poster"),
        ("portfolio", "Portfolio"),
        ("exam_preparation", "Exam preparation"),
        ("other", "Other"),
    ]),
]
TYPE_LABELS = {slug: label for _, items in TYPE_GROUPS for slug, label in items}
DEFAULT_TYPE = "other"

WORK_MODES = {"individual": "Individual", "group": "Group"}
DEFAULT_WORK_MODE = "individual"

CITATION_STYLES = {
    "apa7": "APA 7th",
    "harvard": "Harvard",
    "ieee": "IEEE",
    "mla": "MLA",
    "chicago": "Chicago",
    "follow_guideline": "Follow the guideline",
    "not_required": "Not required",
}

# ---------- 账号 ----------
USERNAME_RANGE = (3, 80)
PASSWORD_MIN_CHARS = 8
EMAIL_MAX_CHARS = 254
LOGIN_MAX_FAILURES = 5        # 同一个用户名 + 地址，10 分钟内最多失败几次
LOGIN_WINDOW_SECONDS = 600

# ---------- 长度限制 ----------
NAME_MAX_CHARS = 120
# 暂定值：Gemini 免费额度的单次请求上限远大于这个数，但正式确定前还要实测（见 spec §4.2）
DESCRIPTION_MAX_CHARS = 20000
GUIDELINE_MAX_CHARS = 8000
TASK_TITLE_MAX_CHARS = 200
TASK_MINUTES_RANGE = (5, 600)

# ---------- 阈值 ----------
DUE_SOON_DAYS = 3          # 侧栏 Overview 徽章：逾期或 3 天内到期、且还没“Ready to submit”的项目
SIDEBAR_PROJECT_LIMIT = 8  # 侧栏最多列出几个项目
UPCOMING_DAYS = 6          # “Next 6 days”页面的天数
CALENDAR_CELL_LIMIT = 2    # 日历每格最多显示几项，其余折叠成 “+N more”

# ---------- AI ----------
# 描述 + guideline 一次最多发给 AI 的字符数。超过就提示学生精简，而不是让请求失败（spec §4.2）
MAX_AI_INPUT_CHARS = 26000

# 学生选的类型 → 用哪一份问题库 / 成功做法（app/skills/prompt_generator/ 下的文件名）。
# 没列出的类型（包括 other）用通用的 general
TYPE_KNOWLEDGE = {
    "essay": "report", "report": "report", "literature_review": "research", "case_study": "report",
    "reflective_writing": "report", "research_proposal": "research", "thesis": "research", "lab_report": "report",
    "software_development": "programming", "data_analysis_ml": "data_ml",
    "system_database_design": "programming", "testing_qa": "programming",
    "presentation": "presentation", "poster": "presentation", "portfolio": "design",
    "exam_preparation": "learning",
}
