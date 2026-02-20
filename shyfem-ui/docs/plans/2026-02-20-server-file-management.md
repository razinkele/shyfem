# Server-Side File Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable browser-only users to upload, manage, and download all simulation data files through the SHYFEM-UI, with tutorial data pre-loaded from the server.

**Architecture:** Add a `ProjectFile` DB model as an inventory layer over the existing filesystem storage. A `FileService` handles upload, download, deletion, quota enforcement, and pre-flight validation. The STR editor gains file pickers populated from the inventory. Tutorial projects seed files from `testcases/examples/mar_menor/`.

**Tech Stack:** SQLAlchemy (model), Alembic (migration), pytest (TDD), existing Shiny/Flask UI patterns.

---

### Task 1: Add `ProjectFile` Model

**Files:**
- Modify: `shyfem-ui/shyfem_ui/models/project.py`
- Test: `shyfem-ui/tests/test_project_file_model.py`

**Step 1: Write the failing test**

Create `shyfem-ui/tests/test_project_file_model.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_project_file_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProjectFile'`

**Step 3: Write the model**

In `shyfem-ui/shyfem_ui/models/project.py`, add after the `Project` class (before `Grid`):

```python
class ProjectFile(Base):
    """A file tracked within a project."""

    __tablename__ = "project_files"
    __table_args__ = (
        Index("ix_project_files_project_id", "project_id"),
        Index("ix_project_files_file_type", "file_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="files")

    def __repr__(self) -> str:
        return f"<ProjectFile(id={self.id}, filename='{self.filename}', type='{self.file_type}')>"
```

Add the `files` relationship to the `Project` class:

```python
    files: Mapped[list["ProjectFile"]] = relationship(
        "ProjectFile", back_populates="project", cascade="all, delete-orphan"
    )
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_project_file_model.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/models/project.py shyfem-ui/tests/test_project_file_model.py
git commit -m "feat: add ProjectFile model with project relationship"
```

---

### Task 2: Alembic Migration for `project_files` Table

**Files:**
- Create: `shyfem-ui/migrations/versions/xxxx_add_project_files_table.py` (via alembic command)

**Step 1: Generate migration**

```bash
cd /home/razinka/shyfem/shyfem-ui
SHYFEM_UI_DATABASE_URL="sqlite:///./shyfem_ui.db" python -m alembic revision --autogenerate -m "add project_files table"
```

**Step 2: Review the generated migration**

Open the generated file in `migrations/versions/`. It should contain:

```python
def upgrade() -> None:
    op.create_table('project_files',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('rel_path', sa.String(length=1024), nullable=False),
        sa.Column('file_type', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('checksum', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('project_files', schema=None) as batch_op:
        batch_op.create_index('ix_project_files_project_id', ['project_id'], unique=False)
        batch_op.create_index('ix_project_files_file_type', ['file_type'], unique=False)

def downgrade() -> None:
    with op.batch_alter_table('project_files', schema=None) as batch_op:
        batch_op.drop_index('ix_project_files_file_type')
        batch_op.drop_index('ix_project_files_project_id')
    op.drop_table('project_files')
```

Verify `render_as_batch=True` is used (required for SQLite). If autogenerate missed the indexes, add them manually.

**Step 3: Apply migration to verify it works**

```bash
cd /home/razinka/shyfem/shyfem-ui
SHYFEM_UI_DATABASE_URL="sqlite:///./shyfem_ui.db" python -m alembic upgrade head
```

Expected: Migration applies without errors.

**Step 4: Commit**

```bash
git add shyfem-ui/migrations/versions/
git commit -m "feat: add alembic migration for project_files table"
```

---

### Task 3: Add `max_project_storage_mb` to Config

**Files:**
- Modify: `shyfem-ui/shyfem_ui/config.py`
- Test: `shyfem-ui/tests/test_config_storage.py`

**Step 1: Write the failing test**

Create `shyfem-ui/tests/test_config_storage.py`:

```python
"""Tests for project storage config."""

import pytest


class TestStorageConfig:

    def test_default_max_project_storage(self):
        from shyfem_ui.config import Config
        c = Config(shyfem_dir="/tmp/sf", work_dir="/tmp/w")
        assert c.max_project_storage_mb == 5000

    def test_override_via_env(self, monkeypatch):
        monkeypatch.setenv("SHYFEM_UI_MAX_PROJECT_STORAGE_MB", "2000")
        from shyfem_ui.config import Config
        c = Config(shyfem_dir="/tmp/sf", work_dir="/tmp/w")
        assert c.max_project_storage_mb == 2000
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_config_storage.py -v`
Expected: FAIL — `AttributeError: 'Config' has no attribute 'max_project_storage_mb'`

