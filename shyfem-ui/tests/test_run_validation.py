"""Tests for pre-flight file validation on the Run page."""

import pytest


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
            "$title\nTest\nbad\nGRID/mesh\n$end\n" "$name\nwind = 'INPUT/wind.fem'\n$end\n"
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


class TestPreflightDoesNotHideErrors:
    """A validator FAILURE must not be reported identically to 'all clean' (M9)."""

    def test_validator_exception_returns_warning_not_empty(self, monkeypatch):
        from shyfem_ui.pages.run import _preflight_validate
        from shyfem_ui.services.file_service import FileService

        def _boom(_sid):
            raise RuntimeError("db exploded")

        monkeypatch.setattr(FileService, "validate_simulation_files", staticmethod(_boom))
        warnings = _preflight_validate(123)
        assert warnings, "a failed pre-flight must surface a warning, not silently report clean"
        assert any("valid" in w.lower() for w in warnings)

    def test_nonexistent_sim_still_returns_empty(self):
        # ValueError ('not found') stays non-blocking -> [] (existing behavior).
        from shyfem_ui.pages.run import _preflight_validate

        assert _preflight_validate(99999) == []


class TestPreflightSkipSurfaced:
    def test_preflight_validation_skip_is_surfaced(self):
        """The pre-run STR validation gate used to swallow every failure
        at debug level — combined with the validate_str shape bug this
        made the preflight a silent no-op for months. A skipped
        validation must now be visible to the user and the log."""
        import inspect

        from shyfem_ui.pages import run

        src = inspect.getsource(run)
        block = src[src.index("Validate STR parameters before submission") :]
        block = block[: block.index("if not working_dir")]
        assert "logger.warning" in block
        assert "notification_show" in block.split("except Exception")[1]
