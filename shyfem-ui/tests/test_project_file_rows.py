"""Imported and cloned projects get file rows; seeding never overwrites (F-01).

Before this fix an imported or cloned project had files on disk but no
ProjectFile rows: the Files page listed nothing, showed 0 B against the
quota, and offered "Seed Tutorial Files", which copied the tutorial over
same-named files such as the user's edited ``mm_hyd_00.str``.
"""

import json
import zipfile
from io import BytesIO

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SHYFEM_UI_MAX_PROJECT_STORAGE_MB", "10")
    shyfem_dir = tmp_path / "shyfem"
    mm = shyfem_dir / "testcases" / "examples" / "mar_menor"
    (mm / "GRID").mkdir(parents=True)
    (mm / "GRID" / "mm.bas").write_bytes(b"\x00tutorial bas")
    (mm / "mm_hyd_00.str").write_text("$title\ntutorial\n$end\n")
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(shyfem_dir))

    import shyfem_ui.config as cfg_mod
    import shyfem_ui.db.base as db_mod

    cfg_mod._config = None
    db_mod._engine = None
    db_mod._SessionLocal = None
    from shyfem_ui.db.base import init_db

    init_db()
    yield
    db_mod._engine = None
    db_mod._SessionLocal = None
    cfg_mod._config = None


_EDITED_STR = "$title\nmy edited run\n$end\n"


def _app_zip(files: list | None = None) -> BytesIO:
    """A ZIP shaped like the app's own export."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mm_hyd_00.str", _EDITED_STR)
        zf.writestr("GRID/mm.bas", b"\x00user bas")
        zf.writestr("INPUT/wind.fem", "wind")
        zf.writestr("INPUT/bc.dat", "boundary")
        zf.writestr("run.stdout", "a job log")
        zf.writestr(".boxmodel_cache/r1/state.parquet", "cache")
        manifest = {
            "version": "1.0",
            "project": {"name": "imp"},
            "grids": [],
            "simulations": [{"name": "s", "str_file": "mm_hyd_00.str"}],
            "files": files or [],
        }
        zf.writestr("manifest.json", json.dumps(manifest))
    buf.seek(0)
    return buf


async def _import(tmp_path, files=None) -> int:
    from shyfem_ui.services.project_export import create_project_records, import_project

    result = await import_project(_app_zip(files), tmp_path / "projects")
    return create_project_records(result, owner_id=None)


def _rel_paths(pid):
    from shyfem_ui.services.file_service import FileService

    return {f["rel_path"]: f for f in FileService.list_files(pid)}


@pytest.mark.asyncio
async def test_an_imported_project_lists_its_files_and_counts_them(tmp_path):
    from shyfem_ui.services.file_service import FileService

    pid = await _import(tmp_path)
    rows = _rel_paths(pid)
    assert set(rows) == {"mm_hyd_00.str", "GRID/mm.bas", "INPUT/wind.fem", "INPUT/bc.dat"}
    assert rows["mm_hyd_00.str"]["size_bytes"] == len(_EDITED_STR)
    assert rows["GRID/mm.bas"]["file_type"] == "basin"
    storage = FileService.get_project_storage(pid)
    assert storage["file_count"] == 4
    assert storage["used_bytes"] > 0


@pytest.mark.asyncio
async def test_the_manifest_restores_a_type_the_user_chose(tmp_path):
    pid = await _import(
        tmp_path,
        files=[
            {"rel_path": "INPUT/bc.dat", "file_type": "boundary"},
            {"rel_path": "INPUT/wind.fem", "file_type": "<script>"},  # unknown: inferred
            {"rel_path": "not/extracted.txt", "file_type": "grid"},  # no file: no row
            "not a dict",
        ],
    )
    rows = _rel_paths(pid)
    assert rows["INPUT/bc.dat"]["file_type"] == "boundary"
    assert rows["INPUT/wind.fem"]["file_type"] == "forcing"
    assert "not/extracted.txt" not in rows


@pytest.mark.asyncio
async def test_seeding_an_imported_project_is_refused_and_keeps_the_users_files(tmp_path):
    from shyfem_ui.services.file_service import FileService

    pid = await _import(tmp_path)
    work = tmp_path / "projects" / "imp"
    assert FileService.has_project_files(pid)
    with pytest.raises(ValueError, match="already has files"):
        FileService.seed_tutorial_files(pid)
    assert (work / "mm_hyd_00.str").read_text() == _EDITED_STR
    assert (work / "GRID" / "mm.bas").read_bytes() == b"\x00user bas"


def _project(tmp_path, name="p"):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project

    work = tmp_path / "projects" / name
    work.mkdir(parents=True)
    with db_session() as db:
        p = Project(name=name, work_dir=str(work))
        db.add(p)
        db.flush()
        return p.id, work


def test_seeding_a_project_with_files_but_no_rows_is_refused(tmp_path):
    """The live 'Mar Menor Tutorial' project has 85 files on disk and 0 rows."""
    from shyfem_ui.services.file_service import FileService

    pid, work = _project(tmp_path)
    (work / "notes.txt").write_text("mine")
    assert FileService.has_project_files(pid)
    with pytest.raises(ValueError, match="already has files"):
        FileService.seed_tutorial_files(pid)
    assert not (work / "mm_hyd_00.str").exists()
    assert FileService.list_files(pid) == []


def test_seeding_an_empty_project_still_works(tmp_path):
    from shyfem_ui.services.file_service import FileService

    pid, work = _project(tmp_path)
    (work / "run.stdout").write_text("a job log is not a project file")
    assert not FileService.has_project_files(pid)
    FileService.seed_tutorial_files(pid)
    assert (work / "mm_hyd_00.str").read_text() == "$title\ntutorial\n$end\n"
    assert len(FileService.list_files(pid)) == 2


def test_seeding_is_refused_when_only_rows_exist(tmp_path):
    """A row whose file is gone would collide with the seed's insert after the copy."""
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import ProjectFile
    from shyfem_ui.services.file_service import FileService

    pid, work = _project(tmp_path)
    with db_session() as db:
        db.add(
            ProjectFile(
                project_id=pid, filename="mm_hyd_00.str", rel_path="mm_hyd_00.str", file_type="str"
            )
        )
    with pytest.raises(ValueError, match="already has files"):
        FileService.seed_tutorial_files(pid)
    assert not (work / "mm_hyd_00.str").exists()


