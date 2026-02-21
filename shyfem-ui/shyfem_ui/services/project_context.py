"""Load full project context from DB for active-project state."""


from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, ProjectFile, Simulation
from shyfem_ui.services.access_control import check_project_access


def load_project_context(
    project_id: int,
    user: dict | None = None,
    session_factory=None,
) -> dict | None:
    """Load project with its grids, simulations, and files as a plain dict.

    Returns None if the project_id does not exist or if the user
    lacks at least viewer access.

    Args:
        project_id: Project database ID.
        user: User dict from get_current_user(). None skips access check (local mode).
        session_factory: Optional session factory for testing.
    """
    # Access check (skip when user is None — local mode backward compat)
    if user is not None:
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


def _load(db, project_id: int) -> dict | None:
    """Internal: load project data from an open session."""
    project = db.query(Project).filter_by(id=project_id).first()
    if project is None:
        return None
    grids = db.query(Grid).filter_by(project_id=project_id).all()
    sims = db.query(Simulation).filter_by(project_id=project_id).all()
    files = (
        db.query(ProjectFile)
        .filter_by(project_id=project_id)
        .order_by(ProjectFile.filename)
        .all()
    )
    return {
        "id": project.id,
        "name": project.name,
        "work_dir": project.work_dir,
        "description": project.description,
        "grids": [
            {"name": g.name, "grd_file": g.grd_file, "bas_file": g.bas_file}
            for g in grids
        ],
        "simulations": [
            {"name": s.name, "str_file": s.str_file}
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
