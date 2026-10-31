"""Tests for the Run page's pre-run STR validation gate."""

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