**Step 3: Add the field to Config**

In `shyfem-ui/shyfem_ui/config.py`, add after `max_upload_size_mb`:

```python
    max_project_storage_mb: int = Field(
        default=5000,
        description="Maximum total storage per project in MB"
    )
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_config_storage.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/config.py shyfem-ui/tests/test_config_storage.py
git commit -m "feat: add max_project_storage_mb config field"
```

---

### Task 4: Create `FileService` — Core Upload/Delete/List

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/file_service.py`
- Test: `shyfem-ui/tests/test_file_service.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_file_service.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_file_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shyfem_ui.services.file_service'`

**Step 3: Implement FileService**

Create `shyfem-ui/shyfem_ui/services/file_service.py`:

```python
"""File management service for project data files."""

import hashlib
from pathlib import Path, PurePosixPath

from shyfem_ui.config import get_config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Project, ProjectFile


class FileService:
    """Manages project files: upload, delete, list, validate."""

    @staticmethod
    def upload_file(
        project_id: int,
        file_data: bytes,
        filename: str,
        file_type: str,
        subdir: str | None = None,
    ) -> dict:
        """Upload a file to a project.

        Args:
            project_id: Project to add the file to.
            file_data: Raw file bytes.
            filename: Original filename (validated for safety).
            file_type: Category — grid, basin, str, forcing, boundary,
                       initial_condition, restart, config, output, other.
            subdir: Optional subdirectory within work_dir (e.g. "GRID", "INPUT").

        Returns:
            Dict with id, filename, rel_path, file_type, size_bytes, checksum.

        Raises:
            ValueError: On invalid filename, missing project, or quota exceeded.
        """
        # Validate filename — no path separators, no traversal
        safe_name = PurePosixPath(filename).name
        if safe_name != filename or not filename or ".." in filename:
            raise ValueError(f"Invalid filename: {filename!r}")

        config = get_config()
        size = len(file_data)

        with db_session() as db:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                raise ValueError(f"Project {project_id} not found")

            work_dir = Path(project.work_dir)

            # Check project storage quota
            current = _sum_project_bytes(db, project_id)
            limit = config.max_project_storage_mb * 1024 * 1024
            if current + size > limit:
                raise ValueError(
                    f"Upload would exceed project storage limit "
                    f"({config.max_project_storage_mb} MB)"
                )

            # Determine target path
            if subdir:
                # Validate subdir
                safe_sub = PurePosixPath(subdir)
                if ".." in safe_sub.parts:
                    raise ValueError(f"Invalid subdir: {subdir!r}")
                target_dir = work_dir / str(safe_sub)
                rel_path = f"{safe_sub}/{safe_name}"
            else:
                target_dir = work_dir
                rel_path = safe_name

            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / safe_name

            # Write file
            target.write_bytes(file_data)

            # Compute checksum
            checksum = hashlib.sha256(file_data).hexdigest()

            # Create DB record
            pf = ProjectFile(
                project_id=project_id,
                filename=safe_name,
                rel_path=rel_path,
                file_type=file_type,
                size_bytes=size,
                checksum=checksum,
            )
            db.add(pf)
            db.flush()

            return {
                "id": pf.id,
                "filename": pf.filename,
                "rel_path": pf.rel_path,
                "file_type": pf.file_type,
                "size_bytes": pf.size_bytes,
                "checksum": pf.checksum,
            }

    @staticmethod
    def delete_file(file_id: int) -> None:
        """Delete a file from disk and DB.

        Raises:
            ValueError: If file_id does not exist.
        """
        with db_session() as db:
            pf = db.query(ProjectFile).filter_by(id=file_id).first()
            if pf is None:
                raise ValueError(f"File {file_id} not found")

            project = db.query(Project).filter_by(id=pf.project_id).first()
            if project:
                disk_path = Path(project.work_dir) / pf.rel_path
                if disk_path.exists():
                    disk_path.unlink()

            db.delete(pf)

    @staticmethod
    def list_files(project_id: int, file_type: str | None = None) -> list[dict]:
        """List files in a project, optionally filtered by type.

        Returns:
            List of dicts with id, filename, rel_path, file_type, size_bytes,
            uploaded_at, checksum.
        """
        with db_session() as db:
            q = db.query(ProjectFile).filter_by(project_id=project_id)
            if file_type:
                q = q.filter_by(file_type=file_type)
            q = q.order_by(ProjectFile.filename)
            return [
                {
                    "id": pf.id,
                    "filename": pf.filename,
                    "rel_path": pf.rel_path,
                    "file_type": pf.file_type,
                    "size_bytes": pf.size_bytes,
                    "uploaded_at": pf.uploaded_at.isoformat() if pf.uploaded_at else None,
                    "checksum": pf.checksum,
                }
                for pf in q.all()
            ]

    @staticmethod
    def get_file_path(file_id: int) -> Path:
        """Get absolute path for a file (for download or job use).

        Raises:
            ValueError: If file_id does not exist.
        """
        with db_session() as db:
            pf = db.query(ProjectFile).filter_by(id=file_id).first()
            if pf is None:
                raise ValueError(f"File {file_id} not found")
            project = db.query(Project).filter_by(id=pf.project_id).first()
            return Path(project.work_dir) / pf.rel_path

    @staticmethod
    def get_project_storage(project_id: int) -> dict:
        """Get storage usage for a project.

        Returns:
            Dict with used_bytes and file_count.
        """
        with db_session() as db:
            total = _sum_project_bytes(db, project_id)
            count = db.query(ProjectFile).filter_by(project_id=project_id).count()
            return {"used_bytes": total, "file_count": count}


def _sum_project_bytes(db, project_id: int) -> int:
    """Sum size_bytes for all files in a project."""
    from sqlalchemy import func as sa_func
    result = (
        db.query(sa_func.coalesce(sa_func.sum(ProjectFile.size_bytes), 0))
        .filter_by(project_id=project_id)
        .scalar()
    )
    return int(result)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_file_service.py -v`
