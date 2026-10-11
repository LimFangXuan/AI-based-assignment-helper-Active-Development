"""所有数据表。在这里统一导入，db.create_all() 才能看到全部模型。"""
from .paper import Paper, PaperSearch
from .plan import Task
from .project import Project
from .prompt import PromptSession
from .report import ReportDraft, ReportSection
from .requirements import RequirementsCheck
from .user import User

__all__ = ["Paper", "PaperSearch", "Project", "PromptSession", "ReportDraft", "ReportSection",
           "RequirementsCheck", "Task", "User"]
