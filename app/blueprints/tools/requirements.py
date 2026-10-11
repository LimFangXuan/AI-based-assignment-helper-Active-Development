"""Requirements Checklist（阶段 5 实现，现在是占位页）。"""
from flask import Blueprint

from ...security import login_required
from . import placeholder

bp = Blueprint("requirements", __name__, url_prefix="/projects/<int:project_id>/tools/requirements")


@bp.route("")
@login_required
def index(project_id):
    return placeholder(project_id, "requirements")
