"""Tests for pre-flight file validation on the Run page."""

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path / "shyfem"))
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))

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


class TestPreflightValidation:

    def test_no_warnings_all_files_present(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, Simulation
        from shyfem_ui.pages.run import _preflight_validate

        work = tmp_path / "projects" / "ok_proj"
        work.mkdir(parents=True)
        (work / "INPUT").mkdir()
        (work / "GRID").mkdir()
        (work / "ok.str").write_text(
            "$title\nTest\nok\nGRID/mesh\n$end\n"
            "$para\nidt = 300\n$end\n"
            "$name\nwind = 'INPUT/wind.fem'\n$end\n"
        )
        (work / "INPUT" / "wind.fem").write_text("data")
        (work / "GRID" / "mesh.bas").write_text("data")

        with db_session() as db:
            p = Project(name="ok_proj", work_dir=str(work))
            db.add(p)
            db.flush()
            s = Simulation(project_id=p.id, name="ok", str_file="ok.str")
            db.add(s)
            db.flush()
            sid = s.id

        warnings = _preflight_validate(sid)
        assert warnings == []

    def test_returns_warnings_for_missing_files(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, Simulation
        from shyfem_ui.pages.run import _preflight_validate

        work = tmp_path / "projects" / "bad_proj"
        work.mkdir(parents=True)
        (work / "bad.str").write_text(
            "$title\nTest\nbad\nGRID/mesh\n$end\n"
            "$name\nwind = 'INPUT/wind.fem'\n$end\n"
        )

        with db_session() as db:
            p = Project(name="bad_proj", work_dir=str(work))
            db.add(p)
            db.flush()
            s = Simulation(project_id=p.id, name="bad", str_file="bad.str")
            db.add(s)
            db.flush()
            sid = s.id

        warnings = _preflight_validate(sid)
        assert len(warnings) >= 1
        assert any("wind" in w.lower() for w in warnings)

    def test_returns_empty_for_invalid_sim(self):
        from shyfem_ui.pages.run import _preflight_validate
        warnings = _preflight_validate(None)
        assert warnings == []

    def test_returns_empty_for_nonexistent_sim(self):
        from shyfem_ui.pages.run import _preflight_validate
        warnings = _preflight_validate(99999)
        assert warnings == []
