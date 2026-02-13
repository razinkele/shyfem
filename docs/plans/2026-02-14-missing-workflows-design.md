# Design: Complete Missing Workflows and Functions

**Date:** 2026-02-14
**Scope:** SHYFEM UI — 5 dead buttons + active project state propagation

---

## Problem

The SHYFEM UI has 60+ buttons across 8 pages and 6 components. Five buttons have no event handlers — they render but do nothing when clicked. Additionally, there is no concept of an "active project" flowing between pages, so users must manually re-enter file paths on every tab.

### Dead Buttons

| # | File | Button ID | Expected Behavior |
|---|------|-----------|-------------------|
| 1 | `home.py` | `open_project_btn` | Open existing project from DB list |
| 2 | `home.py` | `import_grid_btn` | Import .grd file into a project |
| 3 | `home.py` | `project_{id}` links | Click project row to activate it |
| 4 | `ensemble.py` | `remove_var_{i}` | Remove parameter variation row |
| 5 | `boundary_editor.py` | `remove_bound_{bid}` | Remove boundary condition card |

---

## Approach: Full Active Project Propagation (Approach C)

Fix all 5 dead buttons AND introduce a shared `active_project` reactive value that propagates to every page, auto-filling file path inputs when the user selects a project.

---

## 1. Active Project State

### 1.1 Data Shape

```python
# reactive.value stored in app.py, passed to all page servers
active_project: reactive.Value[Optional[dict]] = reactive.value(None)

# Shape when set:
{
    "id": int,              # DB project.id
    "name": str,            # "mar_menor_tutorial"
    "work_dir": str,        # "/home/.../projects/mar_menor_tutorial"
    "description": str,     # optional
    "grids": [              # list of grid dicts
        {
            "name": "MM_coarse",
            "grd_file": "GRID/MM_coarse.grd",
            "bas_file": "GRID/MM_coarse.bas",
        }
    ],
    "simulations": [        # list of simulation dicts
        {
            "name": "mm_hyd_00",
            "str_file": "mm_hyd_00.str",
        }
    ],
}
```

### 1.2 Creation Point

In `app.py:_build_server()`:
```python
active_project = reactive.value(None)
```

Passed to every page server as a keyword argument. Also create a `nav_callback` for cross-module tab navigation:
```python
def nav_to(tab_name: str):
    ui.update_navs("main_navbar", selected=tab_name, session=session)
```

### 1.3 Helper: Load Project from DB

Shared utility function (in `home.py` or a new `utils.py`):
```python
def load_project_context(project_id: int) -> dict:
    """Load full project with grids and simulations from DB."""
    with db_session() as db:
        project = db.query(Project).get(project_id)
        grids = db.query(Grid).filter_by(project_id=project_id).all()
        sims = db.query(Simulation).filter_by(project_id=project_id).all()
        return {
            "id": project.id,
            "name": project.name,
            "work_dir": project.work_dir,
            "description": project.description,
            "grids": [{"name": g.name, "grd_file": g.grd_file, "bas_file": g.bas_file} for g in grids],
            "simulations": [{"name": s.name, "str_file": s.str_file} for s in sims],
        }
```

---

## 2. Dead Button Implementations

### 2.1 `open_project_btn` (home.py)

**Handler**: `_show_open_project_modal()`

Opens a modal listing all DB projects. Each project rendered as a clickable `input_action_link`. Clicking one:
1. Calls `load_project_context(project_id)`
2. Sets `active_project.set(context)`
3. Closes modal with `ui.modal_remove()`
4. Calls `nav_callback("Grid Prep")` to switch tabs
5. Shows notification "Opened project: {name}"

Dynamic link handlers are registered inside a `@reactive.effect` that watches the projects list.

### 2.2 `import_grid_btn` (home.py)

**Handler**: `_show_import_grid_modal()`

Modal with:
- `input_select("import_project")` — dropdown of DB projects
- `input_text("import_grd_path")` — text input for .grd file path
- `input_text("import_grid_name")` — optional name (defaults to filename stem)

On confirm (`import_confirm_btn`):
1. Validate .grd path exists via `config.validate_path()`
2. Copy file to `project.work_dir / "GRID" / filename` via `shutil.copy2()`
3. Create `Grid` DB record with `grd_file = "GRID/{filename}"`
4. Show success notification
5. Refresh projects list

### 2.3 `project_{id}` Links (home.py)

Same behavior as selecting from the open-project modal:
1. Load project context
2. Set `active_project`
3. Navigate to Grid Prep

Implementation: register dynamic handlers for each project link ID inside the `projects_list` render or a reactive effect watching the projects list.

### 2.4 `remove_var_{i}` (ensemble.py)

**Handler**: Dynamic removal handlers registered via reactive effect.

When `param_variations` changes (and thus the UI re-renders with new buttons), register handlers for each `remove_var_{i}` button. Each handler pops index `i` from the variations list and re-sets `param_variations`.