Expected: PASS (all 11 tests)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/file_service.py shyfem-ui/tests/test_file_service.py
git commit -m "feat: add FileService with upload, delete, list, quota"
```

---

### Task 5: Add `validate_simulation_files` to FileService

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/file_service.py`
- Test: `shyfem-ui/tests/test_file_service_validation.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_file_service_validation.py`:

```python
"""Tests for FileService.validate_simulation_files."""

import pytest
from pathlib import Path


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
def sim_project(tmp_path):
    """Create a project with a simulation and STR file."""
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project, Simulation

    work = tmp_path / "projects" / "val_proj"
    work.mkdir(parents=True)

    str_content = """$title
    Validation test
    val_sim
    GRID/mesh
$end

$para
    itanf = '2020-01-01'
    itend = '2020-01-02'
    idt = 300
$end

$name
    wind = 'INPUT/wind.fem'
    gotmpa = 'gotmturb.nml'
$end

$bound1
    kbound = 1 2 3
    ibtyp = 1
    boundn = 'INPUT/levels.dat'
    tempn = 'INPUT/temp_bnd.fem'
$end
"""
    (work / "val_sim.str").write_text(str_content)

    with db_session() as db:
        p = Project(name="val_proj", work_dir=str(work))
        db.add(p)
        db.flush()
        s = Simulation(
            project_id=p.id, name="val_sim",
            str_file="val_sim.str",
        )
        db.add(s)
        db.flush()
        return {"project_id": p.id, "sim_id": s.id, "work": work}


class TestValidateSimulationFiles:

    def test_all_missing_returns_warnings(self, sim_project):
        from shyfem_ui.services.file_service import FileService
        warnings = FileService.validate_simulation_files(sim_project["sim_id"])
        # wind, gotmpa, boundn, tempn, basin — all missing
        assert len(warnings) >= 4

    def test_no_warnings_when_all_present(self, sim_project):
        from shyfem_ui.services.file_service import FileService
        work = sim_project["work"]

        # Create all referenced files
        (work / "INPUT").mkdir(exist_ok=True)
        (work / "GRID").mkdir(exist_ok=True)
        (work / "INPUT" / "wind.fem").write_text("data")
        (work / "gotmturb.nml").write_text("data")
        (work / "INPUT" / "levels.dat").write_text("data")
        (work / "INPUT" / "temp_bnd.fem").write_text("data")
        (work / "GRID" / "mesh.bas").write_text("data")

        warnings = FileService.validate_simulation_files(sim_project["sim_id"])
        assert len(warnings) == 0

    def test_partial_missing(self, sim_project):
        from shyfem_ui.services.file_service import FileService
        work = sim_project["work"]

        # Create some but not all
        (work / "INPUT").mkdir(exist_ok=True)
        (work / "INPUT" / "wind.fem").write_text("data")
        (work / "gotmturb.nml").write_text("data")

        warnings = FileService.validate_simulation_files(sim_project["sim_id"])
        # levels.dat, temp_bnd.fem, basin still missing
        assert len(warnings) >= 2
        assert any("levels.dat" in w for w in warnings)

    def test_invalid_sim_id_raises(self):
        from shyfem_ui.services.file_service import FileService
        with pytest.raises(ValueError, match="not found"):
            FileService.validate_simulation_files(99999)

    def test_str_with_no_file_refs(self, tmp_path):
        """STR with only $para returns no warnings."""
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, Simulation
        from shyfem_ui.services.file_service import FileService

        work = tmp_path / "projects" / "minimal"
        work.mkdir(parents=True)
        (work / "minimal.str").write_text(
            "$title\nMinimal\nminimal\nGRID/m\n$end\n"
            "$para\nidt = 300\n$end\n"
        )
        (work / "GRID").mkdir()
        (work / "GRID" / "m.bas").write_text("data")

        with db_session() as db:
            p = Project(name="minimal", work_dir=str(work))
            db.add(p)
            db.flush()
            s = Simulation(project_id=p.id, name="minimal", str_file="minimal.str")
            db.add(s)
            db.flush()
            sid = s.id

        warnings = FileService.validate_simulation_files(sid)
        assert len(warnings) == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_file_service_validation.py -v`
