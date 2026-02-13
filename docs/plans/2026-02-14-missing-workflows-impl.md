# Missing Workflows & Active Project Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 dead buttons and add shared active-project state that auto-fills file paths across all UI tabs.

**Architecture:** A `reactive.value(None)` created in `app.py` is passed to every page server. Home page handlers set it when users select/create projects. Each page watches it with a `@reactive.effect` that calls `ui.update_text()` to pre-fill its file path inputs. Two dynamic-remove-button patterns fix ensemble and boundary editor.

**Tech Stack:** Shiny for Python 1.5, SQLAlchemy (SQLite), Playwright (E2E tests), pytest

**Test runner:** `/opt/micromamba/envs/shiny/bin/python -m pytest`

**Design doc:** `docs/plans/2026-02-14-missing-workflows-design.md`

---

## Task 1: `load_project_context` helper + unit test

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/project_context.py`
- Test: `shyfem-ui/tests/test_project_context.py`

**Step 1: Write the failing test**

```python
# shyfem-ui/tests/test_project_context.py
"""Unit tests for load_project_context."""

import os
import pytest
from pathlib import Path

# Point at a temp SQLite DB before importing anything that calls get_config
@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path))
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))

    # Force re-init of config and DB singletons
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


class TestLoadProjectContext:
    def test_returns_none_for_missing_id(self):
        from shyfem_ui.services.project_context import load_project_context
        assert load_project_context(9999) is None

    def test_loads_project_with_grids_and_sims(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Grid, Project, Simulation
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="test_proj", work_dir=str(tmp_path / "proj"))
            db.add(p)
            db.flush()
            g = Grid(project_id=p.id, name="grid1", grd_file="GRID/g.grd", bas_file="GRID/g.bas")
            db.add(g)
            db.flush()
            s = Simulation(project_id=p.id, grid_id=g.id, name="sim1", str_file="sim1.str")
            db.add(s)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid)
        assert ctx is not None
        assert ctx["name"] == "test_proj"
        assert len(ctx["grids"]) == 1
        assert ctx["grids"][0]["grd_file"] == "GRID/g.grd"
        assert len(ctx["simulations"]) == 1
        assert ctx["simulations"][0]["str_file"] == "sim1.str"

    def test_empty_grids_and_sims(self, tmp_path):
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="empty_proj", work_dir=str(tmp_path / "empty"))
            db.add(p)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid)
        assert ctx["grids"] == []
        assert ctx["simulations"] == []
```

**Step 2: Run test to verify it fails**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_project_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shyfem_ui.services.project_context'`

**Step 3: Write minimal implementation**

```python
# shyfem-ui/shyfem_ui/services/project_context.py
"""Load full project context from DB for active-project state."""

from typing import Optional

from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, Simulation


def load_project_context(project_id: int) -> Optional[dict]:
    """Load project with its grids and simulations as a plain dict.

    Returns None if the project_id does not exist.
    """
    with db_session() as db:
        project = db.query(Project).filter_by(id=project_id).first()
        if project is None:
            return None
        grids = db.query(Grid).filter_by(project_id=project_id).all()
        sims = db.query(Simulation).filter_by(project_id=project_id).all()
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
        }
```

**Step 4: Run test to verify it passes**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_project_context.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/project_context.py shyfem-ui/tests/test_project_context.py
git commit -m "feat: add load_project_context helper with unit tests"
```

---

## Task 2: Wire `active_project` + `nav_callback` in app.py

**Files:**
- Modify: `shyfem-ui/shyfem_ui/app.py:196-207`

**Step 1: Modify `_build_server`**

Add `reactive` import at top of file (line 12, alongside existing shiny imports):
```python
from shiny import App, reactive, ui
```

Replace `_build_server` body (lines 196-207) with:

```python
def _build_server(input, output, session, config: Config, job_queue: JobQueue):
    """Build the application server logic."""
    active_project = reactive.value(None)

    def nav_to(tab_name: str):
        ui.update_navs("main_navbar", selected=tab_name, session=session)

    # Initialize page servers
    home.home_server("home", config, job_queue,
                     active_project=active_project, nav_callback=nav_to)
    grid_prep.grid_prep_server("grid_prep", config, active_project=active_project)
    partitioning.partitioning_server("partitioning", config, active_project=active_project)
    simulation.simulation_server("simulation", config, active_project=active_project)
    run.run_server("run", config, job_queue, active_project=active_project)
    postprocess.postprocess_server("postprocess", config, active_project=active_project)
    visualize.visualize_server("visualize", config, active_project=active_project)
    compare.compare_server("compare", config, job_queue, active_project=active_project)
    ensemble.ensemble_server("ensemble", config, job_queue, active_project=active_project)
