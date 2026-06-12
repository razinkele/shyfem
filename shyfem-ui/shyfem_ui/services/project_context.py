"""Load full project context from DB for active-project state."""

from typing import TypedDict

from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, ProjectFile, Simulation
from shyfem_ui.services.access_control import check_project_access


class GridEntry(TypedDict):
    name: str
    grd_file: str | None
    bas_file: str | None
    num_layers: int | None
    min_depth: float | None
    max_depth: float | None


class SimulationEntry(TypedDict):
    name: str
    str_file: str | None
    start_time: str | None
    end_time: str | None
    time_step: float | None


class FileEntry(TypedDict):
    id: int
    filename: str
    rel_path: str
    file_type: str
    size_bytes: int


class ProjectContext(TypedDict):
    id: int
    name: str
    work_dir: str
    description: str | None
    grids: list[GridEntry]
    simulations: list[SimulationEntry]
    files: list[FileEntry]


def load_project_context(
    project_id: int,
    user: dict | None = None,
    session_factory=None,
    is_server_mode: bool | None = None,
) -> ProjectContext | None:
    """Load project with its grids, simulations, and files as a plain dict.

    Returns None if the project_id does not exist or if the user
    lacks at least viewer access.

    Access check is fail-CLOSED in server mode: an unresolved identity
    (``user is None``) is denied, because behind the Shiny Server proxy the WS
    is admitted with ``user=None`` and skipping the check would let any client
    open/export/clone arbitrary projects by id. Local desktop mode has no auth,
    so ``user`` is legitimately None and the check is skipped (backward compat).

    Args:
        project_id: Project database ID.
        user: User dict from get_current_user() / the WS-resolved identity.
        session_factory: Optional session factory for testing.
        is_server_mode: Whether the app runs in multi-user server mode. When
            None, resolved from the global config's ``deployment_mode``.
    """
    if is_server_mode is None:
        from shyfem_ui.config import get_config

        is_server_mode = get_config().deployment_mode == "server"

    if user is None:
        # Fail closed in server mode; local mode skips the check (no auth).
        if is_server_mode:
            return None
    else:
        role = check_project_access(
            project_id, user, min_role="viewer", session_factory=session_factory
        )
        if role is None:
            return None

    if session_factory:
        db = session_factory()
        try:
            return _load(db, project_id)
        finally:
            db.close()
    else:
        with db_session() as db:
            return _load(db, project_id)


def _load(db, project_id: int) -> ProjectContext | None:
    """Internal: load project data from an open session."""
    project = db.query(Project).filter_by(id=project_id).first()
    if project is None:
        return None
    grids = db.query(Grid).filter_by(project_id=project_id).all()
    sims = db.query(Simulation).filter_by(project_id=project_id).all()
    files = (
        db.query(ProjectFile).filter_by(project_id=project_id).order_by(ProjectFile.filename).all()
    )
    return {
        "id": project.id,
        "name": project.name,
        "work_dir": project.work_dir,
        "description": project.description,
        "grids": [
            {
                "name": g.name,
                "grd_file": g.grd_file,
                "bas_file": g.bas_file,
                "num_layers": g.num_layers,
                "min_depth": g.min_depth,
                "max_depth": g.max_depth,
            }
            for g in grids
        ],
        "simulations": [
            {
                "name": s.name,
                "str_file": s.str_file,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "time_step": s.time_step,
            }
            for s in sims
        ],
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "rel_path": f.rel_path,
                "file_type": f.file_type,
                "size_bytes": f.size_bytes,
            }
            for f in files
        ],
    }
