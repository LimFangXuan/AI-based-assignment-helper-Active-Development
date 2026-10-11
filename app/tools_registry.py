"""项目页上的工具卡片。顺序就是依赖链：后面的工具读取前面工具确认过的结果。

加一个工具 = 在这里加一项 + 写它的 blueprint。endpoint 是工具首页的路由名。
implemented=False 的工具显示为灰色并带 “Soon” 标签，链接到共用的占位页。
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tool:
    slug: str
    name: str
    description: str
    icon: str                    # Phosphor 图标名
    endpoint: str
    implemented: bool
    hidden_for_types: frozenset = field(default_factory=frozenset)


TOOLS = [
    Tool("requirements", "Requirements Checklist",
         "Answer questions until every aspect of your task is clear.",
         "ph-list-checks", "requirements.index", implemented=True),
    Tool("prompt", "Prompt Generator",
         "Turn your confirmed requirements into a full project framework and a ready-to-use AI prompt.",
         "ph-chat-centered-text", "prompt.index", implemented=True),
    Tool("planner", "Task Planner",
         "Break your framework into daily tasks that fit before the deadline.",
         "ph-calendar-check", "planner.index", implemented=True),
    Tool("papers", "Paper Finder",
         "Find real academic papers for your topic, with a reason for each pick.",
         "ph-books", "papers.index", implemented=True,
         hidden_for_types=frozenset({"portfolio", "exam_preparation"})),
    Tool("report", "Report Drafter",
         "Build a draft section by section from your framework and chosen papers.",
         "ph-file-text", "report.index", implemented=True,
         hidden_for_types=frozenset({"portfolio", "exam_preparation"})),
]
TOOLS_BY_SLUG = {t.slug: t for t in TOOLS}


def tools_for(project):
    """这个项目类型能用的工具（按依赖顺序）。"""
    return [t for t in TOOLS if project.type not in t.hidden_for_types]


def is_visible(slug, project):
    return project.type not in TOOLS_BY_SLUG[slug].hidden_for_types
