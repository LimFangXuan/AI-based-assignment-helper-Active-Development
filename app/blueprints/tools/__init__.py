"""项目工具。每个工具一个 blueprint，URL 都在 /projects/<id>/tools/<slug> 下面。

这里放各工具共用的查询：依赖链上“前一个工具确认过的结果”。
"""
from flask import abort, render_template

from ...security import get_own_project
from ...tools_registry import TOOLS_BY_SLUG, is_visible


def get_tool_project(project_id, slug):
    """取项目并确认这个工具对该项目类型可见；不可见就 404（例如 Portfolio 没有 Paper Finder）。"""
    project = get_own_project(project_id)
    if not is_visible(slug, project):
        abort(404)
    return project, TOOLS_BY_SLUG[slug]


def placeholder(project_id, slug):
    """还没做好的工具共用这一个占位页。"""
    project, tool = get_tool_project(project_id, slug)
    return render_template("pages/tool_placeholder.html", project=project, tool=tool)


def finished_requirements(project):
    """最新一次已结束的 Requirements Checklist（下游工具的输入）。最新一次还在进行中时返回 None。"""
    checks = project.requirements_checks
    return checks[0] if checks and checks[0].finished else None


def framework_sessions(project):
    """新流程的 Prompt Generator 记录（有 framework 的）。旧流程的记录保留在数据库里，但不显示（spec §4.5）。"""
    return [ps for ps in project.prompt_sessions if ps.framework_json]


def confirmed_framework(project):
    """最近一次已确认（已生成 prompt）的 framework 记录。"""
    return next((ps for ps in framework_sessions(project) if ps.final_prompt), None)
