# Phase 33: Project Import/Export — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add project export (ZIP download), import (ZIP upload), and clone functionality to the SHYFEM UI Dashboard.

**Architecture:** New `services/project_export.py` with three pure functions: `export_project()`, `import_project()`, `clone_project()`. The export produces a ZIP containing the work_dir tree + `manifest.json`. Import validates the manifest, extracts files, creates DB records. Clone uses `shutil.copytree()`. The Dashboard UI (home.py) wires buttons to these functions.

**Tech Stack:** Python zipfile, shutil, json, Shiny `ui.download_button` + `@render.download`, pytest

---

### Task 1: Implement export_project() with tests

**Files:**
- Create: `shyfem_ui/services/project_export.py`
- Create: `tests/test_project_export.py`

**Step 1: Write the failing tests**

Create `tests/test_project_export.py`:

```python
"""Tests for project export/import/clone service."""

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from shyfem_ui.services.project_export import export_project, MANIFEST_VERSION


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project directory with grid and str files."""
    d = tmp_path / "test_project"
    d.mkdir()
    (d / "GRID").mkdir()
    (d / "GRID" / "mesh.grd").write_text("grid data")
    (d / "GRID" / "mesh.bas").write_text("bas data")
    (d / "INPUT").mkdir()
    (d / "INPUT" / "wind.txt").write_text("wind data")
    (d / "sim.str").write_text("$title\nTest\n$end\n")
    # Job log files that should be excluded
    (d / "abc-123.stdout").write_text("stdout log")
    (d / "abc-123.stderr").write_text("stderr log")
    return d


@pytest.fixture
def project_meta():
    """Project metadata dict (mimics DB query result)."""
    return {
        "name": "Test Project",
        "description": "A test project",
        "grids": [
            {
                "name": "mesh",
                "description": None,
                "grd_file": "GRID/mesh.grd",
                "bas_file": "GRID/mesh.bas",
                "num_nodes": 100,
                "num_elements": 200,
                "num_layers": None,
                "min_depth": 0.5,
                "max_depth": 20.0,
            }
        ],
        "simulations": [
            {
                "name": "sim",
                "description": None,
                "str_file": "sim.str",
                "grid_name": "mesh",
                "start_time": "2020-01-01",
                "end_time": "2020-01-02",
                "time_step": 300.0,
                "mpi_enabled": False,
                "mpi_np": 1,
            }
        ],
    }


class TestExportProject:

    def test_returns_valid_zip(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        assert isinstance(result, BytesIO)
        with zipfile.ZipFile(result) as zf:
            assert zf.testzip() is None  # no corrupt files

    def test_zip_contains_manifest(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            assert "manifest.json" in zf.namelist()
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["version"] == MANIFEST_VERSION
            assert manifest["project"]["name"] == "Test Project"

    def test_zip_contains_project_files(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "GRID/mesh.grd" in names
            assert "GRID/mesh.bas" in names
            assert "INPUT/wind.txt" in names
            assert "sim.str" in names

    def test_zip_excludes_log_files(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert not any(n.endswith(".stdout") for n in names)
            assert not any(n.endswith(".stderr") for n in names)

    def test_manifest_has_grids_and_simulations(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert len(manifest["grids"]) == 1
            assert manifest["grids"][0]["name"] == "mesh"
            assert len(manifest["simulations"]) == 1
            assert manifest["simulations"][0]["name"] == "sim"

    def test_manifest_has_exported_at(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert "exported_at" in manifest

    def test_empty_project_dir(self, tmp_path, project_meta):
        empty = tmp_path / "empty"
        empty.mkdir()
        project_meta["grids"] = []
        project_meta["simulations"] = []
        result = export_project(empty, project_meta)
        with zipfile.ZipFile(result) as zf:
            assert "manifest.json" in zf.namelist()
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_export.py::TestExportProject -v`
Expected: FAIL — `cannot import name 'export_project'`

**Step 3: Implement export_project()**

Create `shyfem_ui/services/project_export.py`:

