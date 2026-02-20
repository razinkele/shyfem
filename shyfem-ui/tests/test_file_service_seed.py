"""Tests for FileService.seed_tutorial_files."""

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
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


@pytest.fixture
def fake_tutorial_dir(tmp_path, monkeypatch):
    """Create a fake testcases/examples/mar_menor with known files."""
    shyfem_dir = tmp_path / "shyfem"
    mm = shyfem_dir / "testcases" / "examples" / "mar_menor"
    (mm / "GRID").mkdir(parents=True)
    (mm / "INPUT").mkdir()
    (mm / "GRID" / "MM_coarse.grd").write_text("grid data")
    (mm / "GRID" / "MM_coarse.bas").write_bytes(b"\x00bas")
    (mm / "INPUT" / "wind.fem").write_text("wind data")
    (mm / "INPUT" / "level.dat").write_text("level data")
    (mm / "mm_hyd_00.str").write_text("$title\nTest\nmm_hyd_00\nGRID/MM_coarse\n$end\n")
    (mm / "mm_hyd_01.str").write_text("$title\nTest\nmm_hyd_01\nGRID/MM_coarse\n$end\n")
    # These should NOT be copied
    (mm / "Makefile").write_text("make stuff")
    (mm / "run_all.sh").write_text("#!/bin/bash")
    (mm / "mm_hyd_00.sh").write_text("#!/bin/bash")

    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(shyfem_dir))
    import shyfem_ui.config as cfg_mod
    cfg_mod._config = None
    return mm


@pytest.fixture
def empty_project(tmp_path):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project

    work = tmp_path / "projects" / "tutorial_proj"
    work.mkdir(parents=True)
    with db_session() as db:
        p = Project(name="tutorial_proj", work_dir=str(work))
        db.add(p)
        db.flush()
        pid = p.id
    return pid, work


class TestSeedTutorialFiles:

    def test_copies_grid_files(self, fake_tutorial_dir, empty_project):
        from shyfem_ui.services.file_service import FileService
        pid, work = empty_project

        FileService.seed_tutorial_files(pid)
        assert (work / "GRID" / "MM_coarse.grd").exists()
        assert (work / "GRID" / "MM_coarse.bas").exists()

    def test_copies_input_files(self, fake_tutorial_dir, empty_project):
        from shyfem_ui.services.file_service import FileService
        pid, work = empty_project

        FileService.seed_tutorial_files(pid)
        assert (work / "INPUT" / "wind.fem").exists()
        assert (work / "INPUT" / "level.dat").exists()

    def test_copies_str_files(self, fake_tutorial_dir, empty_project):
        from shyfem_ui.services.file_service import FileService
        pid, work = empty_project

        FileService.seed_tutorial_files(pid)
        assert (work / "mm_hyd_00.str").exists()
        assert (work / "mm_hyd_01.str").exists()

    def test_skips_scripts_and_makefile(self, fake_tutorial_dir, empty_project):
        from shyfem_ui.services.file_service import FileService
        pid, work = empty_project

        FileService.seed_tutorial_files(pid)
        assert not (work / "Makefile").exists()
        assert not (work / "run_all.sh").exists()
        assert not (work / "mm_hyd_00.sh").exists()

    def test_creates_db_records(self, fake_tutorial_dir, empty_project):
        from shyfem_ui.services.file_service import FileService
        pid, _ = empty_project

        FileService.seed_tutorial_files(pid)
        files = FileService.list_files(pid)
        # At least: 2 grid files + 2 input files + 2 str files = 6
        assert len(files) >= 6

    def test_assigns_correct_file_types(self, fake_tutorial_dir, empty_project):
        from shyfem_ui.services.file_service import FileService
        pid, _ = empty_project

        FileService.seed_tutorial_files(pid)
        files = FileService.list_files(pid)
        types = {f["filename"]: f["file_type"] for f in files}
        assert types["MM_coarse.grd"] == "grid"
        assert types["MM_coarse.bas"] == "basin"
        assert types["mm_hyd_00.str"] == "str"
        assert types["wind.fem"] == "forcing"