def test_register_existing_files_is_idempotent_and_skips_job_and_cache_files(tmp_path):
    from shyfem_ui.services.file_service import FileService

    pid, work = _project(tmp_path)
    (work / "a.str").write_text("x")
    (work / "run.pid").write_text("1")
    (work / ".boxmodel_cache" / "r").mkdir(parents=True)
    (work / ".boxmodel_cache" / "r" / "c.parquet").write_text("c")
    (work / "link.str").symlink_to(work / "a.str")
    assert FileService.register_existing_files(pid) == 1
    assert FileService.register_existing_files(pid) == 0
    assert set(_rel_paths(pid)) == {"a.str"}


def test_clone_copies_rows_and_their_types(tmp_path):
    from shyfem_ui.services.file_service import FileService
    from shyfem_ui.services.project_context import load_project_context
    from shyfem_ui.services.project_export import (
        clone_project,
        create_project_records,
        export_meta,
    )

    pid, work = _project(tmp_path, "src")
    (work / "INPUT").mkdir()
    FileService.upload_file(pid, b"bc", "bc.dat", "boundary", subdir="INPUT")
    (work / "unregistered.str").write_text("on disk only")
    ctx = load_project_context(pid)
    meta = export_meta(ctx)
    assert meta["files"] == [{"rel_path": "INPUT/bc.dat", "file_type": "boundary"}]
    result = clone_project(work, meta, tmp_path / "projects")
    clone_id = create_project_records(result, owner_id=None)
    rows = _rel_paths(clone_id)
    assert rows["INPUT/bc.dat"]["file_type"] == "boundary"
    assert rows["unregistered.str"]["file_type"] == "str"
    assert set(_rel_paths(pid)) == {"INPUT/bc.dat"}  # source rows unchanged


@pytest.mark.asyncio
async def test_an_import_over_the_storage_limit_is_refused(tmp_path, monkeypatch):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project
    from shyfem_ui.services.project_export import create_project_records, import_project

    monkeypatch.setenv("SHYFEM_UI_MAX_PROJECT_STORAGE_MB", "0")
    import shyfem_ui.config as cfg_mod

    cfg_mod._config = None
    result = await import_project(_app_zip(), tmp_path / "projects")
    with pytest.raises(ValueError, match="storage limit"):
        create_project_records(result, owner_id=None)
    with db_session() as db:
        assert db.query(Project).count() == 0


def test_export_meta_carries_rows_without_db_ids():
    from shyfem_ui.services.project_export import export_meta

    ctx = {
        "name": "p",
        "description": "d",
        "grids": [],
        "simulations": [],
        "files": [
            {
                "id": 7,
                "filename": "a.str",
                "rel_path": "a.str",
                "file_type": "str",
                "size_bytes": 1,
            }
        ],
    }
    assert export_meta(ctx)["files"] == [{"rel_path": "a.str", "file_type": "str"}]


def test_handlers_use_the_shared_helpers():
    """Export, clone and import build meta and records in one place."""
    import inspect

    from shyfem_ui.pages import home

    src = inspect.getsource(home)
    assert src.count("export_meta(ctx)") == 2
    assert src.count("create_project_records(") == 2
    # the tutorial project is created from a full copy of mar_menor
    assert src.count("register_existing_files(project.id, db=db)") == 1


def test_the_seed_button_follows_the_seed_guard():
    import inspect

    from shyfem_ui.pages import files

    src = inspect.getsource(files)
    assert "has_project_files(" in src
    assert 'summary["file_count"] == 0 and' not in src
