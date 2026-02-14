"""Unit tests for load_project_context."""

import pytest


# Point at a temp SQLite DB before importing anything that calls get_config
@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path))
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))

    # Force re-init of config and DB singletons
    import shyfem_ui.config as cfg_mod
    cfg_mod._config = None
    import shyfem_ui.db.base as db_mod
    db_mod._engine = None
    db_mod._SessionLocal = None

    from shyfem_ui.db.base import init_db
    init_db()
    yield
    db_mod._engine = None
    db_mod._SessionLocal = None
    cfg_mod._config = None


class TestLoadProjectContext:
    def test_returns_none_for_missing_id(self):
        from shyfem_ui.services.project_context import load_project_context
        assert load_project_context(9999) is None

    def test_loads_project_with_grids_and_sims(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Grid, Project, Simulation
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="test_proj", work_dir=str(tmp_path / "proj"))
            db.add(p)
            db.flush()
            g = Grid(project_id=p.id, name="grid1", grd_file="GRID/g.grd", bas_file="GRID/g.bas")
            db.add(g)
            db.flush()
            s = Simulation(project_id=p.id, grid_id=g.id, name="sim1", str_file="sim1.str")
            db.add(s)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid)
        assert ctx is not None
        assert ctx["name"] == "test_proj"
        assert len(ctx["grids"]) == 1
        assert ctx["grids"][0]["grd_file"] == "GRID/g.grd"
        assert len(ctx["simulations"]) == 1
        assert ctx["simulations"][0]["str_file"] == "sim1.str"

    def test_empty_grids_and_sims(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="empty_proj", work_dir=str(tmp_path / "empty"))
            db.add(p)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid)
        assert ctx["grids"] == []
        assert ctx["simulations"] == []