```python
"""Project export, import, and clone operations."""

import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

MANIFEST_VERSION = "1.0"

# File extensions to exclude from export (job logs)
_EXCLUDE_EXTENSIONS = frozenset({".stdout", ".stderr"})


def export_project(work_dir: Path, project_meta: dict) -> BytesIO:
    """Export a project as a ZIP archive with manifest.

    Args:
        work_dir: Absolute path to the project's work directory.
        project_meta: Dict with keys: name, description, grids, simulations.

    Returns:
        BytesIO containing the ZIP archive.
    """
    buf = BytesIO()
    work_dir = Path(work_dir)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write project files
        for file_path in sorted(work_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix in _EXCLUDE_EXTENSIONS:
                continue
            arcname = str(file_path.relative_to(work_dir))
            zf.write(file_path, arcname)

        # Write manifest
        manifest = {
            "version": MANIFEST_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "project": {
                "name": project_meta["name"],
                "description": project_meta.get("description"),
            },
            "grids": project_meta.get("grids", []),
            "simulations": project_meta.get("simulations", []),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    return buf
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_export.py::TestExportProject -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/project_export.py shyfem-ui/tests/test_project_export.py
git commit -m "$(cat <<'EOF'
feat: add export_project() service with ZIP + manifest

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Implement import_project() with tests

**Files:**
- Modify: `shyfem_ui/services/project_export.py`
- Modify: `tests/test_project_export.py`

**Step 1: Write the failing tests**

Append to `tests/test_project_export.py`:

```python
from shyfem_ui.services.project_export import import_project


@pytest.fixture
def exported_zip(project_dir, project_meta):
    """Create an exported ZIP for import tests."""
    return export_project(project_dir, project_meta)


