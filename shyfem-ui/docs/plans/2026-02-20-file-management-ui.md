# File Management UI Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Enable browser-only users to upload, browse, download, and delete project files; select files from dropdowns in the STR editor; and validate file references before job submission.

**Architecture:** Two reusable Shiny module components (`file_picker`, enhanced `file_browser`) wired into three page integration points (new Files tab, STR editor, Run page). All persistence goes through the existing `FileService` backed by the `ProjectFile` DB model.

**Tech Stack:** Shiny for Python (modules, reactive values), FileService (SQLAlchemy), Bootstrap 5 (UI), pytest (TDD).

---

### Task 1: Enhance `file_browser` Component with Project Persistence

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/file_browser.py`
- Test: `shyfem-ui/tests/test_file_browser_persist.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_file_browser_persist.py`:

```python
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

        # Create a temporary upload file (simulating Shiny's temp path)
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

        # 11MB file exceeds 10MB quota
        temp = tmp_path / "upload_tmp" / "big.dat"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(b"x" * (11 * 1024 * 1024))

        result = persist_upload(
            temp_path=temp,
            filename="big.dat",
            project_id=pid,
            file_type="other",
        )
        # Returns None on quota error (not an exception — UI shows notification)
        assert result is None

    def test_infer_file_type_from_extension(self):
        from shyfem_ui.components.file_browser import infer_file_type
        assert infer_file_type("mesh.grd") == "grid"
        assert infer_file_type("domain.bas") == "basin"
        assert infer_file_type("sim.str") == "str"
        assert infer_file_type("gotmturb.nml") == "config"
        assert infer_file_type("data.txt") == "other"
        assert infer_file_type("INPUT/wind.fem") == "forcing"
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_browser_persist.py -v`
Expected: FAIL — `ImportError: cannot import name 'persist_upload'`

**Step 3: Implement `persist_upload` and `infer_file_type`**

Add to `shyfem-ui/shyfem_ui/components/file_browser.py`, after the existing `validate_upload` function:

```python
def infer_file_type(filename: str) -> str:
    """Infer file_type category from filename/path."""
    from pathlib import PurePosixPath
    p = PurePosixPath(filename)
    ext = p.suffix.lower()
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
    if ext in (".shy", ".nc"):
        return "output"
    # Subdirectory hint
    if len(p.parts) > 1 and p.parts[0].upper() == "INPUT":
        return "forcing"
    return "other"


def persist_upload(
    temp_path: Path,
    filename: str,
    project_id: int | None,
    file_type: str | None = None,
    subdir: str | None = None,
) -> dict | None:
    """Persist an uploaded file to a project via FileService.

    Args:
        temp_path: Path to the temporary uploaded file.
        filename: Original filename.
        project_id: Target project ID. If None, returns None (no persistence).
        file_type: File category. If None, inferred from filename.
        subdir: Optional subdirectory within project work_dir.

    Returns:
        ProjectFile dict on success, None if project_id is None or on error.
    """
    if project_id is None:
        return None

    if file_type is None:
        file_type = infer_file_type(filename)

    try:
        from shyfem_ui.services.file_service import FileService
        file_data = temp_path.read_bytes()
        return FileService.upload_file(
            project_id=project_id,
            file_data=file_data,
            filename=filename,
            file_type=file_type,
            subdir=subdir,
        )
    except Exception:
        logger.warning("Failed to persist upload %s to project %s", filename, project_id, exc_info=True)
        return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_browser_persist.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/file_browser.py shyfem-ui/tests/test_file_browser_persist.py