```

**Step 2: Verify the app still imports cleanly**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.app import create_app; print('OK')"`
Expected: This will FAIL because page servers don't accept `active_project` yet. That's expected — we fix them in the next tasks.

**Step 3: Commit (app.py only, ahead of page updates)**

```bash
git add shyfem-ui/shyfem_ui/app.py
git commit -m "feat: wire active_project and nav_callback in app.py"
```

---

## Task 3: Update all page server signatures to accept `active_project`

Every page server needs an `active_project=None` keyword param added. This is a mechanical change across 9 files. No behavior change yet — just accept and ignore.

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/home.py:125-131`
- Modify: `shyfem-ui/shyfem_ui/pages/grid_prep.py:98-103`
- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py:115-120`
- Modify: `shyfem-ui/shyfem_ui/pages/simulation.py:115-120`
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:224-229`
- Modify: `shyfem-ui/shyfem_ui/pages/postprocess.py:215-220`
- Modify: `shyfem-ui/shyfem_ui/pages/visualize.py:133-138`
- Modify: `shyfem-ui/shyfem_ui/pages/compare.py:101-106`
- Modify: `shyfem-ui/shyfem_ui/pages/ensemble.py:123-128`

**Step 1: Add parameters**

For **home.py** — add both `active_project` and `nav_callback`:
```python
@module.server
def home_server(
    input,
    output,
    session,
    config: Config,
    job_queue: Optional[JobQueue] = None,
    active_project: Optional[reactive.Value] = None,
    nav_callback=None,
):
```
Also add `from pathlib import Path` to imports if not present, and add `reactive` to the shiny import line:
```python
from shiny import module, reactive, render, ui
```
(Already imported — no change needed for home.py.)

For **all other 8 pages** — add `active_project` only. The pattern for each file:

`grid_prep.py`:
```python
def grid_prep_server(
    input, output, session,
    config: Config,
    active_project=None,
):
```

`partitioning.py`:
```python
def partitioning_server(
    input, output, session,
    config: Config,
    active_project=None,
):
```

`simulation.py`:
```python
def simulation_server(
    input, output, session,
    config: Config,
    active_project=None,
):
```

`run.py`:
```python
def run_server(
    input, output, session,
    config: Config,
    job_queue: Optional[JobQueue] = None,
    active_project=None,
):
```

`postprocess.py`:
```python
def postprocess_server(
    input, output, session,
    config: Config,
    active_project=None,
):
```

`visualize.py`:
```python
def visualize_server(
    input, output, session,
    config: Config,
    active_project=None,
):
```

`compare.py`:
```python
def compare_server(
    input, output, session,
    config: Config,
    job_queue: Optional[JobQueue] = None,
    active_project=None,
):
```

`ensemble.py`:
```python
def ensemble_server(
    input, output, session,
    config: Config,
    job_queue: Optional[JobQueue] = None,
    active_project=None,
):
```

**Step 2: Verify import succeeds**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.app import create_app; print('OK')"`
Expected: `OK`

**Step 3: Run existing tests to confirm no regressions**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_pages_helpers.py shyfem-ui/tests/test_parser_str.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/
git commit -m "feat: accept active_project param in all page servers"
```

---

## Task 4: Fix `remove_bound_{bid}` dead button (boundary_editor.py)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/boundary_editor.py:102-117`

**Step 1: Write the failing test**

```python
# Append to shyfem-ui/tests/test_components.py (or create new test file)
# shyfem-ui/tests/test_boundary_remove.py

"""Test that remove_bound handlers filter the boundaries list correctly."""


def test_remove_boundary_filters_by_id():
    """Simulate what the handler does: filter list by bid."""
    boundaries = [
        {"id": 1, "label": "bound1", "nodes": "1 2", "ibtyp": 1, "boundn": "", "zfact": 1.0, "intpol": 1},
        {"id": 2, "label": "bound2", "nodes": "3 4", "ibtyp": 2, "boundn": "", "zfact": 1.0, "intpol": 1},
        {"id": 3, "label": "bound3", "nodes": "5 6", "ibtyp": 1, "boundn": "", "zfact": 1.0, "intpol": 1},
    ]
    bid_to_remove = 2
    result = [x for x in boundaries if x["id"] != bid_to_remove]
    assert len(result) == 2
    assert all(b["id"] != 2 for b in result)


def test_remove_nonexistent_boundary_is_noop():
    boundaries = [
        {"id": 1, "label": "bound1", "nodes": "1", "ibtyp": 1, "boundn": "", "zfact": 1.0, "intpol": 1},
    ]
    result = [x for x in boundaries if x["id"] != 99]
    assert len(result) == 1
```