```python
@reactive.effect
def _register_remove_handlers():
    variations = param_variations.get()
    for i in range(1, len(variations)):  # skip i=0, no remove button
        _make_remove_var(i)

def _make_remove_var(index: int):
    @reactive.effect
    @reactive.event(input[f"remove_var_{index}"])
    def handler():
        current = list(param_variations.get())
        if index < len(current):
            current.pop(index)
            param_variations.set(current)
```

### 2.5 `remove_bound_{bid}` (boundary_editor.py)

Same pattern as 2.4 but using the stable boundary `id` field:

```python
@reactive.effect
def _register_remove_handlers():
    bounds = boundaries.get()
    for b in bounds:
        _make_remove_bound(b["id"])

def _make_remove_bound(bid: int):
    @reactive.effect
    @reactive.event(input[f"remove_bound_{bid}"])
    def handler():
        current = boundaries.get()
        boundaries.set([x for x in current if x["id"] != bid])
```

---

## 3. Auto-fill Per Page

When `active_project` changes to a non-None value, each page auto-fills its text inputs using `ui.update_text()`. Auto-fill only updates the input value — it does NOT auto-trigger load buttons. The user remains in control.

| Page | Input(s) Auto-filled | Source |
|------|---------------------|--------|
| Grid Prep | `grd_path` | `work_dir / grids[0].grd_file` |
| Partitioning | `bas_path`, `grd_path` | `work_dir / grids[0].bas_file`, `.grd_file` |
| Simulation | `str_path` | `work_dir / simulations[0].str_file` |
| Run | `input_file`, `working_dir` | `work_dir / simulations[0].str_file`, `work_dir` |
| Post-Process | `input_path` | `work_dir` |
| Visualize | `file_path` | `work_dir` |
| Compare | (no auto-fill) | Job-based, not file-based |
| Ensemble | `base_str_file`, `working_dir` | `work_dir / simulations[0].str_file`, `work_dir / "ensemble"` |

Each page adds a simple `@reactive.effect` like:
```python
@reactive.effect
def _on_project_changed():
    proj = active_project.get()
    if proj is None:
        return
    if proj["grids"]:
        grid = proj["grids"][0]
        grd_path = str(Path(proj["work_dir"]) / grid["grd_file"])
        ui.update_text("grd_path", value=grd_path)
```

If no grids or simulations exist in the project, auto-fill is skipped for those fields; only `work_dir`-derived fields are filled.

---

## 4. App.py Wiring Changes

### 4.1 `_build_server` Signature Changes

```python
def _build_server(input, output, session, config: Config, job_queue: JobQueue):
    active_project = reactive.value(None)

    def nav_to(tab_name: str):
        ui.update_navs("main_navbar", selected=tab_name, session=session)

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

### 4.2 Page Server Signature Changes

Each `*_server` function adds `active_project: reactive.Value = None` as an optional keyword argument. Pages that don't use it yet simply ignore it (backwards compatible).

---

## 5. Error Handling

- **No projects in DB**: "Open Project" modal shows "No projects yet. Create one first."
- **Import grid with no projects**: Modal shows warning, confirm button disabled
- **Active project with missing work_dir**: On auto-fill, check `Path(work_dir).exists()`. If missing, show error notification and set `active_project` to None
- **Dynamic button handler lifecycle**: Shiny re-registers handlers on re-render. Use stable IDs (boundary `bid`, variation index) to avoid stale closures
- **Tab navigation from module scope**: `nav_callback` is a plain Python callable passed as argument, avoids session scope issues

---

## 6. Testing

### Unit Tests
- `test_open_project_modal`: Verify modal renders with project list
- `test_import_grid_copies_file`: Verify .grd file copied + Grid DB record created
- `test_remove_var_handler`: Add 3 variations, remove middle one, verify list updated
- `test_remove_bound_handler`: Add 2 boundaries, remove first, verify list updated

### E2E Tests (Playwright)
- `test_project_click_navigates`: Create tutorial project, click project link, verify Grid Prep tab is active
- `test_open_project_modal_lists_projects`: Create project, click "Open Project", verify modal shows project name
- `test_import_grid_creates_record`: Import .grd via modal, verify file exists in project dir

---

## Files Modified

| File | Changes |
|------|---------|
| `app.py` | Add `active_project`, `nav_to`, pass to all page servers |
| `home.py` | Add `open_project_btn`, `import_grid_btn`, `project_{id}` handlers; accept `active_project` + `nav_callback` |
| `ensemble.py` | Add `remove_var_{i}` handlers; accept `active_project`, add auto-fill effect |
| `boundary_editor.py` | Add `remove_bound_{bid}` handlers |
| `grid_prep.py` | Accept `active_project`, add auto-fill effect |
| `partitioning.py` | Accept `active_project`, add auto-fill effect |
| `simulation.py` | Accept `active_project`, add auto-fill effect |
| `run.py` | Accept `active_project`, add auto-fill effect |
| `postprocess.py` | Accept `active_project`, add auto-fill effect |
| `visualize.py` | Accept `active_project`, add auto-fill effect |
| `compare.py` | Accept `active_project` (no auto-fill) |
