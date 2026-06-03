"""Tests for file_picker component helpers."""

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


@pytest.fixture
def project_with_files(tmp_path):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project
    from shyfem_ui.services.file_service import FileService

    work = tmp_path / "projects" / "picker_proj"
    work.mkdir(parents=True)
    with db_session() as db:
        p = Project(name="picker_proj", work_dir=str(work))
        db.add(p)
        db.flush()
        pid = p.id

    FileService.upload_file(pid, b"wind data", "wind.fem", "forcing", subdir="INPUT")
    FileService.upload_file(pid, b"temp data", "temp.fem", "forcing", subdir="INPUT")
    FileService.upload_file(pid, b"grid data", "mesh.grd", "grid", subdir="GRID")
    FileService.upload_file(pid, b"basin data", "mesh.bas", "basin", subdir="GRID")
    FileService.upload_file(pid, b"level data", "levels.dat", "boundary", subdir="INPUT")
    return pid


class TestBuildFileChoices:

    def test_returns_all_files_no_filter(self, project_with_files):
        from shyfem_ui.components.file_picker import build_file_choices
        choices = build_file_choices(project_with_files)
        assert len(choices) == 5

    def test_filters_by_single_type(self, project_with_files):
        from shyfem_ui.components.file_picker import build_file_choices
        choices = build_file_choices(project_with_files, file_types=["forcing"])
        assert len(choices) == 2
        assert all("INPUT/" in v for v in choices.values())

    def test_filters_by_multiple_types(self, project_with_files):
        from shyfem_ui.components.file_picker import build_file_choices
        choices = build_file_choices(project_with_files, file_types=["forcing", "boundary"])
        assert len(choices) == 3

    def test_returns_rel_path_as_value(self, project_with_files):
        from shyfem_ui.components.file_picker import build_file_choices
        choices = build_file_choices(project_with_files, file_types=["grid"])
        values = list(choices.values())
        assert "GRID/mesh.grd" in values

    def test_empty_project_returns_empty(self, tmp_path):
        from shyfem_ui.components.file_picker import build_file_choices
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project

        work = tmp_path / "projects" / "empty"
        work.mkdir(parents=True)
        with db_session() as db:
            p = Project(name="empty", work_dir=str(work))
            db.add(p)
            db.flush()
            pid = p.id
        choices = build_file_choices(pid)
        assert len(choices) == 0

    def test_none_project_returns_empty(self):
        from shyfem_ui.components.file_picker import build_file_choices
        choices = build_file_choices(None)
        assert len(choices) == 0


class TestFileTypeMapping:

    def test_param_to_file_types_wind(self):
        from shyfem_ui.components.file_picker import param_to_file_types
        assert param_to_file_types("wind") == ["forcing"]

    def test_param_to_file_types_boundn(self):
        from shyfem_ui.components.file_picker import param_to_file_types
        assert param_to_file_types("boundn") == ["boundary", "forcing"]

    def test_param_to_file_types_restrt(self):
        from shyfem_ui.components.file_picker import param_to_file_types
        assert param_to_file_types("restrt") == ["restart"]

    def test_param_to_file_types_gotmpa(self):
        from shyfem_ui.components.file_picker import param_to_file_types
        assert param_to_file_types("gotmpa") == ["config"]

    def test_param_to_file_types_tempin(self):
        from shyfem_ui.components.file_picker import param_to_file_types
        assert param_to_file_types("tempin") == ["initial_condition", "forcing"]

    def test_param_to_file_types_unknown(self):
        from shyfem_ui.components.file_picker import param_to_file_types
        assert param_to_file_types("unknown_param") is None


class TestIsFileParam:

    def test_wind_is_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("wind") is True

    def test_boundn_is_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("boundn") is True

    def test_idt_is_not_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("idt") is False
