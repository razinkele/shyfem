"""Tests for ProjectFile model."""

import pytest
from datetime import datetime


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Isolated DB for each test."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path))
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


class TestProjectFileModel:

    def test_create_project_file(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, ProjectFile

        with db_session() as db:
            p = Project(name="test_proj", work_dir=str(tmp_path / "proj"))
            db.add(p)
            db.flush()
            pf = ProjectFile(
                project_id=p.id,
                filename="wind.fem",
                rel_path="INPUT/wind.fem",
                file_type="forcing",
                size_bytes=1024,
            )
            db.add(pf)
            db.flush()
            assert pf.id is not None
            assert pf.uploaded_at is not None

    def test_project_files_relationship(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, ProjectFile

        with db_session() as db:
            p = Project(name="test_proj2", work_dir=str(tmp_path / "proj2"))
            db.add(p)
            db.flush()
            pf1 = ProjectFile(
                project_id=p.id, filename="wind.fem",
                rel_path="INPUT/wind.fem", file_type="forcing", size_bytes=100,
            )
            pf2 = ProjectFile(
                project_id=p.id, filename="mesh.grd",
                rel_path="GRID/mesh.grd", file_type="grid", size_bytes=200,
            )
            db.add_all([pf1, pf2])
            db.flush()
            assert len(p.files) == 2

    def test_cascade_delete(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, ProjectFile

        with db_session() as db:
            p = Project(name="test_proj3", work_dir=str(tmp_path / "proj3"))
            db.add(p)
            db.flush()
            pf = ProjectFile(
                project_id=p.id, filename="data.fem",
                rel_path="data.fem", file_type="other", size_bytes=50,
            )
            db.add(pf)
            db.flush()
            pid = p.id

        with db_session() as db:
            p = db.query(Project).filter_by(id=pid).first()
            db.delete(p)

        with db_session() as db:
            orphans = db.query(ProjectFile).filter_by(project_id=pid).all()
            assert len(orphans) == 0

    def test_file_type_values(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, ProjectFile

        valid_types = [
            "grid", "basin", "str", "forcing", "boundary",
            "initial_condition", "restart", "config", "output", "other",
        ]
        with db_session() as db:
            p = Project(name="test_types", work_dir=str(tmp_path / "proj_t"))
            db.add(p)
            db.flush()
            for i, ft in enumerate(valid_types):
                pf = ProjectFile(
                    project_id=p.id, filename=f"f{i}.dat",
                    rel_path=f"f{i}.dat", file_type=ft, size_bytes=10,
                )
                db.add(pf)
            db.flush()
            assert len(p.files) == len(valid_types)