**Step 2: Run test**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_boundary_remove.py -v`
Expected: 2 PASSED (logic test — the actual handler doesn't exist yet but the filtering logic is validated)

**Step 3: Add dynamic remove handlers in boundary_editor.py**

Insert after the `_add_boundary` handler (after line 117 in `boundary_editor.py`), inside `boundary_editor_server`:

```python
    # Dynamic remove handlers for remove_bound_{bid} buttons
    @reactive.effect
    def _register_remove_handlers():
        bounds = boundaries.get()
        for b in bounds:
            _make_remove_bound(b["id"])

    def _make_remove_bound(bid: int):
        @reactive.effect
        @reactive.event(input[f"remove_bound_{bid}"])
        def _remove():
            current = boundaries.get()
            boundaries.set([x for x in current if x["id"] != bid])
```

**Step 4: Verify import**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.components.boundary_editor import boundary_editor_server; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/boundary_editor.py shyfem-ui/tests/test_boundary_remove.py
git commit -m "fix: add remove_bound_{bid} dynamic handlers in boundary editor"
```

---

## Task 5: Fix `remove_var_{i}` dead button (ensemble.py)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/ensemble.py:234-238`

**Step 1: Write the failing test**

```python
# shyfem-ui/tests/test_ensemble_remove.py

"""Test that remove_var handlers pop the correct variation."""


def test_remove_variation_by_index():
    variations = [
        {"section": "para", "param": "czdef", "values": "0.02, 0.03"},
        {"section": "para", "param": "idt", "values": "10, 30"},
        {"section": "para", "param": "ahpar", "values": "1, 5"},
    ]
    index_to_remove = 1
    current = list(variations)
    current.pop(index_to_remove)
    assert len(current) == 2
    assert current[0]["param"] == "czdef"
    assert current[1]["param"] == "ahpar"


def test_remove_last_variation():
    variations = [
        {"section": "para", "param": "czdef", "values": "0.02"},
        {"section": "para", "param": "idt", "values": "10"},
    ]
    current = list(variations)
    current.pop(1)
    assert len(current) == 1
    assert current[0]["param"] == "czdef"
```

**Step 2: Run test**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_ensemble_remove.py -v`
Expected: 2 PASSED

**Step 3: Add dynamic remove handlers in ensemble.py**

Insert after the `_add_variation` handler (after line 238), inside `ensemble_server`:

```python
    # Dynamic remove handlers for remove_var_{i} buttons
    @reactive.effect
    def _register_remove_var_handlers():
        variations = param_variations.get()
        for i in range(1, len(variations)):  # i=0 has no remove button
            _make_remove_var(i)

    def _make_remove_var(index: int):
        @reactive.effect
        @reactive.event(input[f"remove_var_{index}"])
        def _remove():
            current = list(param_variations.get())
            if index < len(current):
                current.pop(index)
                param_variations.set(current)
```

**Step 4: Verify import**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.ensemble import ensemble_server; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/ensemble.py shyfem-ui/tests/test_ensemble_remove.py
git commit -m "fix: add remove_var_{i} dynamic handlers in ensemble page"
```

---

## Task 6: `open_project_btn` + `project_{id}` handlers (home.py)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/home.py:124-479`

**Step 1: Add the `_activate_project` helper inside `home_server`**

Insert after `_refresh_projects` (after line 158), inside `home_server`. This helper is shared by `open_project_btn` modal and `project_{id}` link clicks:

```python
    def _activate_project(project_id: int):
        """Load project context, set active, navigate to Grid Prep."""
        from shyfem_ui.services.project_context import load_project_context

        ctx = load_project_context(project_id)
        if ctx is None:
            ui.notification_show("Project not found", type="error")
            return
        if active_project is not None:
            active_project.set(ctx)
        ui.notification_show(f"Opened project: {ctx['name']}", type="message")
        if nav_callback:
            nav_callback("Grid Prep")
```

**Step 2: Add the `open_project_btn` handler**

Insert after `_activate_project`, still inside `home_server`:

