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

        # Context shape/content is auth-agnostic; pin local mode so the test is
        # deterministic regardless of the ambient .env deployment_mode (server
        # mode fails closed on user=None — covered separately below).
        ctx = load_project_context(pid, user=None, is_server_mode=False)
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

        # Context shape/content is auth-agnostic; pin local mode so the test is
        # deterministic regardless of the ambient .env deployment_mode (server
        # mode fails closed on user=None — covered separately below).
        ctx = load_project_context(pid, user=None, is_server_mode=False)
        assert ctx["grids"] == []
        assert ctx["simulations"] == []

    def test_context_includes_grid_and_sim_metadata(self, tmp_path):
        """2026-06-08 audit P6: the import-populated metadata columns must be
        readable from the context so the dashboard Details modal can show them."""
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Grid, Project, Simulation
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="meta_proj", work_dir=str(tmp_path / "proj"))
            db.add(p)
            db.flush()
            g = Grid(
                project_id=p.id,
                name="grid1",
                grd_file="GRID/g.grd",
                bas_file="GRID/g.bas",
                num_layers=12,
                min_depth=0.5,
                max_depth=44.0,
            )
            db.add(g)
            db.flush()
            s = Simulation(
                project_id=p.id,
                grid_id=g.id,
                name="sim1",
                str_file="sim1.str",
                start_time="2024-01-01 00:00:00",
                end_time="2024-01-31 00:00:00",
                time_step=300.0,
            )
            db.add(s)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid, user=None, is_server_mode=False)
        assert ctx is not None
        grid = ctx["grids"][0]
        assert grid["num_layers"] == 12
        assert grid["min_depth"] == 0.5
        assert grid["max_depth"] == 44.0
        sim = ctx["simulations"][0]
        assert sim["start_time"] == "2024-01-01 00:00:00"
        assert sim["end_time"] == "2024-01-31 00:00:00"
        assert sim["time_step"] == 300.0

    def test_context_includes_files(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, ProjectFile
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="files_proj", work_dir=str(tmp_path / "fp"))
            db.add(p)
            db.flush()
            pf = ProjectFile(
                project_id=p.id,
                filename="wind.fem",
                rel_path="INPUT/wind.fem",
                file_type="forcing",
                size_bytes=100,
            )
            db.add(pf)
            db.flush()
            pid = p.id

        # Context shape/content is auth-agnostic; pin local mode so the test is
        # deterministic regardless of the ambient .env deployment_mode (server
        # mode fails closed on user=None — covered separately below).
        ctx = load_project_context(pid, user=None, is_server_mode=False)
        assert "files" in ctx
        assert len(ctx["files"]) == 1
        assert ctx["files"][0]["filename"] == "wind.fem"
        assert ctx["files"][0]["file_type"] == "forcing"


class TestServerModeFailClosed:
    """In server mode an unresolved identity (user=None) must NOT load a project.

    home.py activation/clone/export delegate authorization entirely to
    ``load_project_context(pid, user=_user())``. Behind the proxy a viewer who
    never pushes ``_wsauth`` resolves to user=None; if the access check is
    skipped for None, that viewer can open/export/clone ANY project by id
    (data exfiltration). Server mode therefore fails closed on None; local
    desktop mode (no auth, user legitimately None) still loads.
    """

    def test_server_mode_denies_unresolved_user(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="secret", work_dir=str(tmp_path / "secret"))
            db.add(p)
            db.flush()
            pid = p.id

        assert load_project_context(pid, user=None, is_server_mode=True) is None

    def test_local_mode_loads_unresolved_user(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="local", work_dir=str(tmp_path / "local"))
            db.add(p)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid, user=None, is_server_mode=False)
        assert ctx is not None
        assert ctx["name"] == "local"

    def test_server_mode_auto_detected_from_config(self, tmp_path, monkeypatch):
        import shyfem_ui.config as cfg_mod
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="cfg", work_dir=str(tmp_path / "cfg"))
            db.add(p)
            db.flush()
            pid = p.id

        cfg = cfg_mod.get_config()
        monkeypatch.setattr(cfg, "deployment_mode", "server")
        assert load_project_context(pid, user=None) is None
        monkeypatch.setattr(cfg, "deployment_mode", "local")
        assert load_project_context(pid, user=None) is not None