class TestImportProject:

    def test_import_creates_directory(self, exported_zip, tmp_path):
        result = import_project(exported_zip, tmp_path)
        assert result["work_dir"].is_dir()

    def test_import_extracts_files(self, exported_zip, tmp_path):
        result = import_project(exported_zip, tmp_path)
        wd = result["work_dir"]
        assert (wd / "GRID" / "mesh.grd").exists()
        assert (wd / "sim.str").exists()

    def test_import_returns_manifest_data(self, exported_zip, tmp_path):
        result = import_project(exported_zip, tmp_path)
        assert result["name"] == "Test Project"
        assert len(result["grids"]) == 1
        assert len(result["simulations"]) == 1

    def test_import_name_collision_appends_suffix(self, exported_zip, tmp_path):
        # First import
        import_project(exported_zip, tmp_path)
        # Second import — same name, should get a suffix
        exported_zip.seek(0)
        result = import_project(exported_zip, tmp_path)
        assert result["name"] != "Test Project"
        assert result["name"].startswith("Test Project_")

    def test_import_rejects_missing_manifest(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("file.txt", "hello")
        buf.seek(0)
        with pytest.raises(ValueError, match="manifest.json"):
            import_project(buf, tmp_path)

    def test_import_rejects_bad_json(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", "not json")
        buf.seek(0)
        with pytest.raises(ValueError, match="manifest"):
            import_project(buf, tmp_path)

    def test_import_rejects_path_traversal(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            manifest = {
                "version": "1.0",
                "exported_at": "2026-01-01T00:00:00Z",
                "project": {"name": "evil", "description": None},
                "grids": [],
                "simulations": [],
            }
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("../../../etc/passwd", "pwned")
        buf.seek(0)
        with pytest.raises(ValueError, match="path traversal"):
            import_project(buf, tmp_path)

    def test_import_rejects_missing_version(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            manifest = {
                "project": {"name": "test", "description": None},
                "grids": [],
                "simulations": [],
            }
            zf.writestr("manifest.json", json.dumps(manifest))
        buf.seek(0)
        with pytest.raises(ValueError, match="version"):
            import_project(buf, tmp_path)
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_export.py::TestImportProject -v`
Expected: FAIL — `cannot import name 'import_project'`

**Step 3: Implement import_project()**

Append to `shyfem_ui/services/project_export.py`:

```python
def import_project(zip_data: BytesIO, base_dir: Path) -> dict:
    """Import a project from a ZIP archive.

    Args:
        zip_data: BytesIO containing the ZIP archive.
        base_dir: Base directory where the project will be extracted.

    Returns:
        Dict with keys: name, description, work_dir (Path), grids, simulations.

    Raises:
        ValueError: If the archive is invalid (missing manifest, bad JSON,
            path traversal, missing version).
    """
    base_dir = Path(base_dir)

    with zipfile.ZipFile(zip_data, "r") as zf:
        # Validate manifest exists
        if "manifest.json" not in zf.namelist():
            raise ValueError("Invalid archive: missing manifest.json")

        # Parse manifest
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except (json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Invalid manifest: {e}") from e

        if "version" not in manifest:
            raise ValueError("Invalid manifest: missing version")

        project_info = manifest.get("project", {})
        name = project_info.get("name", "imported_project")

        # Check for path traversal
        for member in zf.namelist():
            if member == "manifest.json":
                continue
            normalized = Path(member).as_posix()
            if ".." in normalized.split("/"):
                raise ValueError(f"Rejected: path traversal in '{member}'")

        # Determine unique directory name
        project_dir = base_dir / _sanitize_dirname(name)
        if project_dir.exists():
            suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"{name}_{suffix}"
            project_dir = base_dir / _sanitize_dirname(name)

        project_dir.mkdir(parents=True)

        # Extract files (skip manifest)
        for member in zf.namelist():
            if member == "manifest.json":
                continue
            target = project_dir / member
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())

    return {
        "name": name,
        "description": project_info.get("description"),
        "work_dir": project_dir,
        "grids": manifest.get("grids", []),
        "simulations": manifest.get("simulations", []),
    }


def _sanitize_dirname(name: str) -> str:
    """Convert a project name to a safe directory name."""
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    return safe.strip().replace(" ", "_") or "project"
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_export.py::TestImportProject -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/project_export.py shyfem-ui/tests/test_project_export.py
git commit -m "$(cat <<'EOF'
feat: add import_project() with validation and path traversal protection

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Implement clone_project() with tests

**Files:**
- Modify: `shyfem_ui/services/project_export.py`
- Modify: `tests/test_project_export.py`

**Step 1: Write the failing tests**

Append to `tests/test_project_export.py`:

```python
from shyfem_ui.services.project_export import clone_project


class TestCloneProject:

    def test_clone_creates_new_directory(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        assert result["work_dir"].is_dir()
        assert result["work_dir"] != project_dir

    def test_clone_copies_files(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        wd = result["work_dir"]
        assert (wd / "GRID" / "mesh.grd").exists()
        assert (wd / "sim.str").exists()

    def test_clone_default_name(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        assert result["name"] == "Test Project (Copy)"

    def test_clone_custom_name(self, project_dir, project_meta):
        result = clone_project(
            project_dir, project_meta, project_dir.parent, new_name="My Clone"
        )
        assert result["name"] == "My Clone"

    def test_clone_returns_metadata(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        assert len(result["grids"]) == 1
        assert len(result["simulations"]) == 1

    def test_clone_excludes_logs(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        wd = result["work_dir"]
        assert not list(wd.glob("*.stdout"))
        assert not list(wd.glob("*.stderr"))
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_export.py::TestCloneProject -v`
Expected: FAIL — `cannot import name 'clone_project'`

**Step 3: Implement clone_project()**

Append to `shyfem_ui/services/project_export.py`:

```python
def clone_project(
    work_dir: Path,
    project_meta: dict,
    base_dir: Path,
    new_name: str | None = None,
) -> dict:
    """Clone a project by copying its work directory.

    Args:
        work_dir: Source project's work directory.
        project_meta: Dict with keys: name, description, grids, simulations.
        base_dir: Base directory where the clone will be created.
        new_name: Optional name for the clone. Defaults to "Original (Copy)".

    Returns:
        Dict with keys: name, description, work_dir (Path), grids, simulations.
    """
    work_dir = Path(work_dir)
    base_dir = Path(base_dir)
    name = new_name or f"{project_meta['name']} (Copy)"
    clone_dir = base_dir / _sanitize_dirname(name)

    if clone_dir.exists():
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{name}_{suffix}"
        clone_dir = base_dir / _sanitize_dirname(name)

    import shutil

    def _ignore_logs(directory, files):
        return [f for f in files if Path(f).suffix in _EXCLUDE_EXTENSIONS]

    shutil.copytree(work_dir, clone_dir, ignore=_ignore_logs)

    return {
        "name": name,
        "description": project_meta.get("description"),
        "work_dir": clone_dir,
        "grids": project_meta.get("grids", []),
        "simulations": project_meta.get("simulations", []),
    }
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_export.py::TestCloneProject -v`
Expected: 6 PASSED

**Step 5: Run full export test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_export.py -v`
Expected: 21 PASSED (7 export + 8 import + 6 clone)

**Step 6: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/project_export.py shyfem-ui/tests/test_project_export.py
git commit -m "$(cat <<'EOF'
feat: add clone_project() with log exclusion

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Wire export/import/clone into Dashboard UI

**Files:**
- Modify: `shyfem_ui/pages/home.py:49-125` (UI), `shyfem_ui/pages/home.py:129-534` (server)

**Step 1: Add Import Project button to Quick Start card**

In `home_ui()`, after the "Import Grid" button (line 82), add:

```python
                    ui.input_action_button(
                        "import_project_btn",
                        "Import Project",
                        class_="btn-outline-secondary w-100 mb-2",
                    ),
```

**Step 2: Add Export and Clone columns to projects table**

In `projects_list()` render function (line 242), modify the table to add action buttons per project. Replace the existing `rows.append(...)` block (lines 250-266) with:

```python
            rows.append(
                ui.tags.tr(
                    ui.tags.td(
                        ui.input_action_link(
                            f"project_{p['id']}",
                            p["name"],
                            class_="fw-bold",
                        )
                    ),
                    ui.tags.td(p["description"] or "-"),
                    ui.tags.td(ui.code(p["work_dir"], class_="small")),
                    ui.tags.td(
                        p["updated_at"].strftime("%Y-%m-%d %H:%M")
                        if p["updated_at"] else "-"
                    ),
                    ui.tags.td(
                        ui.input_action_link(
                            f"export_{p['id']}",
                            "Export",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        ui.input_action_link(
                            f"clone_{p['id']}",
                            "Clone",
                            class_="btn btn-sm btn-outline-secondary",
                        ),
                    ),
                )
            )
```

And add an "Actions" column header (line 274):

```python
                    ui.tags.th("Actions"),
```

**Step 3: Add export handler in server**

In `home_server()`, after the `_activate_project()` function (after line 507), add:

```python
    # --- Export/Import/Clone handlers ---

    @reactive.effect
    async def _handle_export():
        """Watch for export_<id> link clicks and trigger download."""
        project_data = projects.get()
        for p in project_data:
            pid = p["id"]
            try:
                if input[f"export_{pid}"]():
                    await _do_export(pid, p["name"])
            except Exception:
                pass  # Input not yet created

    async def _do_export(project_id: int, project_name: str):
        """Export a project as ZIP and trigger browser download."""
        import base64
        from shyfem_ui.services.project_context import load_project_context
        from shyfem_ui.services.project_export import export_project

        ctx = load_project_context(project_id)
        if ctx is None:
            ui.notification_show("Project not found", type="error")
            return

        work_dir = Path(ctx["work_dir"])
        if not work_dir.is_dir():
            ui.notification_show("Project directory not found", type="error")
            return

        # Build export metadata from context
        meta = {
            "name": ctx["name"],
            "description": ctx.get("description"),
            "grids": ctx.get("grids", []),
            "simulations": ctx.get("simulations", []),
        }

        try:
            zip_buf = export_project(work_dir, meta)
            b64 = base64.b64encode(zip_buf.read()).decode("ascii")
            filename = f"{_safe_filename(project_name)}.zip"
            js = (
                f"var a=document.createElement('a');"
                f"a.href='data:application/zip;base64,{b64}';"
                f"a.download='{filename}';"
                f"a.click();"
            )
            await session.send_custom_message("eval_js", js)
            ui.notification_show(f"Exported '{project_name}'", type="message")
        except Exception as e:
            ui.notification_show(f"Export failed: {e}", type="error")
```

Add the helper at the top of the server function (after `_is_server_mode` line 142):

```python
    def _safe_filename(name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
```

**Step 4: Add import handler**

After the export handler, add:

```python
    @reactive.effect
    @reactive.event(input.import_project_btn)
    def _show_import_modal():
        m = ui.modal(
            ui.p("Upload a project ZIP archive (exported from SHYFEM UI)."),
            ui.input_file(
                "import_zip_file",
                "Select ZIP file",
                accept=[".zip"],
                multiple=False,
            ),
            title="Import Project",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button(
                    "confirm_import_btn",
                    "Import",
                    class_="btn-primary",
                ),
                ui.input_action_button(
                    "cancel_import_btn",
                    "Cancel",
                    class_="btn-secondary ms-2",
                ),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.cancel_import_btn)
    def _hide_import_modal():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.confirm_import_btn)
    def _do_import():
        file_info = input.import_zip_file()
        if not file_info:
            ui.notification_show("No file selected", type="error")
            return

        file_path = file_info[0]["datapath"]

        from shyfem_ui.services.project_export import import_project

        try:
            with open(file_path, "rb") as f:
                zip_data = BytesIO(f.read())
            result = import_project(zip_data, config.work_dir)
        except ValueError as e:
            ui.notification_show(f"Import failed: {e}", type="error")
            return
        except Exception as e:
            ui.notification_show(f"Import failed: {e}", type="error")
            return

        # Create DB records
        try:
            with db_session() as db:
                project = Project(
                    name=result["name"],
                    description=result.get("description"),
                    work_dir=str(result["work_dir"]),
                )
                db.add(project)
                db.flush()

                grid_name_to_id = {}
                for g in result.get("grids", []):
                    grid = Grid(
                        project_id=project.id,
                        name=g["name"],
                        description=g.get("description"),
                        grd_file=g.get("grd_file"),
                        bas_file=g.get("bas_file"),
                        num_nodes=g.get("num_nodes"),
                        num_elements=g.get("num_elements"),
                        num_layers=g.get("num_layers"),
                        min_depth=g.get("min_depth"),
                        max_depth=g.get("max_depth"),
                    )
                    db.add(grid)
                    db.flush()
                    grid_name_to_id[g["name"]] = grid.id

                for s in result.get("simulations", []):
                    sim = Simulation(
                        project_id=project.id,
                        grid_id=grid_name_to_id.get(s.get("grid_name")),
                        name=s["name"],
                        description=s.get("description"),
                        str_file=s.get("str_file"),
                        start_time=s.get("start_time"),
                        end_time=s.get("end_time"),
                        time_step=s.get("time_step"),
                        mpi_enabled=s.get("mpi_enabled", False),
                        mpi_np=s.get("mpi_np", 1),
                    )
                    db.add(sim)

            ui.notification_show(
                f"Imported project '{result['name']}'", type="message"
            )
            ui.modal_remove()
            _refresh_projects()

        except Exception as e:
            # Clean up extracted directory on DB failure
            import shutil
            work_dir = result.get("work_dir")
            if work_dir and Path(work_dir).exists():
                shutil.rmtree(work_dir, ignore_errors=True)
            ui.notification_show(f"Import failed: {e}", type="error")
```

Add `from io import BytesIO` to the imports at the top of `home.py` (line 1-12).

**Step 5: Add clone handler**

After the import handler, add:

```python
    @reactive.effect
    async def _handle_clone():
        """Watch for clone_<id> link clicks."""
        project_data = projects.get()
        for p in project_data:
            pid = p["id"]
            try:
                if input[f"clone_{pid}"]():
                    _do_clone(pid, p["name"])
            except Exception:
                pass

    def _do_clone(project_id: int, project_name: str):
        """Clone a project."""
        from shyfem_ui.services.project_context import load_project_context
        from shyfem_ui.services.project_export import clone_project

        ctx = load_project_context(project_id)
        if ctx is None:
            ui.notification_show("Project not found", type="error")
            return

        work_dir = Path(ctx["work_dir"])
        if not work_dir.is_dir():
            ui.notification_show("Project directory not found", type="error")
            return

        meta = {
            "name": ctx["name"],
            "description": ctx.get("description"),
            "grids": ctx.get("grids", []),
            "simulations": ctx.get("simulations", []),
        }

        try:
            result = clone_project(work_dir, meta, config.work_dir)
        except Exception as e:
            ui.notification_show(f"Clone failed: {e}", type="error")
            return

        # Create DB records (same pattern as import)
        try:
            with db_session() as db:
                project = Project(
                    name=result["name"],
                    description=result.get("description"),
                    work_dir=str(result["work_dir"]),
                )
                db.add(project)
                db.flush()

                grid_name_to_id = {}
                for g in result.get("grids", []):
                    grid = Grid(
                        project_id=project.id,
                        name=g["name"],
                        description=g.get("description"),
                        grd_file=g.get("grd_file"),
                        bas_file=g.get("bas_file"),
                    )
                    db.add(grid)
                    db.flush()
                    grid_name_to_id[g["name"]] = grid.id

                for s in result.get("simulations", []):
                    sim = Simulation(
                        project_id=project.id,
                        grid_id=grid_name_to_id.get(s.get("grid_name")),
                        name=s["name"],
                        description=s.get("description"),
                        str_file=s.get("str_file"),
                    )
                    db.add(sim)

            ui.notification_show(
                f"Cloned '{project_name}' as '{result['name']}'", type="message"
            )
            _refresh_projects()

        except Exception as e:
            import shutil
            work_dir = result.get("work_dir")
            if work_dir and Path(work_dir).exists():
                shutil.rmtree(work_dir, ignore_errors=True)
            ui.notification_show(f"Clone failed: {e}", type="error")
```

**Step 6: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: all passed, 0 failed

**Step 7: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/home.py
git commit -m "$(cat <<'EOF'
feat: wire export/import/clone into Dashboard UI

Export downloads ZIP via data URI. Import uploads ZIP and creates
DB records. Clone copies work_dir and creates new project.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Update TODO_NEXT.md

**Files:**
- Modify: `shyfem-ui/TODO_NEXT.md:349-362`

**Step 1: Update Phase 33 section**

Replace:

```markdown
## Phase 33: Project Import/Export

> No way to share simulation setups between users or back up projects.

- [ ] **33.1** Add "Export Project" button to Dashboard
  - ZIP archive containing: work_dir files, project metadata JSON,
    grid and simulation records, job history summary

- [ ] **33.2** Add "Import Project" handler
  - Upload ZIP, extract to work_dir, create DB records from metadata JSON
  - Validate paths and file integrity before importing

- [ ] **33.3** Add project clone functionality
  - "Clone Project" button that duplicates work_dir and DB records
```

With:

```markdown
## Phase 33: Project Import/Export

> Export, import, and clone projects for sharing and backup.

- [x] **33.1** Add "Export Project" button to Dashboard — 7 tests
  - ZIP archive with work_dir files + `manifest.json` (project/grid/sim metadata)
  - Excludes job logs (`.stdout`, `.stderr`); downloads via data URI

- [x] **33.2** Add "Import Project" handler — 8 tests
  - Upload ZIP, validate manifest, reject path traversal, extract to work_dir
  - Creates Project, Grid, Simulation DB records from manifest
  - Handles name collisions by appending timestamp

- [x] **33.3** Add project clone functionality — 6 tests
  - `shutil.copytree()` with log exclusion, new DB records
  - Default name: "Original (Copy)"
```

**Step 2: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/TODO_NEXT.md
git commit -m "$(cat <<'EOF'
docs: mark Phase 33 complete in TODO_NEXT.md

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```