Expected: FAIL — `AttributeError: type object 'FileService' has no attribute 'validate_simulation_files'`

**Step 3: Implement validate_simulation_files**

Add to `file_service.py` inside the `FileService` class:

```python
    # Parameters in $name that reference files
    _NAME_FILE_PARAMS = frozenset({
        "wind", "rain", "qflux", "ice", "zinit", "tempin", "saltin",
        "conzin", "restrt", "tempobs", "saltobs", "gotmpa", "basnam",
        "offlin", "surfvel", "temptau", "salttau",
    })

    # Parameters in $bound sections that reference files
    _BOUND_FILE_PARAMS = frozenset({
        "boundn", "tempn", "saltn", "conzn", "vel3dn", "bio2dn", "sed2dn",
    })

    @classmethod
    def validate_simulation_files(cls, simulation_id: int) -> list[str]:
        """Check that all files referenced in the STR exist on disk.

        Args:
            simulation_id: Simulation whose STR file to validate.

        Returns:
            List of warning strings for missing files (empty = all OK).

        Raises:
            ValueError: If simulation_id does not exist.
        """
        from shyfem_ui.services.parser_str import StrParser

        with db_session() as db:
            from shyfem_ui.models.project import Simulation
            sim = db.query(Simulation).filter_by(id=simulation_id).first()
            if sim is None:
                raise ValueError(f"Simulation {simulation_id} not found")

            project = db.query(Project).filter_by(id=sim.project_id).first()
            work_dir = Path(project.work_dir)
            str_path = work_dir / sim.str_file

        if not str_path.exists():
            return [f"STR file not found: {sim.str_file}"]

        parsed = StrParser.parse_file(str_path)
        warnings = []

        # Check $name file references
        name_section = parsed.sections.get("name")
        if name_section:
            for param, value in name_section.parameters.items():
                if param in cls._NAME_FILE_PARAMS and isinstance(value, str) and value:
                    path = work_dir / value
                    if not path.exists():
                        warnings.append(
                            f"Missing file for $name/{param}: {value}"
                        )

        # Check $bound sections
        for sec_name, section in parsed.sections.items():
            if not sec_name.startswith("bound"):
                continue
            for param, value in section.parameters.items():
                if param in cls._BOUND_FILE_PARAMS and isinstance(value, str) and value:
                    path = work_dir / value
                    if not path.exists():
                        warnings.append(
                            f"Missing file for ${sec_name}/{param}: {value}"
                        )

        # Check basin file from $title (3rd line = basin name)
        title_section = parsed.sections.get("title")
        if title_section and title_section.raw_lines:
            # Basin name is typically the 3rd non-empty non-comment line
            content_lines = [
                ln.strip() for ln in title_section.raw_lines
                if ln.strip() and not ln.strip().startswith(("#", "!"))
            ]
            if len(content_lines) >= 3:
                basin_name = content_lines[2]
                bas_path = work_dir / (basin_name + ".bas")
                if not bas_path.exists():
                    warnings.append(
                        f"Missing basin file: {basin_name}.bas"
                    )

        return warnings
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_file_service_validation.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/file_service.py shyfem-ui/tests/test_file_service_validation.py
git commit -m "feat: add pre-flight file validation for simulations"
```

