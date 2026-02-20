"""Tests for file_browser persistence via FileService."""

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path / "shyfem"))
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SHYFEM_UI_MAX_PROJECT_STORAGE_MB", "10")

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
def project_with_dir(tmp_path):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project

    work = tmp_path / "projects" / "test_proj"
    work.mkdir(parents=True)
    with db_session() as db:
        p = Project(name="test_proj", work_dir=str(work))
        db.add(p)
        db.flush()
        pid = p.id
    return pid, work


class TestPersistUpload:

    def test_persist_upload_creates_db_record(self, project_with_dir, tmp_path):
        from shyfem_ui.components.file_browser import persist_upload
        pid, work = project_with_dir

        temp = tmp_path / "upload_tmp" / "wind.fem"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text("wind data\n1.0 2.0\n")

        result = persist_upload(
            temp_path=temp,
            filename="wind.fem",
            project_id=pid,
            file_type="forcing",
        )
        assert result["id"] is not None
        assert result["filename"] == "wind.fem"
        assert result["file_type"] == "forcing"
        assert (work / "wind.fem").exists()

    def test_persist_upload_with_subdir(self, project_with_dir, tmp_path):
        from shyfem_ui.components.file_browser import persist_upload
        pid, work = project_with_dir

        temp = tmp_path / "upload_tmp" / "mesh.grd"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(b"grid data")

        result = persist_upload(
            temp_path=temp,
            filename="mesh.grd",
            project_id=pid,
            file_type="grid",
            subdir="GRID",
        )
        assert result["rel_path"] == "GRID/mesh.grd"
        assert (work / "GRID" / "mesh.grd").exists()

    def test_persist_upload_returns_none_without_project(self, tmp_path):
        from shyfem_ui.components.file_browser import persist_upload

        temp = tmp_path / "upload_tmp" / "data.dat"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text("data")

        result = persist_upload(
            temp_path=temp,
            filename="data.dat",
            project_id=None,
            file_type="other",
        )
        assert result is None

    def test_persist_upload_quota_exceeded(self, project_with_dir, tmp_path):
        from shyfem_ui.components.file_browser import persist_upload
        pid, _ = project_with_dir

        temp = tmp_path / "upload_tmp" / "big.dat"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(b"x" * (11 * 1024 * 1024))

        result = persist_upload(
            temp_path=temp,
            filename="big.dat",
            project_id=pid,
            file_type="other",
        )
        assert result is None

    def test_infer_file_type_from_extension(self):
        from shyfem_ui.components.file_browser import infer_file_type
        assert infer_file_type("mesh.grd") == "grid"
        assert infer_file_type("domain.bas") == "basin"
        assert infer_file_type("sim.str") == "str"
        assert infer_file_type("gotmturb.nml") == "config"
        assert infer_file_type("data.txt") == "other"
        assert infer_file_type("INPUT/wind.fem") == "forcing"
