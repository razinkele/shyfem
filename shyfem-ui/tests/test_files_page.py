"""Tests for Files page helpers."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path / "shyfem"))
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SHYFEM_UI_MAX_PROJECT_STORAGE_MB", "100")

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


@pytest.fixture
def project_with_files(tmp_path):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project
    from shyfem_ui.services.file_service import FileService

    work = tmp_path / "projects" / "files_proj"
    work.mkdir(parents=True)
    with db_session() as db:
        p = Project(name="files_proj", work_dir=str(work))
        db.add(p)
        db.flush()
        pid = p.id

    FileService.upload_file(pid, b"wind data", "wind.fem", "forcing", subdir="INPUT")
    FileService.upload_file(pid, b"mesh data", "mesh.grd", "grid", subdir="GRID")
    FileService.upload_file(pid, b"basin data", "mesh.bas", "basin", subdir="GRID")
    return pid, work


class TestBuildFileTable:

    def test_returns_all_files(self, project_with_files):
        from shyfem_ui.pages.files import _build_file_table_data
        pid, _ = project_with_files
        rows = _build_file_table_data(pid)
        assert len(rows) == 3

    def test_filter_by_type(self, project_with_files):
        from shyfem_ui.pages.files import _build_file_table_data
        pid, _ = project_with_files
        rows = _build_file_table_data(pid, file_type="forcing")
        assert len(rows) == 1
        assert rows[0]["filename"] == "wind.fem"

    def test_empty_project(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.pages.files import _build_file_table_data

        work = tmp_path / "projects" / "empty"
        work.mkdir(parents=True)
        with db_session() as db:
            p = Project(name="empty", work_dir=str(work))
            db.add(p)
            db.flush()
            pid = p.id
        rows = _build_file_table_data(pid)
        assert rows == []

    def test_row_contains_expected_keys(self, project_with_files):
        from shyfem_ui.pages.files import _build_file_table_data
        pid, _ = project_with_files
        rows = _build_file_table_data(pid)
        row = rows[0]
        assert "id" in row
        assert "filename" in row
        assert "file_type" in row
        assert "size_str" in row
        assert "rel_path" in row


class TestStorageSummary:

    def test_returns_usage_and_limit(self, project_with_files):
        from shyfem_ui.pages.files import _storage_summary
        pid, _ = project_with_files
        summary = _storage_summary(pid)
        assert summary["used_bytes"] > 0
        assert summary["file_count"] == 3
        assert summary["limit_bytes"] > 0
        assert 0 <= summary["usage_pct"] <= 100

    def test_empty_project_zero_usage(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.pages.files import _storage_summary

        work = tmp_path / "projects" / "empty2"
        work.mkdir(parents=True)
        with db_session() as db:
            p = Project(name="empty2", work_dir=str(work))
            db.add(p)
            db.flush()
            pid = p.id
        summary = _storage_summary(pid)
        assert summary["used_bytes"] == 0
        assert summary["usage_pct"] == 0


class TestHasTutorialData:

    def test_true_when_testcases_exist(self, tmp_path, monkeypatch):
        from shyfem_ui.pages.files import _has_tutorial_data
        shyfem_dir = tmp_path / "shyfem"
        mm = shyfem_dir / "testcases" / "examples" / "mar_menor"
        mm.mkdir(parents=True)
        (mm / "mm_hyd_00.str").write_text("data")
        monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(shyfem_dir))
        import shyfem_ui.config as cfg_mod
        cfg_mod._config = None
        assert _has_tutorial_data() is True

    def test_false_when_missing(self, tmp_path, monkeypatch):
        from shyfem_ui.pages.files import _has_tutorial_data
        monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path / "nonexistent"))
        import shyfem_ui.config as cfg_mod
        cfg_mod._config = None
        assert _has_tutorial_data() is False