---

### Task 6: Add `seed_tutorial_files` to FileService

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/file_service.py`
- Test: `shyfem-ui/tests/test_file_service_seed.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_file_service_seed.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_file_service_seed.py -v`
Expected: FAIL — `AttributeError: type object 'FileService' has no attribute 'seed_tutorial_files'`

**Step 3: Implement seed_tutorial_files**

Add to `file_service.py` inside the `FileService` class:

```python
    # Extensions to skip when seeding tutorial files
    _SKIP_EXTENSIONS = frozenset({".sh", ".stdout", ".stderr"})
    _SKIP_FILENAMES = frozenset({"Makefile", "README", "util.sh", "run_all.sh"})

    # Map file extension / path to file_type
    @staticmethod
    def _infer_file_type(rel_path: str) -> str:
        """Infer file_type from path and extension."""
        p = PurePosixPath(rel_path)
        ext = p.suffix.lower()
        name = p.name.lower()
        parts = p.parts

        if ext == ".grd":
            return "grid"
        if ext == ".bas":
            return "basin"
        if ext == ".str":
            return "str"
        if ext == ".rst":
            return "restart"
        if ext == ".nml":
            return "config"
        if ext in (".shy", ".ext", ".flx", ".nc"):
            return "output"
        # Subdirectory hints
        if len(parts) > 1 and parts[0].upper() == "INPUT":
            return "forcing"
        return "other"

    @classmethod
    def seed_tutorial_files(cls, project_id: int) -> None:
        """Copy Mar Menor tutorial files into a project.

        Copies grid, input, and STR files from testcases/examples/mar_menor/
        into the project work directory and creates ProjectFile records.

        Args:
            project_id: Target project.

        Raises:
            ValueError: If project not found or tutorial data missing.
        """
        import shutil

        config = get_config()
        tutorial_dir = config.shyfem_dir / "testcases" / "examples" / "mar_menor"
        if not tutorial_dir.exists():
            raise ValueError(f"Tutorial data not found: {tutorial_dir}")

        with db_session() as db:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            work_dir = Path(project.work_dir)

        # Walk tutorial directory and copy relevant files
        for src_file in sorted(tutorial_dir.rglob("*")):
            if not src_file.is_file():
                continue
            if src_file.suffix in cls._SKIP_EXTENSIONS:
                continue
            if src_file.name in cls._SKIP_FILENAMES:
                continue
            # Skip output/partition files
            if src_file.name.startswith("partition."):
                continue
            if src_file.suffix in (".inf",):
                continue
            # Skip large output files
            if ".hydro." in src_file.name or ".ext" == src_file.suffix:
                if src_file.stat().st_size > 100_000:
                    continue

            rel = src_file.relative_to(tutorial_dir)
            rel_str = str(rel)
            dest = work_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)

            file_type = cls._infer_file_type(rel_str)
            file_data = src_file.read_bytes()
            checksum = hashlib.sha256(file_data).hexdigest()

            with db_session() as db:
                pf = ProjectFile(
                    project_id=project_id,
                    filename=src_file.name,
                    rel_path=rel_str,
                    file_type=file_type,
                    size_bytes=len(file_data),
                    checksum=checksum,
                )
                db.add(pf)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_file_service_seed.py -v`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/file_service.py shyfem-ui/tests/test_file_service_seed.py
git commit -m "feat: add tutorial file seeding from testcases/mar_menor"
```

---

### Task 7: Update `project_context` to Include Files

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/project_context.py`
- Test: `shyfem-ui/tests/test_project_context.py` (extend existing)

**Step 1: Write the failing test**

Add to `shyfem-ui/tests/test_project_context.py`, in the existing test class:

```python
    def test_context_includes_files(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, ProjectFile
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="files_proj", work_dir=str(tmp_path / "fp"))
            db.add(p)
            db.flush()
            pf = ProjectFile(
                project_id=p.id, filename="wind.fem",
                rel_path="INPUT/wind.fem", file_type="forcing", size_bytes=100,
            )
            db.add(pf)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid)
        assert "files" in ctx
        assert len(ctx["files"]) == 1
        assert ctx["files"][0]["filename"] == "wind.fem"
        assert ctx["files"][0]["file_type"] == "forcing"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_project_context.py -v -k files`
Expected: FAIL — `KeyError: 'files'`

**Step 3: Update load_project_context**

In `shyfem-ui/shyfem_ui/services/project_context.py`:

```python
from shyfem_ui.models.project import Grid, Project, ProjectFile, Simulation