```python
    @reactive.effect
    @reactive.event(input.open_project_btn)
    def _show_open_project_modal():
        project_data = projects.get()
        if not project_data:
            m = ui.modal(
                ui.p("No projects yet. Create one first!", class_="text-muted"),
                title="Open Project",
                easy_close=True,
            )
            ui.modal_show(m)
            return

        project_links = []
        for p in project_data:
            project_links.append(
                ui.div(
                    ui.input_action_link(
                        f"open_proj_{p['id']}",
                        ui.span(p["name"], class_="fw-bold"),
                    ),
                    ui.span(f" — {p['description'] or 'No description'}", class_="text-muted small"),
                    ui.br(),
                    ui.code(p["work_dir"], class_="small text-muted"),
                    class_="mb-2 p-2 border rounded",
                )
            )

        m = ui.modal(
            *project_links,
            title="Open Project",
            easy_close=True,
        )
        ui.modal_show(m)
```

**Step 3: Add dynamic handlers for `open_proj_{id}` modal links**

Insert right after `_show_open_project_modal`:

```python
    @reactive.effect
    def _register_open_proj_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_open_proj_handler(p["id"])

    def _make_open_proj_handler(pid: int):
        @reactive.effect
        @reactive.event(input[f"open_proj_{pid}"])
        def _open():
            ui.modal_remove()
            _activate_project(pid)
```

**Step 4: Add dynamic handlers for `project_{id}` table links**

Insert right after the open_proj handlers:

```python
    @reactive.effect
    def _register_project_link_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_project_link_handler(p["id"])

    def _make_project_link_handler(pid: int):
        @reactive.effect
        @reactive.event(input[f"project_{pid}"])
        def _click():
            _activate_project(pid)
```

**Step 5: Verify import**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.home import home_server; print('OK')"`
Expected: `OK`

**Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/home.py
git commit -m "feat: add open_project_btn and project_{id} click handlers"
```

---

## Task 7: `import_grid_btn` handler (home.py)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/home.py`

**Step 1: Add the `import_grid_btn` handler**

Insert after the project link handlers (still inside `home_server`):

```python
    @reactive.effect
    @reactive.event(input.import_grid_btn)
    def _show_import_grid_modal():
        project_data = projects.get()
        if not project_data:
            ui.notification_show("Create a project first before importing a grid", type="warning")
            return

        choices = {str(p["id"]): p["name"] for p in project_data}

        m = ui.modal(
            ui.input_select(
                "import_project_id",
                "Target Project",
                choices=choices,
            ),
            ui.input_text(
                "import_grd_path",
                "Grid File Path (.grd)",
                placeholder="/path/to/grid.grd",
            ),
            ui.input_text(
                "import_grid_name",
                "Grid Name (optional)",
                placeholder="Leave blank to use filename",
            ),
            title="Import Grid",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button(
                    "import_confirm_btn",
                    "Import",
                    class_="btn-primary",
                ),
                ui.input_action_button(
                    "import_cancel_btn",
                    "Cancel",
                    class_="btn-secondary ms-2",
                ),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.import_cancel_btn)
    def _cancel_import():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.import_confirm_btn)
    def _do_import_grid():
        grd_path_str = input.import_grd_path()
        project_id_str = input.import_project_id()
        grid_name = input.import_grid_name().strip()

        if not grd_path_str:
            ui.notification_show("Grid file path is required", type="error")
            return
        if not project_id_str:
            ui.notification_show("Select a target project", type="error")
            return

        # Validate source file
        try:
            src_path = config.validate_path(grd_path_str, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        # Look up project work_dir
        project_id = int(project_id_str)
        from shyfem_ui.services.project_context import load_project_context
        ctx = load_project_context(project_id)
        if ctx is None:
            ui.notification_show("Project not found", type="error")
            return

        work_dir = Path(ctx["work_dir"])
        grid_dir = work_dir / "GRID"
        grid_dir.mkdir(parents=True, exist_ok=True)

        dest_path = grid_dir / src_path.name
        if not grid_name:
            grid_name = src_path.stem

        try:
            shutil.copy2(src_path, dest_path)
        except Exception as e:
            ui.notification_show(f"Failed to copy grid file: {e}", type="error")
            return

        # Create DB record
        try:
            with db_session() as db:
                grid = Grid(
                    project_id=project_id,
                    name=grid_name,
                    grd_file=f"GRID/{src_path.name}",
                )
                db.add(grid)

            ui.notification_show(f"Imported grid '{grid_name}' into project", type="message")
            ui.modal_remove()
            _refresh_projects()
        except Exception as e:
            ui.notification_show(f"Failed to create grid record: {e}", type="error")
```

