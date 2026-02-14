"""Load full project context from DB for active-project state."""

from typing import Optional

from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, Simulation


def load_project_context(project_id: int) -> Optional[dict]:
    """Load project with its grids and simulations as a plain dict.

    Returns None if the project_id does not exist.
    """
    with db_session() as db:
        project = db.query(Project).filter_by(id=project_id).first()
        if project is None:
            return None
        grids = db.query(Grid).filter_by(project_id=project_id).all()
        sims = db.query(Simulation).filter_by(project_id=project_id).all()
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
        }
