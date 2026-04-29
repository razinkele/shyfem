"""SQLAlchemy database models for SHYFEM UI.

Models:
    Project: A named project with work directory, containing grids and simulations.
    Grid: A computational grid (.grd/.bas files) with node/element statistics.
    Simulation: A simulation configuration (.str file) with MPI settings.
    Job: A tracked execution of a SHYFEM tool with status, progress, and output.
    ProjectFile: A file tracked within a project.
    User: A registered user with role-based access.
    AuthSession: An authenticated session tied to a user.
    ProjectPermission: Permission granting a user access to a project.
    Workflow: A persisted multi-step workflow instance.
    WorkflowStatus: Enum for workflow execution status.
"""

from shyfem_ui.models.project import Grid, Job, Project, ProjectFile, Simulation
from shyfem_ui.models.user import AuthSession, ProjectPermission, User
from shyfem_ui.models.workflow import Workflow, WorkflowStatus

__all__ = [
    "Project",
    "Grid",
    "Simulation",
    "Job",
    "ProjectFile",
    "User",
    "AuthSession",
    "ProjectPermission",
    "Workflow",
    "WorkflowStatus",
]