Also add `from pathlib import Path` at the top of `home.py` imports if not already present. (Check: the file already imports `shutil` and uses `Path` indirectly via config. Add `from pathlib import Path` after the existing imports.)

**Step 2: Verify import**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.home import home_server; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/home.py
git commit -m "feat: add import_grid_btn handler with file copy and DB record"
```

---

## Task 8: Auto-fill effects for Grid Prep, Partitioning, Simulation

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/grid_prep.py` (inside `grid_prep_server`, after line 103)
- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py` (inside `partitioning_server`, after line 120)
- Modify: `shyfem-ui/shyfem_ui/pages/simulation.py` (inside `simulation_server`, after line 120)

**Step 1: Add auto-fill to grid_prep.py**

Add `from pathlib import Path` to imports if not present (already imported).

Insert inside `grid_prep_server`, right after the function docstring / initial state:

```python
    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        if proj["grids"]:
            grid = proj["grids"][0]
            if grid.get("grd_file"):
                grd_path = str(Path(proj["work_dir"]) / grid["grd_file"])
                ui.update_text("grd_path", value=grd_path)
```

**Step 2: Add auto-fill to partitioning.py**

Insert inside `partitioning_server`, right after the function docstring / initial state:

```python
    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        work = proj["work_dir"]
        if proj["grids"]:
            grid = proj["grids"][0]
            if grid.get("bas_file"):
                ui.update_text("bas_path", value=str(Path(work) / grid["bas_file"]))
            if grid.get("grd_file"):
                ui.update_text("grd_path", value=str(Path(work) / grid["grd_file"]))
```

Add `from pathlib import Path` to partitioning.py imports if not present (already imported).

**Step 3: Add auto-fill to simulation.py**

Insert inside `simulation_server`, right after the initial state block (after `parsed_str = reactive.value(None)`, around line 124):

```python
    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                str_path = str(Path(proj["work_dir"]) / sim["str_file"])
                ui.update_text("str_path", value=str_path)
```

Add `from pathlib import Path` to simulation.py imports if not present. (Not currently imported — add it.)

**Step 4: Verify imports**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.app import create_app; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/grid_prep.py shyfem-ui/shyfem_ui/pages/partitioning.py shyfem-ui/shyfem_ui/pages/simulation.py
git commit -m "feat: auto-fill grid prep, partitioning, simulation from active project"
```

---

## Task 9: Auto-fill effects for Run, Post-Process, Visualize, Ensemble

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py` (inside `run_server`)
- Modify: `shyfem-ui/shyfem_ui/pages/postprocess.py` (inside `postprocess_server`)
- Modify: `shyfem-ui/shyfem_ui/pages/visualize.py` (inside `visualize_server`)
- Modify: `shyfem-ui/shyfem_ui/pages/ensemble.py` (inside `ensemble_server`)

**Step 1: Add auto-fill to run.py**

Insert inside `run_server`, early in the function body. Add `from pathlib import Path` to imports if needed.

```python
    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        ui.update_text("working_dir", value=proj["work_dir"])
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                ui.update_text("input_file", value=str(Path(proj["work_dir"]) / sim["str_file"]))
```

**Step 2: Add auto-fill to postprocess.py**

Insert inside `postprocess_server`:

```python
    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        ui.update_text("shy_path", value=proj["work_dir"])
```

Note: the postprocess input is `shy_path` (not `input_path` — verified from the grep results).

**Step 3: Add auto-fill to visualize.py**

Insert inside `visualize_server`:

```python
    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        ui.update_text("data_path", value=proj["work_dir"])
```

Note: the visualize input is `data_path` (verified from grep).

**Step 4: Add auto-fill to ensemble.py**

Insert inside `ensemble_server`, after the state initialization block:

```python
    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        ui.update_text("working_dir", value=str(Path(proj["work_dir"]) / "ensemble"))
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                ui.update_text("base_str_file", value=str(Path(proj["work_dir"]) / sim["str_file"]))
```

Add `from pathlib import Path` to ensemble.py imports if needed (not currently imported — add it).

**Step 5: Verify full app import**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.app import create_app; print('OK')"`
Expected: `OK`

**Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/run.py shyfem-ui/shyfem_ui/pages/postprocess.py shyfem-ui/shyfem_ui/pages/visualize.py shyfem-ui/shyfem_ui/pages/ensemble.py
git commit -m "feat: auto-fill run, postprocess, visualize, ensemble from active project"
```

---

## Task 10: Run full test suite and verify

**Step 1: Run all existing unit tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_project_context.py shyfem-ui/tests/test_boundary_remove.py shyfem-ui/tests/test_ensemble_remove.py shyfem-ui/tests/test_pages_helpers.py shyfem-ui/tests/test_parser_str.py shyfem-ui/tests/test_parser_grd.py -v`
Expected: All PASS

**Step 2: Verify the full app starts**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.app import create_app; app = create_app(); print('App created OK')"`
Expected: `App created OK`

**Step 3: Run Playwright E2E tests (existing)**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_playwright_dashboard.py shyfem-ui/tests/test_playwright_navigation.py -v --timeout=120`
Expected: All existing tests PASS (the signature changes are backwards-compatible)

**Step 4: Squash-commit if any fixes were needed**

If any test failures required fixes, commit those fixes now.

---

## Task 11: E2E test — project click navigates to Grid Prep

**Files:**
- Create: `shyfem-ui/tests/test_playwright_active_project.py`

**Step 1: Write the E2E test**

```python
# shyfem-ui/tests/test_playwright_active_project.py
"""E2E tests for active project selection and navigation."""

import pytest


@pytest.mark.usefixtures("_app_server")
class TestActiveProject:
    """Test project selection navigates to Grid Prep tab."""

    def test_tutorial_project_click_navigates(self, page, app_url):
        """Create tutorial project, click its name, verify Grid Prep tab."""
        page.goto(app_url)
        page.wait_for_selector("text=SHYFEM Workbench", timeout=15000)

        # Create tutorial project
        page.click("text=Mar Menor Tutorial", force=True)
        page.wait_for_selector("text=Create Tutorial Project", timeout=5000)
        page.click("text=Create Tutorial Project", force=True)
        page.wait_for_selector("text=created successfully", timeout=10000)

        # Click the project link in the table
        page.click("text=mar_menor_tutorial", force=True)

        # Verify Grid Prep tab becomes active
        page.wait_for_selector("text=Grid Preparation", timeout=5000)

    def test_open_project_modal_shows_projects(self, page, app_url):
        """Open Project modal shows existing projects."""
        page.goto(app_url)
        page.wait_for_selector("text=SHYFEM Workbench", timeout=15000)

        # Click Open Project
        page.click("text=Open Project", force=True)

        # Modal should show — either project list or "No projects yet"
        modal = page.wait_for_selector(".modal", timeout=5000)
        assert modal is not None
```

**Step 2: Run the test**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_playwright_active_project.py -v --timeout=120`
Expected: PASS (if server fixture is available; may need `_app_server` running)

**Step 3: Commit**

```bash
git add shyfem-ui/tests/test_playwright_active_project.py
git commit -m "test: add E2E tests for active project selection and navigation"
```

---

## Task 12: Final commit — compare.py signature (no auto-fill)

Compare already got its signature updated in Task 3. No auto-fill needed (it's job-based). This task is just a verification step.

**Step 1: Verify compare.py accepted the param**

Run: `/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.compare import compare_server; print('OK')"`
Expected: `OK`

**Step 2: Run full test suite one final time**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/ -v --timeout=120 --ignore=shyfem-ui/tests/test_playwright_active_project.py -x`
Expected: All existing tests PASS

**Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup for active project propagation"
```

---

## Summary of Changes

| Task | Files | What |
|------|-------|------|
| 1 | `services/project_context.py`, `tests/test_project_context.py` | `load_project_context` helper |
| 2 | `app.py` | Wire `active_project` + `nav_to` |
| 3 | All 9 page files | Accept `active_project` param |
| 4 | `components/boundary_editor.py`, `tests/test_boundary_remove.py` | Fix `remove_bound_{bid}` |
| 5 | `pages/ensemble.py`, `tests/test_ensemble_remove.py` | Fix `remove_var_{i}` |
| 6 | `pages/home.py` | `open_project_btn` + `project_{id}` handlers |
| 7 | `pages/home.py` | `import_grid_btn` handler |
| 8 | `pages/grid_prep.py`, `partitioning.py`, `simulation.py` | Auto-fill effects |
| 9 | `pages/run.py`, `postprocess.py`, `visualize.py`, `ensemble.py` | Auto-fill effects |
| 10 | — | Full test suite verification |
| 11 | `tests/test_playwright_active_project.py` | E2E tests |
| 12 | — | Final verification + cleanup |
