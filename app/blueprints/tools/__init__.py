"""项目工具。每个工具一个 blueprint，URL 都在 /projects/<id>/tools/<slug> 下面。"""
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
