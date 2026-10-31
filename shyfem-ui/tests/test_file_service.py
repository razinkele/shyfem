"""Tests for FileService."""

import pytest


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

    def test_concurrent_uploads_cannot_both_pass_the_quota(self, project_with_dir, monkeypatch):
        """Uploads run in threads (F-05): two 6 MB files into a 10 MB project
        must not both pass the quota check before either is written."""
        import threading
        import time

        import shyfem_ui.services.file_service as fs_mod
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        real_sum = fs_mod._sum_project_bytes

        def slow_sum(*args, **kwargs):
            total = real_sum(*args, **kwargs)
            time.sleep(0.2)  # widen the check-to-write window
            return total

        monkeypatch.setattr(fs_mod, "_sum_project_bytes", slow_sum)
        data = b"x" * (6 * 1024 * 1024)
        outcomes = []

        def upload(name):
            try:
                FileService.upload_file(
                    project_id=pid, file_data=data, filename=name, file_type="other"
                )
                outcomes.append("ok")
            except ValueError as e:
                outcomes.append(str(e))

        threads = [threading.Thread(target=upload, args=(f"f{i}.dat",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert outcomes.count("ok") == 1, outcomes
        assert sum("storage limit" in o for o in outcomes) == 1, outcomes
        assert len(list(work.glob("f*.dat"))) == 1

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
            project_id=pid,
            file_data=b"data",
            filename="del.dat",
            file_type="other",
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
        assert storage["cache_bytes"] == 0

    def test_empty_project_returns_zero(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService

        pid, _ = project_with_dir

        storage = FileService.get_project_storage(pid)
        assert storage["used_bytes"] == 0
        assert storage["file_count"] == 0
        assert storage["cache_bytes"] == 0

    def test_used_bytes_matches_the_quota_check_and_breaks_out_the_cache(self, project_with_dir):
        """Review Important 4: the displayed usage used to call
        ``_sum_project_bytes`` WITHOUT the project's work_dir while the upload
        quota check passed it, so the box-model cache was enforced but never
        shown -- a user could be refused an upload with "plenty of space left"
        on screen. The two must agree, and the cache-only part is reported
        separately so the number can be explained."""
        from shyfem_ui.db.base import db_session
        from shyfem_ui.services.file_service import FileService, _sum_project_bytes

        pid, work = project_with_dir
        FileService.upload_file(pid, b"aaaa", "a.dat", "other")
        cache = work / ".boxmodel_cache" / "fix"
        cache.mkdir(parents=True)
        (cache / "state_daily.parquet").write_bytes(b"x" * 250)

        storage = FileService.get_project_storage(pid)
        assert storage["cache_bytes"] == 250
        assert storage["used_bytes"] == 254  # 4 uploaded + 250 cached
        assert storage["file_count"] == 1  # cache files are not ProjectFile rows
        with db_session() as db:
            assert storage["used_bytes"] == _sum_project_bytes(db, pid, work_dir=str(work))


class TestFileServiceUpload:

    def test_upload_same_path_twice_is_idempotent(self, project_with_dir):
        """Two uploads of the same rel_path must produce one row, latest content,
        and a quota that reflects ONLY the latest size — not the sum of both."""
        from shyfem_ui.db.base import db_session
        from shyfem_ui.services.file_service import FileService, _sum_project_bytes

        pid, work = project_with_dir

        FileService.upload_file(
            project_id=pid,
            file_data=b"v1",
            filename="foo.txt",
            file_type="other",
            subdir="data",
        )
        FileService.upload_file(
            project_id=pid,
            file_data=b"v22",
            filename="foo.txt",
            file_type="other",
            subdir="data",
        )
        files = FileService.list_files(project_id=pid)
        paths = [f["rel_path"] for f in files]
        assert paths.count("data/foo.txt") == 1, f"Got {len(paths)} rows for same rel_path: {paths}"
        assert (work / "data" / "foo.txt").read_bytes() == b"v22"
        # CRITICAL regression: quota must NOT double-count after re-upload.
        # Old bug: row count grew with each upload, summing to len(b"v1")+len(b"v22") = 5.
        # New: single row of len(b"v22") = 3.
        with db_session() as db:
            total = _sum_project_bytes(db, pid)
        assert total == 3, "Quota inflated: per-path row should be replaced, not duplicated"


class TestInferFileType:

    def test_infer_file_type_lagrangian_lgr(self):
        """`.lgr` (Lagrangian particle output) maps to 'lagrangian' file_type.

        Used by pages/ibm.py to filter the file picker to Lagrangian files
        only. Without this, .lgr files fall through to 'other' and would
        require the picker filter to include 'other' — which pollutes the
        dropdown with any unrecognized file type.
        """
        from shyfem_ui.services.file_service import FileService

        assert FileService._infer_file_type("trajectories.lgr") == "lagrangian"
        assert FileService._infer_file_type("OUTPUT/sim.lgr") == "lagrangian"
        # Case-insensitive on extension (the existing branches use .lower())
        assert FileService._infer_file_type("OUT.LGR") == "lagrangian"


class TestUploadSandboxEscape:
    """upload_file must keep writes inside the project work_dir. A subdir was
    only checked for '..' parts, not absolute paths: work_dir / '/etc/x'
    resolves to /etc/x (absolute RHS wins), letting an authenticated editor
    write outside the sandbox."""

    def test_absolute_subdir_rejected_and_nothing_written(self, project_with_dir, tmp_path):
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        escape_dir = tmp_path / "escape_target"  # OUTSIDE the project work_dir
        with pytest.raises(ValueError):
            FileService.upload_file(
                project_id=pid,
                file_data=b"pwned",
                filename="x.txt",
                file_type="other",
                subdir=str(escape_dir),  # absolute path
            )
        assert not (escape_dir / "x.txt").exists()

    def test_relative_subdir_still_works(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        result = FileService.upload_file(
            project_id=pid,
            file_data=b"grid",
            filename="m.grd",
            file_type="grid",
            subdir="GRID/sub",
        )
        assert result["rel_path"] == "GRID/sub/m.grd"
        assert (work / "GRID" / "sub" / "m.grd").exists()


class TestUploadSubdirDot:
    """F-08: subdir "." stored ``./x`` beside ``x`` -- two rows, one file."""

    @pytest.mark.parametrize("subdir", [".", "./", "", None])
    def test_dot_subdir_is_the_project_root(self, project_with_dir, subdir):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import ProjectFile
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        FileService.upload_file(pid, b"a", "x.dat", "other")
        result = FileService.upload_file(pid, b"bb", "x.dat", "other", subdir=subdir)

        assert result["rel_path"] == "x.dat"
        with db_session() as db:
            rows = db.query(ProjectFile).filter_by(project_id=pid).all()
            assert [(r.rel_path, r.size_bytes) for r in rows] == [("x.dat", 2)]
        assert (work / "x.dat").read_bytes() == b"bb"

    def test_dot_inside_subdir_is_dropped(self, project_with_dir):
        from shyfem_ui.services.file_service import FileService

        pid, _ = project_with_dir
        result = FileService.upload_file(pid, b"a", "x.dat", "other", subdir="./GRID/.")
        assert result["rel_path"] == "GRID/x.dat"


class TestUploadDiskAndRowStayInStep:
    """F-04: the file was written before its row; a failed row left the file."""

    @staticmethod
    def _fail_flush(monkeypatch):
        from sqlalchemy.orm import Session

        def _boom(self, *a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(Session, "flush", _boom)

    def test_failed_row_removes_a_new_file(self, project_with_dir, monkeypatch):
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        self._fail_flush(monkeypatch)
        with pytest.raises(RuntimeError):
            FileService.upload_file(pid, b"new", "y.dat", "other", subdir="INPUT")
        assert sorted(p.name for p in work.rglob("*") if p.is_file()) == []

    def test_failed_row_keeps_the_previous_bytes(self, project_with_dir, monkeypatch):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import ProjectFile
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        FileService.upload_file(pid, b"old", "y.dat", "other")
        self._fail_flush(monkeypatch)
        with pytest.raises(RuntimeError):
            FileService.upload_file(pid, b"newer", "y.dat", "other")
        monkeypatch.undo()
        assert (work / "y.dat").read_bytes() == b"old"
        assert sorted(p.name for p in work.iterdir()) == ["y.dat"]
        with db_session() as db:
            (row,) = db.query(ProjectFile).filter_by(project_id=pid).all()
            assert row.size_bytes == 3

    def test_failed_commit_removes_a_new_file(self, project_with_dir, monkeypatch):
        from sqlalchemy.orm import Session

        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir

        def _boom(self):
            raise RuntimeError("commit failed")

        monkeypatch.setattr(Session, "commit", _boom)
        with pytest.raises(RuntimeError):
            FileService.upload_file(pid, b"new", "z.dat", "other")
        assert list(work.iterdir()) == []

    def test_failed_delete_commit_keeps_the_file(self, project_with_dir, monkeypatch):
        """The reverse drift: delete unlinked the file before the row went."""
        from sqlalchemy.orm import Session

        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import ProjectFile
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        fid = FileService.upload_file(pid, b"keep", "k.dat", "other")["id"]

        def _boom(self):
            raise RuntimeError("commit failed")

        monkeypatch.setattr(Session, "commit", _boom)
        with pytest.raises(RuntimeError):
            FileService.delete_file(fid)
        monkeypatch.undo()
        assert (work / "k.dat").read_bytes() == b"keep"
        with db_session() as db:
            assert db.query(ProjectFile).filter_by(id=fid).count() == 1

    def test_delete_still_removes_file_and_row(self, project_with_dir):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import ProjectFile
        from shyfem_ui.services.file_service import FileService

        pid, work = project_with_dir
        fid = FileService.upload_file(pid, b"x", "d.dat", "other")["id"]
        FileService.delete_file(fid)
        assert not (work / "d.dat").exists()
        with db_session() as db:
            assert db.query(ProjectFile).filter_by(id=fid).count() == 0