git commit -m "feat: add persist_upload and infer_file_type to file_browser"
```

---

### Task 2: Create `file_picker` Component

**Files:**
- Create: `shyfem-ui/shyfem_ui/components/file_picker.py`
- Test: `shyfem-ui/tests/test_file_picker.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_file_picker.py`:

```python
"""Tests for file_picker component helpers."""

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
        # Key = display label, value = rel_path
        values = list(choices.values())
        assert "GRID/mesh.grd" in values

    def test_empty_project_returns_empty(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.components.file_picker import build_file_choices

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
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_picker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shyfem_ui.components.file_picker'`

**Step 3: Implement `file_picker` component**

Create `shyfem-ui/shyfem_ui/components/file_picker.py`:

```python
"""File picker component for selecting project files in forms."""

import logging
from collections.abc import Callable

from shiny import module, reactive, render, ui

logger = logging.getLogger(__name__)

# STR parameters that reference files — from FileService
_NAME_FILE_PARAMS = frozenset({
    "wind", "rain", "qflux", "ice", "zinit", "tempin", "saltin",
    "conzin", "restrt", "tempobs", "saltobs", "gotmpa", "basnam",
    "offlin", "surfvel", "temptau", "salttau",
})

_BOUND_FILE_PARAMS = frozenset({
    "boundn", "tempn", "saltn", "conzn", "vel3dn", "bio2dn", "sed2dn",
})

# Parameter → file_types filter mapping
_PARAM_TYPE_MAP = {
    # Forcing files
    "wind": ["forcing"], "rain": ["forcing"], "qflux": ["forcing"],
    "ice": ["forcing"], "surfvel": ["forcing"],
    # Boundary + forcing
    "boundn": ["boundary", "forcing"], "tempn": ["boundary", "forcing"],
    "saltn": ["boundary", "forcing"], "conzn": ["boundary", "forcing"],
    "vel3dn": ["boundary", "forcing"], "bio2dn": ["boundary", "forcing"],
    "sed2dn": ["boundary", "forcing"],
    # Initial conditions
    "zinit": ["initial_condition", "forcing"],
    "tempin": ["initial_condition", "forcing"],
    "saltin": ["initial_condition", "forcing"],
    "conzin": ["initial_condition", "forcing"],
    # Restart
    "restrt": ["restart"],
    # Config
    "gotmpa": ["config"],
    # Observations
    "tempobs": ["forcing"], "saltobs": ["forcing"],
    "temptau": ["forcing"], "salttau": ["forcing"],
    # Other
    "basnam": ["basin"], "offlin": ["forcing"],
}


def is_file_param(param_name: str) -> bool:
    """Check if an STR parameter name references a file."""
    return param_name in _NAME_FILE_PARAMS or param_name in _BOUND_FILE_PARAMS


def param_to_file_types(param_name: str) -> list[str] | None:
    """Map an STR parameter name to file_types filter for the picker.

    Returns None if the parameter is not a file parameter.
    """
    return _PARAM_TYPE_MAP.get(param_name)


def build_file_choices(
    project_id: int | None,
    file_types: list[str] | None = None,
) -> dict:
    """Build {display_label: rel_path} choices from project files.

    Args:
        project_id: Project to list files from. None returns empty dict.
        file_types: Optional filter by file type categories.

    Returns:
        Dict mapping "filename (type)" display labels to rel_path values.
    """
    if project_id is None:
        return {}

    from shyfem_ui.services.file_service import FileService

    if file_types:
        files = []
        for ft in file_types:
            files.extend(FileService.list_files(project_id, file_type=ft))
        # Deduplicate by id
        seen = set()
        unique = []
        for f in files:
            if f["id"] not in seen:
                seen.add(f["id"])
                unique.append(f)
        files = unique
    else:
        files = FileService.list_files(project_id)

    choices = {}
    for f in sorted(files, key=lambda x: x["rel_path"]):
        label = f"{f['filename']} ({f['file_type']})"
        choices[label] = f["rel_path"]
    return choices


@module.ui
def file_picker_ui(label: str = "Select File"):
    """File picker UI — dropdown with browse button."""
    return ui.div(
        ui.div(
            ui.div(
                ui.input_select(
                    "file_select",
                    label,
                    choices={"": "No files available"},
                    width="100%",
                ),
                class_="flex-grow-1",
            ),
            ui.div(
                ui.input_action_button(
                    "browse_btn",
                    "Browse...",
                    class_="btn-sm btn-outline-secondary mt-4",
                ),
                class_="ms-2",
            ),
            class_="d-flex align-items-start",
        ),
        class_="file-picker-component",
    )


@module.server
def file_picker_server(
    input,
    output,
    session,
    project_id: reactive.Value | None = None,
    file_types: list[str] | None = None,
    on_selected: Callable[[str], None] | None = None,
):
    """File picker server logic.

    Args:
        project_id: Reactive value with current project ID.
        file_types: Filter file list by these types.
        on_selected: Callback fired with rel_path when selection changes.

    Returns:
        reactive.Value[str] — current selected rel_path.
    """
    selected_path = reactive.value("")

    @reactive.effect
    def _update_choices():
        pid = project_id.get() if project_id else None
        choices = build_file_choices(pid, file_types=file_types)
        if choices:
            ui.update_select(
                "file_select",
                choices={"": "-- Select file --", **choices},
            )
        else:
            ui.update_select(
                "file_select",
                choices={"": "No files available"},
            )

    @reactive.effect
    @reactive.event(input.file_select)
    def _on_selection():
        val = input.file_select()
        if val:
            selected_path.set(val)
            if on_selected:
                on_selected(val)

    @reactive.effect
    @reactive.event(input.browse_btn)
    def _show_browse_modal():
        pid = project_id.get() if project_id else None
        if pid is None:
            ui.notification_show("No active project. Select a project first.", type="warning")
            return

        from shyfem_ui.services.file_service import FileService
        files = FileService.list_files(pid)

        rows = []
        for f in files:
            size_str = _format_size(f["size_bytes"])
            type_badge = ui.span(f["file_type"], class_="badge bg-secondary")
            select_btn = ui.input_action_button(
                f"pick_{f['id']}",
                "Select",
                class_="btn-sm btn-outline-primary",
            )
            rows.append(
                ui.tags.tr(
                    ui.tags.td(f["filename"]),
                    ui.tags.td(type_badge),
                    ui.tags.td(f["rel_path"]),
                    ui.tags.td(size_str),
                    ui.tags.td(select_btn),
                )
            )

        table = ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Name"),
                    ui.tags.th("Type"),
                    ui.tags.th("Path"),
                    ui.tags.th("Size"),
                    ui.tags.th(""),
                )
            ),
            ui.tags.tbody(*rows),
            class_="table table-sm table-hover",
        ) if rows else ui.p("No files in project. Upload files first.", class_="text-muted")

        m = ui.modal(
            table,
            title="Browse Project Files",
            size="l",
            easy_close=True,
        )
        ui.modal_show(m)

        # Register click handlers for each file's select button
        for f in files:
            _register_pick_handler(f["id"], f["rel_path"])

    def _register_pick_handler(file_id: int, rel_path: str):
        btn_id = f"pick_{file_id}"

        @reactive.effect
        @reactive.event(getattr(input, btn_id))
        def _pick():
            selected_path.set(rel_path)
            # Update dropdown to match
            choices = build_file_choices(
                project_id.get() if project_id else None,
                file_types=file_types,
            )
            ui.update_select("file_select", choices={"": "-- Select file --", **choices}, selected=rel_path)
            if on_selected:
                on_selected(rel_path)
            ui.modal_remove()

    return selected_path


def _format_size(size: int) -> str:
    """Format byte count as human-readable string."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_picker.py -v`
Expected: PASS (all 12 tests)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/file_picker.py shyfem-ui/tests/test_file_picker.py
git commit -m "feat: add file_picker component with browse modal"
```

---

### Task 3: Create Files Page (New Tab)

**Files:**
- Create: `shyfem-ui/shyfem_ui/pages/files.py`
- Modify: `shyfem-ui/shyfem_ui/app.py:482-492` (add tab), `shyfem-ui/shyfem_ui/app.py:535-551` (wire server)
- Test: `shyfem-ui/tests/test_files_page.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_files_page.py`:

```python
"""Tests for Files page helpers."""

import pytest
from pathlib import Path


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
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_files_page.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shyfem_ui.pages.files'`

**Step 3: Implement `files.py` page**

Create `shyfem-ui/shyfem_ui/pages/files.py`:

```python
"""Project file management page — upload, browse, download, delete."""

import base64
import logging

from shiny import module, reactive, render, ui

from shyfem_ui.config import Config, get_config
from shyfem_ui.services.file_service import FileService

logger = logging.getLogger(__name__)

# File type badge colors
_TYPE_COLORS = {
    "grid": "bg-primary",
    "basin": "bg-info",
    "str": "bg-success",
    "forcing": "bg-warning text-dark",
    "boundary": "bg-danger",
    "initial_condition": "bg-secondary",
    "restart": "bg-dark",
    "config": "bg-light text-dark",
    "output": "bg-primary",
    "other": "bg-secondary",
}


def _format_size(size: int) -> str:
    """Format byte count as human-readable string."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _build_file_table_data(
    project_id: int,
    file_type: str | None = None,
) -> list[dict]:
    """Build file table rows from FileService.

    Returns list of dicts with id, filename, file_type, rel_path, size_str,
    size_bytes, uploaded_at.
    """
    files = FileService.list_files(project_id, file_type=file_type)
    return [
        {
            "id": f["id"],
            "filename": f["filename"],
            "file_type": f["file_type"],
            "rel_path": f["rel_path"],
            "size_str": _format_size(f["size_bytes"]),
            "size_bytes": f["size_bytes"],
            "uploaded_at": f.get("uploaded_at", ""),
        }
        for f in files
    ]


def _storage_summary(project_id: int) -> dict:
    """Get storage usage summary for a project."""
    config = get_config()
    storage = FileService.get_project_storage(project_id)
    limit_bytes = config.max_project_storage_mb * 1024 * 1024
    used = storage["used_bytes"]
    pct = round(used / limit_bytes * 100, 1) if limit_bytes > 0 else 0
    return {
        "used_bytes": used,
        "used_str": _format_size(used),
        "limit_bytes": limit_bytes,
        "limit_str": _format_size(limit_bytes),
        "file_count": storage["file_count"],
        "usage_pct": min(pct, 100),
    }


def _has_tutorial_data() -> bool:
    """Check if Mar Menor tutorial data exists on the server."""
    config = get_config()
    tutorial_dir = config.shyfem_dir / "testcases" / "examples" / "mar_menor"
    return tutorial_dir.exists()


@module.ui
def files_ui():
    """Project files page UI."""
    return ui.div(
        ui.h3("Project Files"),
        ui.p("Upload, browse, and manage data files for the active project.", class_="text-muted"),
        ui.output_ui("files_content"),
    )


@module.server
def files_server(
    input,
    output,
    session,
    config: Config,
    active_project=None,
):
    """Project files page server logic."""
    # Refresh trigger — increment to force re-render
    refresh_trigger = reactive.value(0)
    current_filter = reactive.value(None)  # None = all types

    @render.ui
    def files_content():
        _ = refresh_trigger.get()  # dependency
        if active_project is None:
            return ui.div(
                ui.p("No project selected. Go to Dashboard and select or create a project.",
                     class_="text-muted text-center p-5"),
            )
        proj = active_project.get()
        if proj is None:
            return ui.div(
                ui.p("No project selected. Go to Dashboard and select or create a project.",
                     class_="text-muted text-center p-5"),
            )

        pid = proj["id"]
        ft = current_filter.get()

        # Storage summary
        summary = _storage_summary(pid)
        storage_bar = ui.div(
            ui.div(
                ui.span(f"Storage: {summary['used_str']} / {summary['limit_str']}", class_="small fw-bold"),
                ui.span(f" ({summary['file_count']} files)", class_="small text-muted"),
            ),
            ui.div(
                ui.div(
                    ui.div(
                        class_="progress-bar",
                        style=f"width: {summary['usage_pct']}%",
                        role="progressbar",
                    ),
                    class_="progress",
                    style="height: 8px;",
                ),
                class_="mt-1",
            ),
            class_="mb-3",
        )

        # Type filter buttons
        type_buttons = []
        for label, type_val in [("All", None), ("Grid", "grid"), ("Forcing", "forcing"),
                                 ("Boundary", "boundary"), ("STR", "str"),
                                 ("Config", "config"), ("Other", "other")]:
            active = "btn-primary" if ft == type_val else "btn-outline-secondary"
            type_buttons.append(
                ui.input_action_button(
                    f"filter_{label.lower()}",
                    label,
                    class_=f"btn-sm {active} me-1",
                ),
            )

        # File table
        rows_data = _build_file_table_data(pid, file_type=ft)
        if rows_data:
            table_rows = []
            for row in rows_data:
                badge_class = _TYPE_COLORS.get(row["file_type"], "bg-secondary")
                table_rows.append(
                    ui.tags.tr(
                        ui.tags.td(row["filename"]),
                        ui.tags.td(ui.span(row["file_type"], class_=f"badge {badge_class}")),
                        ui.tags.td(ui.code(row["rel_path"], class_="small")),
                        ui.tags.td(row["size_str"]),
                        ui.tags.td(
                            ui.input_action_button(
                                f"dl_{row['id']}",
                                ui.tags.i(class_="bi bi-download"),
                                class_="btn-sm btn-outline-primary me-1",
                            ),
                            ui.input_action_button(
                                f"rm_{row['id']}",
                                ui.tags.i(class_="bi bi-trash"),
                                class_="btn-sm btn-outline-danger",
                            ),
                        ),
                    )
                )

            file_table = ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Name"),
                        ui.tags.th("Type"),
                        ui.tags.th("Path"),
                        ui.tags.th("Size"),
                        ui.tags.th("Actions"),
                    )
                ),
                ui.tags.tbody(*table_rows),
                class_="table table-sm table-hover",
            )

            # Register handlers for download and delete buttons
            for row in rows_data:
                _register_download_handler(row["id"])
                _register_delete_handler(row["id"], row["filename"])
        else:
            file_table = ui.p("No files found.", class_="text-muted text-center p-4")

        # Upload section
        from shyfem_ui.components.file_browser import file_browser_ui
        upload_section = ui.div(
            ui.h5("Upload File"),
            ui.input_select(
                "upload_type",
                "File Type",
                choices={
                    "": "Auto-detect",
                    "grid": "Grid (.grd)",
                    "basin": "Basin (.bas)",
                    "str": "STR (.str)",
                    "forcing": "Forcing",
                    "boundary": "Boundary",
                    "initial_condition": "Initial Condition",
                    "restart": "Restart",
                    "config": "Config (.nml)",
                    "other": "Other",
                },
            ),
            ui.input_text(
                "upload_subdir",
                "Subdirectory (optional)",
                placeholder="e.g. INPUT, GRID",
            ),
            file_browser_ui("file_upload"),
            class_="card p-3 mb-3",
        )

        # Seed tutorial button
        seed_btn = None
        if summary["file_count"] == 0 and _has_tutorial_data():
            seed_btn = ui.div(
                ui.input_action_button(
                    "seed_tutorial_btn",
                    "Seed Tutorial Files (Mar Menor)",
                    class_="btn-outline-info btn-sm w-100",
                ),
                class_="mb-3",
            )

        return ui.layout_sidebar(
            ui.sidebar(
                storage_bar,
                upload_section,
                seed_btn,
                width=350,
            ),
            ui.div(
                ui.div(*type_buttons, class_="mb-3"),
                file_table,
            ),
        )

    # File upload handler
    from shyfem_ui.components.file_browser import file_browser_server, persist_upload

    def _handle_upload(files):
        if not files or active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return

        for f in files:
            file_type = input.upload_type() or None
            subdir = input.upload_subdir() or None
            from pathlib import Path
            result = persist_upload(
                temp_path=Path(f["datapath"]),
                filename=f["name"],
                project_id=proj["id"],
                file_type=file_type,
                subdir=subdir,
            )
            if result:
                ui.notification_show(f"Uploaded: {result['filename']}", type="message")
            else:
                ui.notification_show(f"Failed to upload: {f['name']}", type="error")

        refresh_trigger.set(refresh_trigger.get() + 1)

    file_browser_server("file_upload", on_file_selected=_handle_upload)

    # Type filter handlers
    for label, type_val in [("all", None), ("grid", "grid"), ("forcing", "forcing"),
                             ("boundary", "boundary"), ("str", "str"),
                             ("config", "config"), ("other", "other")]:
        _register_filter_handler(label, type_val, current_filter, refresh_trigger, input)

    # Seed tutorial handler
    @reactive.effect
    @reactive.event(input.seed_tutorial_btn)
    def _seed_tutorial():
        proj = active_project.get() if active_project else None
        if proj is None:
            return
        try:
            FileService.seed_tutorial_files(proj["id"])
            ui.notification_show("Tutorial files seeded successfully!", type="message")
            refresh_trigger.set(refresh_trigger.get() + 1)
        except Exception as e:
            ui.notification_show(f"Error seeding tutorial files: {e}", type="error")

    def _register_download_handler(file_id: int):
        btn_id = f"dl_{file_id}"

        @reactive.effect
        @reactive.event(getattr(input, btn_id))
        def _download():
            try:
                path = FileService.get_file_path(file_id)
                data = path.read_bytes()
                b64 = base64.b64encode(data).decode()
                js = f"""
                var a = document.createElement('a');
                a.href = 'data:application/octet-stream;base64,{b64}';
                a.download = '{path.name}';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                """
                ui.insert_ui(ui.tags.script(js), selector="body", where="beforeEnd")
            except Exception as e:
                ui.notification_show(f"Download error: {e}", type="error")

    def _register_delete_handler(file_id: int, filename: str):
        btn_id = f"rm_{file_id}"

        @reactive.effect
        @reactive.event(getattr(input, btn_id))
        def _confirm_delete():
            m = ui.modal(
                ui.p(f"Delete '{filename}'? This cannot be undone."),
                title="Confirm Delete",
                easy_close=True,
                footer=ui.div(
                    ui.input_action_button(
                        f"confirm_rm_{file_id}",
                        "Delete",
                        class_="btn-danger",
                    ),
                    ui.input_action_button(
                        f"cancel_rm_{file_id}",
                        "Cancel",
                        class_="btn-secondary ms-2",
                    ),
                ),
            )
            ui.modal_show(m)

            @reactive.effect
            @reactive.event(getattr(input, f"confirm_rm_{file_id}"))
            def _do_delete():
                try:
                    FileService.delete_file(file_id)
                    ui.notification_show(f"Deleted: {filename}", type="message")
                    refresh_trigger.set(refresh_trigger.get() + 1)
                except Exception as e:
                    ui.notification_show(f"Delete error: {e}", type="error")
                ui.modal_remove()

            @reactive.effect
            @reactive.event(getattr(input, f"cancel_rm_{file_id}"))
            def _cancel():
                ui.modal_remove()


def _register_filter_handler(label, type_val, current_filter, refresh_trigger, input):
    btn_id = f"filter_{label}"

    @reactive.effect
    @reactive.event(getattr(input, btn_id))
    def _set_filter():
        current_filter.set(type_val)
        refresh_trigger.set(refresh_trigger.get() + 1)
```

**Step 4: Wire into `app.py`**

In `shyfem-ui/shyfem_ui/app.py`:

1. Add import at top (near other page imports, around line 26):
```python
from shyfem_ui.pages import files
```

2. Add tab after Ensemble (line 492):
```python
            ui.nav_panel("Files", files.files_ui("files")),
```

3. Add server wiring after ensemble (line 551):
```python
    files.files_server("files", config, active_project=active_project)
```

**Step 5: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_files_page.py -v`
Expected: PASS (all 8 tests)

**Step 6: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: All passing (existing + new)

**Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/files.py shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_files_page.py
git commit -m "feat: add Files tab with upload, download, delete, and storage bar"
```

---

### Task 4: STR Editor File Picker Integration

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/str_editor.py:350-416` (form panel rendering)
- Modify: `shyfem-ui/shyfem_ui/components/str_editor.py:102-109` (server signature)
- Modify: `shyfem-ui/shyfem_ui/pages/simulation.py:163` (pass project_id)
- Test: `shyfem-ui/tests/test_str_file_picker.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_str_file_picker.py`:

```python
"""Tests for STR editor file picker integration."""

import pytest


class TestDetectFileParams:

    def test_wind_detected_as_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("wind") is True

    def test_boundn_detected_as_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("boundn") is True

    def test_idt_not_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("idt") is False

    def test_ilin_not_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("ilin") is False


class TestBuildFormPanelWithFilePicker:
    """Test that _build_form_panel uses file picker for file params when project_id is set."""

    def test_form_panel_renders_file_picker_for_wind(self):
        from shyfem_ui.services.parser_str import StrParser
        from shyfem_ui.components.str_editor import _build_form_panel

        content = "$name\n    wind = 'INPUT/wind.fem'\n$end\n"
        parsed = StrParser.parse(content)
        # With project_id=123, file params should get file_picker_ui
        html = _build_form_panel(parsed, project_id=123)
        rendered = str(html)
        # Should contain file-picker-component class (from file_picker_ui)
        assert "file-picker-component" in rendered

    def test_form_panel_renders_text_input_without_project(self):
        from shyfem_ui.services.parser_str import StrParser
        from shyfem_ui.components.str_editor import _build_form_panel

        content = "$name\n    wind = 'INPUT/wind.fem'\n$end\n"
        parsed = StrParser.parse(content)
        # Without project_id, should fall back to text input
        html = _build_form_panel(parsed, project_id=None)
        rendered = str(html)
        assert "file-picker-component" not in rendered

    def test_form_panel_regular_param_unaffected(self):
        from shyfem_ui.services.parser_str import StrParser
        from shyfem_ui.components.str_editor import _build_form_panel

        content = "$para\n    idt = 300\n$end\n"
        parsed = StrParser.parse(content)
        html = _build_form_panel(parsed, project_id=123)
        rendered = str(html)
        # idt should NOT get a file picker
        assert "file-picker-component" not in rendered
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_file_picker.py -v`
Expected: FAIL — `_build_form_panel() got an unexpected keyword argument 'project_id'`

**Step 3: Modify `_build_form_panel` signature and rendering**

In `shyfem-ui/shyfem_ui/components/str_editor.py`:

1. Update `_build_form_panel` signature (line 332) to accept `project_id`:

```python
def _build_form_panel(parsed: StrFile | None, search_filter: dict[str, list[str]] | None = None, project_id: int | None = None) -> ui.Tag:
```

2. Inside the parameter rendering loop (around line 406), before the `else:` that creates `ui.input_text`, add a file picker check. Replace the block at lines 406-416 with:

```python
                else:
                    # Check if this is a file parameter with active project
                    from shyfem_ui.components.file_picker import is_file_param, file_picker_ui, param_to_file_types
                    if project_id is not None and is_file_param(param_name):
                        file_types = param_to_file_types(param_name)
                        picker_id = f"fp_{section_name}_{param_name}"
                        fields.append(
                            ui.div(
                                label,
                                file_picker_ui(picker_id, label=""),
                                # Hidden text input to hold value for form sync
                                ui.input_text(
                                    field_id, "",
                                    value=str(param_val),
                                ),
                                class_="mb-2",
                            )
                        )
                    else:
                        fields.append(
                            ui.div(
                                label,
                                ui.input_text(
                                    field_id, "",
                                    value=str(param_val),
                                ),
                                class_="mb-2",
                            )
                        )
```

3. Do the same for the unknown parameter block (lines 417-428) — add file picker check.

4. Update `str_editor_server` (line 103) to accept `project_id`:

```python
def str_editor_server(
    input,
    output,
    session,
    file_path: reactive.Value[Path | None],
    on_save: Callable[[Path, str], None] | None = None,
    project_id: reactive.Value | None = None,
):
```

5. Pass `project_id` when calling `_build_form_panel` in the form renderer (find the call in the server function).

6. Update `simulation.py` line 163 to pass `project_id`:

```python
    # Extract project_id as reactive value for STR editor
    project_id_reactive = reactive.value(None)

    @reactive.effect
    def _sync_project_id():
        if active_project is None:
            return
        proj = active_project.get()
        project_id_reactive.set(proj["id"] if proj else None)

    editor_state = str_editor_server("str_editor", current_file_path, project_id=project_id_reactive)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_file_picker.py -v`
Expected: PASS (all 7 tests)

**Step 5: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: All passing

**Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/str_editor.py shyfem-ui/shyfem_ui/pages/simulation.py shyfem-ui/tests/test_str_file_picker.py
git commit -m "feat: render file_picker in STR editor for file parameters"
```

---

### Task 5: Run Page Pre-Flight Validation

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:362-409` (submit handler)
- Test: `shyfem-ui/tests/test_run_validation.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_run_validation.py`:

```python
"""Tests for pre-flight file validation on the Run page."""

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


class TestPreflightValidation:

    def test_no_warnings_all_files_present(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, Simulation
        from shyfem_ui.pages.run import _preflight_validate

        work = tmp_path / "projects" / "ok_proj"
        work.mkdir(parents=True)
        (work / "INPUT").mkdir()
        (work / "GRID").mkdir()
        (work / "ok.str").write_text(
            "$title\nTest\nok\nGRID/mesh\n$end\n"
            "$para\nidt = 300\n$end\n"
            "$name\nwind = 'INPUT/wind.fem'\n$end\n"
        )
        (work / "INPUT" / "wind.fem").write_text("data")
        (work / "GRID" / "mesh.bas").write_text("data")

        with db_session() as db:
            p = Project(name="ok_proj", work_dir=str(work))
            db.add(p)
            db.flush()
            s = Simulation(project_id=p.id, name="ok", str_file="ok.str")
            db.add(s)
            db.flush()
            sid = s.id

        warnings = _preflight_validate(sid)
        assert warnings == []

    def test_returns_warnings_for_missing_files(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, Simulation
        from shyfem_ui.pages.run import _preflight_validate

        work = tmp_path / "projects" / "bad_proj"
        work.mkdir(parents=True)
        (work / "bad.str").write_text(
            "$title\nTest\nbad\nGRID/mesh\n$end\n"
            "$name\nwind = 'INPUT/wind.fem'\n$end\n"
        )

        with db_session() as db:
            p = Project(name="bad_proj", work_dir=str(work))
            db.add(p)
            db.flush()
            s = Simulation(project_id=p.id, name="bad", str_file="bad.str")
            db.add(s)
            db.flush()
            sid = s.id

        warnings = _preflight_validate(sid)
        assert len(warnings) >= 1
        assert any("wind" in w.lower() for w in warnings)

    def test_returns_empty_for_invalid_sim(self):
        from shyfem_ui.pages.run import _preflight_validate
        warnings = _preflight_validate(None)
        assert warnings == []

    def test_returns_empty_for_nonexistent_sim(self):
        from shyfem_ui.pages.run import _preflight_validate
        warnings = _preflight_validate(99999)
        assert warnings == []
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_validation.py -v`
Expected: FAIL — `ImportError: cannot import name '_preflight_validate'`

**Step 3: Implement `_preflight_validate` and modify submit handler**

In `shyfem-ui/shyfem_ui/pages/run.py`:

1. Add helper function (at module level, before `run_server`):

```python
def _preflight_validate(simulation_id: int | None) -> list[str]:
    """Run pre-flight file validation for a simulation.

    Returns list of warning strings. Empty = all OK.
    Returns empty list for None or invalid simulation IDs (non-blocking).
    """
    if simulation_id is None:
        return []
    try:
        from shyfem_ui.services.file_service import FileService
        return FileService.validate_simulation_files(simulation_id)
    except (ValueError, Exception):
        return []
```

2. In `_submit_job` handler (line 364), after input validation and before building JobSpec (line 389), add validation check:

```python
        # Pre-flight file validation
        proj = active_project.get() if active_project else None
        if proj and proj.get("simulations"):
            # Find simulation matching the input file
            input_name = Path(input_file).stem
            sim_id = None
            for sim in proj["simulations"]:
                if sim.get("str_file") and Path(sim["str_file"]).stem == input_name:
                    from shyfem_ui.db.base import db_session
                    from shyfem_ui.models.project import Simulation
                    with db_session() as db:
                        s = db.query(Simulation).filter_by(
                            project_id=proj["id"], name=sim["name"]
                        ).first()
                        if s:
                            sim_id = s.id
                    break

            warnings = _preflight_validate(sim_id)
            if warnings:
                warning_items = [ui.tags.li(w) for w in warnings]
                m = ui.modal(
                    ui.p("The following file references could not be found:"),
                    ui.tags.ul(*warning_items),
                    title="Missing File References",
                    easy_close=True,
                    footer=ui.div(
                        ui.input_action_button(
                            "run_anyway_btn",
                            "Run Anyway",
                            class_="btn-warning",
                        ),
                        ui.input_action_button(
                            "cancel_run_btn",
                            "Cancel",
                            class_="btn-secondary ms-2",
                        ),
                    ),
                )
                ui.modal_show(m)
                # Store pending spec for "Run Anyway"
                _pending_spec.set(spec)
                return  # Don't submit yet
```

3. Add the pending spec reactive value and handlers in `run_server`:

```python
    _pending_spec = reactive.value(None)

    @reactive.effect
    @reactive.event(input.run_anyway_btn)
    async def _run_anyway():
        spec = _pending_spec.get()
        if spec is None:
            return
        ui.modal_remove()
        try:
            job_id = await job_queue.submit(spec)
            ui.notification_show(f"Job submitted: {spec.name} (ID: {job_id})", type="message")
        except Exception as e:
            ui.notification_show(f"Submit error: {e}", type="error")
        _pending_spec.set(None)

    @reactive.effect
    @reactive.event(input.cancel_run_btn)
    def _cancel_run():
        ui.modal_remove()
        _pending_spec.set(None)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_validation.py -v`
Expected: PASS (all 4 tests)

**Step 5: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: All passing

**Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/run.py shyfem-ui/tests/test_run_validation.py
git commit -m "feat: add pre-flight file validation before job submission"
```

---

### Task 6: Full Test Suite + TODO Update

**Step 1: Run full test suite**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short
```

Expected: All tests pass.

**Step 2: Update TODO_NEXT.md**

Add a new section after Phase 43:

```markdown
## Phase 44: File Management UI Integration

> Server deployment: end-to-end file management through the browser.

- [x] **44.1** Enhanced file_browser with project persistence — 5 tests
  - `persist_upload()` reads temp file, calls `FileService.upload_file()`
  - `infer_file_type()` auto-detects category from extension
  - Returns None gracefully on quota exceeded or missing project

- [x] **44.2** File picker component (new) — 12 tests
  - `file_picker_ui()` — dropdown + "Browse..." button
  - `file_picker_server()` — reactive choices from FileService, browse modal
  - `build_file_choices()` pure function with type filtering
  - `is_file_param()` / `param_to_file_types()` — STR parameter detection

- [x] **44.3** Files page (new tab) — 8 tests
  - Storage usage bar with progress indicator
  - File table with type badges, download, and delete actions
  - Type filter buttons (All, Grid, Forcing, Boundary, STR, Config, Other)
  - Upload section with type selector and subdirectory input
  - "Seed Tutorial Files" button for empty projects

- [x] **44.4** STR editor file picker integration — 7 tests
  - File parameters auto-detected via `is_file_param()`
  - Renders `file_picker_ui()` instead of `ui.input_text()` when project active
  - Falls back to plain text input when no project selected
  - `project_id` threaded from simulation page → STR editor → form panel

- [x] **44.5** Run page pre-flight validation — 4 tests
  - `_preflight_validate()` calls `FileService.validate_simulation_files()`
  - Warning modal with missing file list
  - "Run Anyway" and "Cancel" buttons
  - Non-blocking: returns empty list for invalid/missing simulations
```

**Step 3: Commit**

```bash
git add shyfem-ui/TODO_NEXT.md
git commit -m "docs: mark Phase 44 file management UI integration complete"
```

---

### Summary

| Task | What | Test Count |
|------|------|------------|
| 1 | Enhanced file_browser (persist_upload, infer_file_type) | 5 |
| 2 | File picker component (dropdown + browse modal) | 12 |
| 3 | Files page (new tab with upload/download/delete) | 8 |
| 4 | STR editor file picker integration | 7 |
| 5 | Run page pre-flight validation | 4 |
| 6 | Full test suite + TODO update | — |

**Total new tests: ~36**

**Dependency order:** Task 1 → Task 2 → Tasks 3, 4, 5 (independent) → Task 6