def load_project_context(project_id: int) -> dict | None:
    with db_session() as db:
        project = db.query(Project).filter_by(id=project_id).first()
        if project is None:
            return None
        grids = db.query(Grid).filter_by(project_id=project_id).all()
        sims = db.query(Simulation).filter_by(project_id=project_id).all()
        files = db.query(ProjectFile).filter_by(project_id=project_id).order_by(ProjectFile.filename).all()
        return {
            "id": project.id,
            "name": project.name,
            "work_dir": project.work_dir,
            "description": project.description,
            "grids": [
                {"name": g.name, "grd_file": g.grd_file, "bas_file": g.bas_file}
                for g in grids
            ],
            "simulations": [
                {"name": s.name, "str_file": s.str_file}
                for s in sims
            ],
            "files": [
                {
                    "id": f.id,
                    "filename": f.filename,
                    "rel_path": f.rel_path,
                    "file_type": f.file_type,
                    "size_bytes": f.size_bytes,
                }
                for f in files
            ],
        }
```

**Step 4: Run all project_context tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_project_context.py -v`
Expected: PASS (existing tests + new test)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/project_context.py shyfem-ui/tests/test_project_context.py
git commit -m "feat: include project files in project context"
```

---

### Task 8: Update `project_export` to Include File Inventory in Manifest

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/project_export.py`
- Modify: `shyfem-ui/tests/test_project_export.py` (extend existing)

**Step 1: Write the failing test**

Add to the existing `TestExport` class in `tests/test_project_export.py`:

```python
    def test_manifest_includes_file_inventory(self, project_dir, project_meta):
        import json
        import zipfile

        project_meta["files"] = [
            {"filename": "wind.txt", "rel_path": "INPUT/wind.txt",
             "file_type": "forcing", "size_bytes": 9},
        ]
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert "files" in manifest
            assert len(manifest["files"]) == 1
            assert manifest["files"][0]["filename"] == "wind.txt"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_project_export.py -v -k manifest_includes_file`
Expected: FAIL — `KeyError: 'files'` in manifest

**Step 3: Update export_project**

In `project_export.py`, add `files` to the manifest dict:

```python
        manifest = {
            "version": MANIFEST_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "project": {
                "name": project_meta["name"],
                "description": project_meta.get("description"),
            },
            "grids": project_meta.get("grids", []),
            "simulations": project_meta.get("simulations", []),
            "files": project_meta.get("files", []),
        }
```

**Step 4: Run all export tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/test_project_export.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/project_export.py shyfem-ui/tests/test_project_export.py
git commit -m "feat: include file inventory in project export manifest"
```

---

### Task 9: Run Full Test Suite

**Step 1: Run all unit tests**

```bash
cd /home/razinka/shyfem/shyfem-ui && python -m pytest tests/ -v --ignore=tests/test_playwright*.py
```

Expected: All tests PASS. If any existing tests fail due to the new `ProjectFile` model, fix the DB initialization in their fixtures.

**Step 2: Commit any fixes**

If needed:

```bash
git add -u
git commit -m "fix: update test fixtures for ProjectFile model compatibility"
```

---

### Summary

| Task | What | Test Count |
|------|------|------------|
| 1 | ProjectFile model + Project.files relationship | 4 |
| 2 | Alembic migration | (manual verification) |
| 3 | max_project_storage_mb config | 2 |
| 4 | FileService: upload, delete, list, get_path, storage | 11 |
| 5 | FileService: validate_simulation_files | 5 |
| 6 | FileService: seed_tutorial_files | 6 |
| 7 | project_context includes files | 1+ |
| 8 | project_export manifest includes files | 1+ |
| 9 | Full test suite verification | all |

**Total new tests: ~30**

**Not in scope for this plan** (future tasks):
- UI page changes (file upload widget, file list, download buttons on home/simulation/run pages)
- STR editor file picker integration
- Pre-flight validation UI on Run page

These UI changes should be planned separately once the backend service layer is solid and tested.