class TestProjectContextShape:
    def test_load_returns_dict_with_required_keys(self, tmp_path):
        """Pin _load's runtime return shape to ProjectContext TypedDict.

        If _load drops a key (e.g., bas_file from a grid dict), this test
        fails immediately. Catches drift between the static TypedDict
        declaration and runtime construction.
        """
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import (
            Grid,
            Project,
            ProjectFile,
            Simulation,
        )
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="ctx_proj", work_dir=str(tmp_path / "p"))
            db.add(p)
            db.flush()
            db.add(
                Grid(
                    project_id=p.id,
                    name="g",
                    grd_file="g.grd",
                    bas_file="g.bas",
                )
            )
            db.add(
                Simulation(
                    project_id=p.id,
                    name="s",
                    str_file="s.str",
                )
            )
            db.add(
                ProjectFile(
                    project_id=p.id,
                    filename="g.grd",
                    rel_path="g.grd",
                    file_type="grid",
                    size_bytes=42,
                )
            )
            db.flush()
            pid = p.id

        # Context shape/content is auth-agnostic; pin local mode so the test is
        # deterministic regardless of the ambient .env deployment_mode (server
        # mode fails closed on user=None — covered separately below).
        ctx = load_project_context(pid, user=None, is_server_mode=False)

        # Top-level ProjectContext keys
        assert ctx is not None
        assert set(ctx.keys()) >= {
            "id",
            "name",
            "work_dir",
            "description",
            "grids",
            "simulations",
            "files",
        }
        assert isinstance(ctx["id"], int)
        assert isinstance(ctx["name"], str)
        assert isinstance(ctx["work_dir"], str)

        # Nested GridEntry keys
        assert ctx["grids"], "expected at least one grid"
        g0 = ctx["grids"][0]
        assert set(g0.keys()) >= {"name", "grd_file", "bas_file"}

        # Nested SimulationEntry keys
        assert ctx["simulations"], "expected at least one simulation"
        s0 = ctx["simulations"][0]
        assert set(s0.keys()) >= {"name", "str_file"}

        # Nested FileEntry keys
        assert ctx["files"], "expected at least one file"
        f0 = ctx["files"][0]
        assert set(f0.keys()) >= {
            "id",
            "filename",
            "rel_path",
            "file_type",
            "size_bytes",
        }
        assert isinstance(f0["id"], int)
        assert isinstance(f0["size_bytes"], int)

        # Pin the TypedDict declarations themselves — fails if a future
        # commit changes any TypedDict's annotated keys without also
        # changing _load. Nested TypedDicts must be pinned independently
        # — Python's __annotations__ on TypedDict is shallow, so the
        # top-level check doesn't recurse.
        from shyfem_ui.services.project_context import (
            FileEntry,
            GridEntry,
            ProjectContext,
            SimulationEntry,
        )

        assert set(ProjectContext.__annotations__.keys()) == {
            "id",
            "name",
            "work_dir",
            "description",
            "grids",
            "simulations",
            "files",
        }
        assert set(GridEntry.__annotations__.keys()) == {
            "name",
            "grd_file",
            "bas_file",
            "num_layers",
            "min_depth",
            "max_depth",
        }
        assert set(SimulationEntry.__annotations__.keys()) == {
            "name",
            "str_file",
            "start_time",
            "end_time",
            "time_step",
        }
        assert set(FileEntry.__annotations__.keys()) == {
            "id",
            "filename",
            "rel_path",
            "file_type",
            "size_bytes",
        }
