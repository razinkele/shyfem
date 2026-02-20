"""Tests for FileService."""

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
    """Create a project with a work directory."""
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


class TestUploadFile:

    def test_upload_creates_file_and_record(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, work = project_with_dir

        result = FileService.upload_file(
            project_id=pid,
            file_data=b"wind speed data\n1.0 2.0\n",
            filename="wind.fem",
            file_type="forcing",
        )
        assert result["id"] is not None
        assert result["filename"] == "wind.fem"
        assert result["rel_path"] == "wind.fem"
        assert result["file_type"] == "forcing"
        assert result["size_bytes"] == len(b"wind speed data\n1.0 2.0\n")
        assert (work / "wind.fem").exists()

    def test_upload_with_subdir(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, work = project_with_dir

        result = FileService.upload_file(
            project_id=pid,
            file_data=b"grid data",
            filename="mesh.grd",
            file_type="grid",
            subdir="GRID",
        )
        assert result["rel_path"] == "GRID/mesh.grd"
        assert (work / "GRID" / "mesh.grd").exists()

    def test_upload_rejects_path_traversal(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, _ = project_with_dir

        with pytest.raises(ValueError, match="Invalid filename"):
            FileService.upload_file(
                project_id=pid,
                file_data=b"evil",
                filename="../../../etc/passwd",
                file_type="other",
            )

    def test_upload_rejects_quota_exceeded(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, _ = project_with_dir

        # Upload 11MB to exceed 10MB quota
        big_data = b"x" * (11 * 1024 * 1024)
        with pytest.raises(ValueError, match="storage limit"):
            FileService.upload_file(
                project_id=pid,
                file_data=big_data,
                filename="big.dat",
                file_type="other",
            )

    def test_upload_computes_checksum(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, _ = project_with_dir

        result = FileService.upload_file(
            project_id=pid,
            file_data=b"test content",
            filename="test.dat",
            file_type="other",
        )
        assert result["checksum"] is not None
        assert len(result["checksum"]) == 64  # SHA256 hex digest


class TestDeleteFile:

    def test_delete_removes_file_and_record(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, work = project_with_dir

        result = FileService.upload_file(
            project_id=pid, file_data=b"data",
            filename="del.dat", file_type="other",
        )
        fid = result["id"]
        assert (work / "del.dat").exists()

        FileService.delete_file(fid)
        assert not (work / "del.dat").exists()

        files = FileService.list_files(pid)
        assert len(files) == 0

    def test_delete_nonexistent_raises(self):
        from shyfem_ui.services.file_service import FileService
        with pytest.raises(ValueError, match="not found"):
            FileService.delete_file(99999)


class TestListFiles:

    def test_list_all_files(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, _ = project_with_dir

        FileService.upload_file(pid, b"a", "a.fem", "forcing")
        FileService.upload_file(pid, b"b", "b.grd", "grid")
        FileService.upload_file(pid, b"c", "c.str", "str")

        files = FileService.list_files(pid)
        assert len(files) == 3

    def test_list_filtered_by_type(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, _ = project_with_dir

        FileService.upload_file(pid, b"a", "a.fem", "forcing")
        FileService.upload_file(pid, b"b", "b.grd", "grid")
        FileService.upload_file(pid, b"c", "c.fem", "forcing")

        forcing = FileService.list_files(pid, file_type="forcing")
        assert len(forcing) == 2

        grids = FileService.list_files(pid, file_type="grid")
        assert len(grids) == 1


class TestGetFilePath:

    def test_returns_absolute_path(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, work = project_with_dir

        result = FileService.upload_file(pid, b"data", "test.fem", "forcing")
        path = FileService.get_file_path(result["id"])
        assert path == work / "test.fem"
        assert path.is_absolute()


class TestGetProjectStorage:

    def test_returns_used_bytes_and_count(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, _ = project_with_dir

        FileService.upload_file(pid, b"aaaa", "a.dat", "other")
        FileService.upload_file(pid, b"bb", "b.dat", "other")

        storage = FileService.get_project_storage(pid)
        assert storage["used_bytes"] == 6
        assert storage["file_count"] == 2

    def test_empty_project_returns_zero(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService
        pid, _ = project_with_dir

        storage = FileService.get_project_storage(pid)
        assert storage["used_bytes"] == 0
        assert storage["file_count"] == 0
