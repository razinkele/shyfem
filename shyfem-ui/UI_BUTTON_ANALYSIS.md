# SHYFEM UI — Button & Workflow Analysis

**Date:** 2026-02-13
**Scope:** All 9 pages, 8 components, services, database models, and test coverage

---

## 1. Complete Button Inventory

### 1.1 Dashboard (home.py) — 4 static buttons, 4 modal buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `new_project_btn` | New Project | `_show_new_project_modal` | Opens modal with name, description, dir fields |
| `open_project_btn` | Open Project | *None* | **BUG: No handler** |
| `import_grid_btn` | Import Grid | *None* | **BUG: No handler** |
| `tutorial_btn` | Mar Menor Tutorial | `_show_tutorial_modal` | Opens tutorial info modal |
| `create_project_btn` | Create (modal) | `_create_project` | DB insert + mkdir |
| `cancel_create_btn` | Cancel (modal) | `_hide_modal` | `ui.modal_remove()` |
| `confirm_tutorial_btn` | Create Tutorial Project (modal) | `_create_tutorial_project` | copytree + DB records |
| `cancel_tutorial_btn` | Cancel (modal) | `_hide_tutorial_modal` | `ui.modal_remove()` |
| `project_{id}` (dynamic) | Project name link | *None* | **BUG: No click handler** |

### 1.2 Grid Preparation (grid_prep.py) — 5 buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `browse_grd_btn` | Browse | `_browse_grd` | Opens file browser for .grd |
| `load_grid_btn` | Load Grid | `_load_grid` | Parses .grd, renders map |
| `run_shypre_btn` | Run shypre | `_run_shypre` | Submits shypre job |
| `run_shybas_btn` | Run shybas | `_run_shybas` | Submits shybas job |
| `refresh_stats_btn` | Refresh | `_refresh_stats` | Reloads grid statistics |

### 1.3 Partitioning (partitioning.py) — 3 buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `load_bas_btn` | Load Basin | `_load_bas` | Loads .bas file |
| `run_partition_btn` | Run Partitioning | `_run_partition` | Submits shyparts job |
| `refresh_partition_btn` | Refresh | `_refresh` | Reloads partition stats |

### 1.4 Simulation (simulation.py) — 7 static buttons, 2 modal buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `load_btn` | Load | `_load_file` | Parses .str from path |
| `new_btn` | New | `_new_file` | Creates template StrFile |
| `save_as_btn` | Save As... | `_show_save_modal` | Opens save modal (dynamic) |
| `apply_quick_btn` | Apply Quick Settings | `_apply_quick_settings` | Merges quick params into parsed_str |
| `load_template_btn` | Load Template | `_load_template` | Loads from dropdown |
| `toggle_boundary_btn` | Toggle Boundary Editor | *render toggle* | Shows/hides boundary component |
| `validate_btn` | Validate | `_validate` | Checks .str syntax |
| `confirm_save_btn` | Save (modal) | `_save_file` | Writes to disk |
| `cancel_save_btn` | Cancel (modal) | `_cancel_save` | `ui.modal_remove()` |

### 1.5 Run (run.py) — 8 buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `submit_btn` | Submit Job | `_submit_job` | Creates JobSpec, submits to queue |
| `cancel_job_btn` | Cancel | `_cancel_job` | Cancels running job |
| `refresh_jobs_btn` | Refresh | `_refresh_jobs` | Reloads job list |
| `clear_completed_btn` | Clear Completed | `_clear_completed` | Removes finished jobs |
| `browse_str_btn` | Browse .str | `_browse_str` | File picker |
| `browse_bas_btn` | Browse .bas | `_browse_bas` | File picker |
| `download_log_btn` | Download Log | `_download_log` | data URI download |
| `view_output_btn` | View Output | `_view_output` | Shows output directory listing |

### 1.6 Post-Process (postprocess.py) — 5 buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `browse_input_btn` | Browse | `_browse_input` | File picker for .shy/.ext |
| `run_shyelab_btn` | Run shyelab | `_run_shyelab` | Submits shyelab job |
| `refresh_output_btn` | Refresh | `_refresh_output` | Reloads output listing |
| `batch_run_btn` | Run Batch | `_run_batch` | Multi-variable extraction |
| `download_output_btn` | Download | `_download_output` | data URI download |

### 1.7 Visualize (visualize.py) — 5 buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `load_data_btn` | Load Data | `_load_data` | Reads .shy/.ext/.nc |
| `browse_file_btn` | Browse | `_browse_file` | File picker |
| `update_plot_btn` | Update Plot | `_update_plot` | Re-renders Plotly figure |
| `export_plot_btn` | Export | `_export_plot` | Saves plot as PNG/HTML |
| `reset_view_btn` | Reset View | `_reset_view` | Restores default plot settings |

### 1.8 Compare (compare.py) — 4 buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `add_job_btn` | Add Job | `_add_job` | Adds job to comparison set |
| `remove_job_btn` | Remove | `_remove_job` | Removes from set |
| `compare_btn` | Compare | `_run_compare` | Generates diff table + overlaid plots |
| `export_report_btn` | Export Report | `_export_report` | HTML report generation |

### 1.9 Ensemble (ensemble.py) — 6 buttons + dynamic buttons

| Button ID | Label | Handler | Behaviour |
|-----------|-------|---------|-----------|
| `browse_base_btn` | Browse | `_browse_base` | File picker for base .str |
| `add_var_btn` | Add Variable | `_add_var` | Adds parameter to sweep grid |
| `remove_var_{i}` (dynamic) | Remove | **BUG: No handler** | Button registered but never @reactive.event |
| `submit_ensemble_btn` | Submit Ensemble | `_submit_ensemble` | Submits all combinations |
| `cancel_ensemble_btn` | Cancel All | `_cancel_ensemble` | Cancels running sweep |
| `refresh_ensemble_btn` | Refresh | `_refresh_ensemble` | Reloads status |
| `plot_envelope_btn` | Plot Envelope | `_plot_envelope` | Generates envelope plot |

### 1.10 Components — Additional Buttons

**str_editor.py:**
| Button ID | Label | Handler |
|-----------|-------|---------|
| `add_section_btn` | Add Section | `_add_section` |

**boundary_editor.py:**
| Button ID | Label | Handler |
|-----------|-------|---------|
| `add_bound_btn` | Add Boundary | `_add_boundary` |
| `import_csv_btn` | Import CSV | `_import_csv` |
| `generate_btn` | Generate Section | `_generate_section` |
| `remove_bound_{bid}` (dynamic) | Remove | **BUG: No handler** |

**log_viewer.py:**
| Button ID | Label | Handler |
|-----------|-------|---------|
| `download_log_btn` | Download | `_download_log` |
| `search_btn` | Search | `_search_log` |
| `clear_search_btn` | Clear | `_clear_search` |

**file_browser.py:**
| Button ID | Label | Handler |
|-----------|-------|---------|
| `select_btn` | Select | `_select_file` |
| `up_btn` | Up | `_go_up` |

---

## 2. Bug Summary

| # | Location | Bug | Severity |
|---|----------|-----|----------|
| 1 | `home.py` | `open_project_btn` — no handler | Medium |
| 2 | `home.py` | `import_grid_btn` — no handler | Medium |
| 3 | `home.py` | `project_{id}` action links — no click handler | Low |
| 4 | `ensemble.py` | `remove_var_{i}` dynamic buttons — no handler | Medium |
| 5 | `boundary_editor.py` | `remove_bound_{bid}` dynamic buttons — no handler | Medium |

---

## 3. Mar Menor Tutorial Workflow — Deep Analysis

### 3.1 Entry Point

The tutorial is triggered from the Dashboard page by clicking `tutorial_btn` (ID: `home-tutorial_btn` after module namespacing).

### 3.2 Tutorial Data Structure

Defined at module level in `home.py:15-46`:

```python
TUTORIAL_PHASES = [
    ("1. Basic Hydrodynamics",    "Minimal setup, output, wind forcing, friction",
     ["mm_hyd_00", "mm_hyd_01", "mm_hyd_02", "mm_hyd_03"]),
    ("2. Tidal Boundaries",       "Sea level boundary conditions",
     ["mm_hyd_11", "mm_hyd_12", "mm_hyd_13"]),
    ("3. Coriolis & Rivers",      "Coriolis force, advection, river discharge",
     ["mm_hyd_21", "mm_hyd_22", "mm_hyd_23"]),
    ("4. Salinity (3D)",          "Baroclinic salinity transport",
     ["mm_hyd_31"]),
    ("5. Temperature (3D)",       "Full 3D with temperature and turbulence",
     ["mm_hyd_41", "mm_hyd_42"]),
    ("6. Advanced Numerics",      "Non-linear free surface, Smagorinsky diffusion",
     ["mm_hyd_43"]),
]
```

Total: **6 phases, 14 .str configuration files**.

### 3.3 Step-by-Step Execution Flow

```
User clicks "Mar Menor Tutorial" button
        │
        ▼
┌─ _show_tutorial_modal() ─────────────────────────────────┐
│  Creates ui.modal() dynamically with:                    │
│   - Description text                                     │
│   - input_text("tutorial_project_name", default="mar_menor_tutorial") │
│   - Ordered list of 6 phases with .str file names        │
│   - footer: [Create Tutorial Project] [Cancel]           │
│  Calls ui.modal_show(m)                                  │
└──────────────────────────────────────────────────────────┘
        │
        ▼  User clicks "Create Tutorial Project"
        │
┌─ _create_tutorial_project() ─────────────────────────────┐
│                                                          │
│  1. READ input                                           │
│     name = input.tutorial_project_name().strip()         │
│     Validate non-empty                                   │
│                                                          │
│  2. CHECK source directory                               │
│     mar_menor_src = config.testcases_dir / "mar_menor"   │
│     = {shyfem_dir}/testcases/examples/mar_menor          │
│     Must exist as directory                              │
│                                                          │
│  3. CREATE project directory                             │
│     project_path = config.work_dir / name                │
│     = ~/.shyfem-ui/projects/mar_menor_tutorial           │
│     config.ensure_work_dir() — creates parents           │
│     Check NOT already existing (error if so)             │
│     shutil.copytree(mar_menor_src, project_path)         │
│                                                          │
│  4. CREATE database records (in transaction)             │
│     a) Project row:                                      │
│        name = "mar_menor_tutorial"                       │
│        description = "Mar Menor tutorial — 6-phase..."   │
│        work_dir = str(project_path)                      │
│     b) Grid row:                                         │
│        project_id = project.id                           │
│        name = "MM_coarse"                                │
│        grd_file = "GRID/MM_coarse.grd"                   │
│        bas_file = "GRID/MM_coarse.bas"                   │
│     c) Simulation rows (one per .str file):              │
│        For each phase → for each basename:               │
│          Check {project_path}/{basename}.str exists       │
│          Insert Simulation(name=basename,                │
│            description="{phase}: {desc}",                │
│            str_file="{basename}.str")                    │
│                                                          │
│  5. SUCCESS                                              │
│     ui.notification_show("...created successfully!")     │
│     ui.modal_remove()                                    │
│     _refresh_projects() — updates project list           │
│                                                          │
│  6. ON ERROR                                             │
│     If DB fails, shutil.rmtree(project_path)             │
│     ui.notification_show(error, type="error")            │
└──────────────────────────────────────────────────────────┘
```

### 3.4 Files Copied

The `shutil.copytree()` copies the entire `testcases/examples/mar_menor/` directory:

```
mar_menor_tutorial/
├── GRID/
│   ├── MM_coarse.grd              # Main grid (triangular FEM mesh)
│   ├── MM_coarse_smooth.grd       # Smoothed bathymetry variant
│   ├── MM_coarse.bas              # Pre-compiled basin file
│   ├── MM_coarse.{2,4}.node.grd   # Pre-partitioned for MPI
│   └── partition.{2,4,8}.txt      # Partition metadata
├── INPUT/
│   ├── wind09.txt, wind_scir.txt  # Wind forcing
│   ├── T_MarMenor.txt             # Temperature profile
│   ├── S_MarMenor.txt             # Salinity profile
│   ├── level_Mar_Menor.dat        # Boundary water level
│   ├── river.txt                  # River discharge
│   ├── rain09.txt                 # Precipitation
│   ├── qflux09.txt                # Heat flux
│   ├── gotmturb.nml               # GOTM turbulence config
│   └── colormap.dat               # Plotting colors
├── mm_hyd_00.str ... mm_hyd_43.str  # 14 tutorial .str files
├── mm_hyd_*.sh                      # Run scripts
├── apn_*.str                        # Annotation/particle cases
└── Makefile                         # Build/run targets
```

### 3.5 Database Records Created

**Project table:**
```
id: auto-increment
name: "mar_menor_tutorial"
description: "Mar Menor tutorial — 6-phase guided introduction to SHYFEM"
work_dir: "/home/razinka/.shyfem-ui/projects/mar_menor_tutorial"
created_at: now()
updated_at: now()
```

**Grid table:**
```
id: auto-increment
project_id: <project.id>
name: "MM_coarse"
description: "Mar Menor coarse grid"
grd_file: "GRID/MM_coarse.grd"
bas_file: "GRID/MM_coarse.bas"
```

**Simulation table (up to 14 rows):**
```
For each .str file found on disk:
  id: auto-increment
  project_id: <project.id>
  grid_id: <grid.id>
  name: e.g. "mm_hyd_00"
  description: "1. Basic Hydrodynamics: Minimal setup, output, wind forcing, friction"
  str_file: "mm_hyd_00.str"
```

### 3.6 Post-Creation User Workflow

After the tutorial project is created, the user should:

1. **Grid Prep tab** — Load `GRID/MM_coarse.grd`, run `shypre` to create/verify `.bas`
2. **Partitioning tab** — (Optional) Partition for MPI with `shyparts`
3. **Simulation tab** — Load any `mm_hyd_*.str` file, review/edit parameters
4. **Run tab** — Submit job with `shyfem`, monitor progress and logs
5. **Post-Process tab** — Run `shyelab` on `.shy` output files
6. **Visualize tab** — Plot time series, contour maps, transects

---

## 4. Database Schema

### 4.1 Tables

```sql
-- projects
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR NOT NULL,
    description TEXT,
    work_dir    VARCHAR NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- grids
CREATE TABLE grids (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    name        VARCHAR NOT NULL,
    description TEXT,
    grd_file    VARCHAR,     -- relative path within project work_dir
    bas_file    VARCHAR,     -- relative path within project work_dir
    node_count  INTEGER,
    elem_count  INTEGER,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- simulations
CREATE TABLE simulations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    grid_id     INTEGER REFERENCES grids(id),
    name        VARCHAR NOT NULL,
    description TEXT,
    str_file    VARCHAR,     -- relative path within project work_dir
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- jobs
CREATE TABLE jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      VARCHAR NOT NULL UNIQUE,    -- UUID
    simulation_id INTEGER REFERENCES simulations(id),
    name        VARCHAR NOT NULL,
    tool_name   VARCHAR NOT NULL,
    status      VARCHAR NOT NULL,           -- PENDING/QUEUED/RUNNING/COMPLETED/FAILED
    args        TEXT,                        -- JSON
    working_dir VARCHAR,
    started_at  DATETIME,
    completed_at DATETIME,
    error       TEXT,
    metadata    TEXT                         -- JSON
);
```

### 4.2 Relationships

```
Project 1 ──< N Grid
Project 1 ──< N Simulation
Grid    1 ──< N Simulation
Simulation 1 ──< N Job
```

---

## 5. Service Interfaces

### 5.1 Config (config.py)

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `shyfem_dir` | Path | auto-detect | SHYFEM installation root |
| `work_dir` | Path | `~/.shyfem-ui/projects` | Project storage |
| `testcases_dir` | Path | (computed) | `shyfem_dir / "testcases" / "examples"` |
| `deployment_mode` | str | `local` | `local` or `server` |
| `database_url` | str | `sqlite:///./shyfem_ui.db` | SQLAlchemy URL |
| `max_workers` | int | 4 | Concurrent job limit |
| `mpi_enabled` | bool | True | MPI support |
| `mpi_default_np` | int | 4 | Default MPI processes |
| `auth_enabled` | bool | False | HTTP Basic Auth |

Key methods:
- `validate_path(path)` — Symlink resolution, null-byte rejection, allowed directories
- `validate_save_path(path)` — Ensures path within `work_dir`
- `ensure_work_dir()` — Creates `work_dir` if missing

### 5.2 ShyfemWrapper (shyfem_wrapper.py)

```python
class ShyfemWrapper:
    def __init__(self, shyfem_dir: Path)
    def check_available(self, tool: str) -> bool
    def build_command(self, tool: str, args: list, mpi: bool, np: int) -> list[str]
    async def run(self, spec: JobSpec, progress_cb) -> int  # return code
```

Tools: `shypre`, `shybas`, `shyparts`, `shyfem`, `shyelab`, `shyplot`

### 5.3 JobQueue (job_queue.py, job_local.py)

```python
class JobQueue(ABC):
    async def submit(self, spec: JobSpec) -> str       # returns job_id
    async def cancel(self, job_id: str) -> bool
    async def get_status(self, job_id: str) -> JobInfo
    async def list_jobs(self, limit: int) -> list[JobInfo]
    async def cleanup(self, max_age_hours: int) -> int
```

Job lifecycle: `PENDING → QUEUED → RUNNING → COMPLETED | FAILED`

### 5.4 StrParser (parser_str.py)

```python
class StrParser:
    @staticmethod
    def parse(text: str) -> StrFile
    @staticmethod
    def generate(str_file: StrFile) -> str
    @staticmethod
    def get_param(str_file: StrFile, section: str, key: str) -> Optional[str]
    @staticmethod
    def set_param(str_file: StrFile, section: str, key: str, value: str)
```

---

## 6. Reactive Architecture (Simulation Page)

### 6.1 One-Way Data Flow (Post-Fix)

```
                  ┌─────────────────────────────────┐
                  │    STR Editor Component          │
                  │  (str_editor.py)                 │
                  │                                  │
  User edits  ──►│  editor_content (textarea)       │
                  │       │                          │
                  │       ▼                          │
                  │  parsed_file (reactive.calc)     │──► editor_state["parsed_file"]
                  └─────────────────────────────────┘
                                                            │
                                                            ▼
                  ┌─────────────────────────────────┐
                  │    Simulation Page               │
                  │  (simulation.py)                 │
                  │                                  │
                  │  _sync_editor_to_simulation()    │ (one-way reactive effect)
                  │       │                          │
                  │       ▼                          │
                  │  parsed_str (reactive.value)     │ ◄── also set by:
                  │       │                          │     • _new_file()
                  │       ▼                          │     • _apply_quick_settings()
                  │  UI renders from parsed_str      │     • _load_template()
                  └─────────────────────────────────┘     • _load_file()

  When handlers modify parsed_str directly, they ALSO call:
    editor_state["set_content"](new_text)
  to update the editor without a reverse reactive effect.
```

### 6.2 Why Bidirectional Sync Failed

The original code had two reactive effects:
1. `_sync_editor_to_simulation`: editor → parsed_str
2. `_sync_simulation_to_editor`: parsed_str → editor

This created an infinite loop:
```
editor text changed → effect 1 fires → parsed_str.set() →
effect 2 fires → editor text changed → effect 1 fires → ...
```

A `reactive.value(False)` guard failed because effects are scheduled asynchronously.
A plain Python `bool` flag also failed because by the time effect 2 ran, effect 1 had already reset the flag.

**Solution:** Remove effect 2 entirely. Handlers that modify `parsed_str` directly also call `editor_state["set_content"]()` imperatively.

---

## 7. Modal Patterns

### 7.1 Correct Pattern (Used in home.py)

```python
@reactive.effect
@reactive.event(input.some_btn)
def _show_modal():
    m = ui.modal(
        ui.input_text("field", "Label"),
        title="Title",
        easy_close=True,
        footer=ui.div(
            ui.input_action_button("confirm_btn", "OK", class_="btn-primary"),
            ui.input_action_button("cancel_btn", "Cancel", class_="btn-secondary ms-2"),
        ),
    )
    ui.modal_show(m)
```

Key rules:
- Modal created **dynamically** inside event handler (not static in UI tree)
- `ui.modal_show(m)` takes a **Tag object**, not a string ID
- `ui.modal_remove()` takes **no arguments** (optional `session` kwarg only)
- Modal footer buttons get fresh IDs each time (Shiny re-registers handlers)

### 7.2 Anti-Patterns Fixed in simulation.py

| Anti-pattern | Fix |
|---|---|
| Static `ui.modal()` in UI tree | Removed; create dynamically in handler |
| `ui.modal_show("save_as_modal")` | Changed to `ui.modal_show(m)` with Tag |
| `ui.modal_remove("save_as_modal")` | Changed to `ui.modal_remove()` |

---

## 8. Test Coverage Analysis

### 8.1 Test Files & Counts

| File | Tests | Type | Scope |
|------|-------|------|-------|
| `test_playwright_dashboard.py` | 30 | E2E | Dashboard elements, buttons, modals |
| `test_playwright_navigation.py` | 15 | E2E | Tab switching, URL routing |
| `test_playwright_pages.py` | 30 | E2E | Page rendering, element presence |
| `test_playwright_interactions.py` | 19 | E2E | Form fills, modal interactions |
| `test_parser_str.py` | ~30 | Unit | StrParser parse/generate round-trip |
| `test_parser_grd.py` | ~20 | Unit | GrdParser node/element parsing |
| `test_job_local.py` | ~15 | Unit | Job submit/cancel/list/cleanup |
| `test_workflow.py` | ~10 | Unit | Workflow step execution |
| `test_report.py` | ~10 | Unit | HTML report generation |
| `test_wrapper.py` | ~10 | Unit | ShyfemWrapper commands |
| `test_config.py` | ~10 | Unit | Config validation |
| `test_components.py` | ~5 | Unit | Component rendering |
| `test_pages_helpers.py` | ~8 | Unit | Helper functions |
| **Total** | **~212** | | |

### 8.2 Coverage Gaps

| Area | Gap | Impact |
|------|-----|--------|
| Tutorial workflow | Only checks button visibility, NOT click-through | High |
| Simulation page buttons | No E2E click tests for load/new/save/validate | High |
| Run page job submission | No E2E test for submit → progress → complete | High |
| Post-process page | No E2E click tests | Medium |
| Visualize page | No plot rendering tests | Medium |
| Ensemble page | No sweep submission tests | Medium |
| Compare page | No comparison workflow tests | Low |
| Dynamic button handlers | `remove_var_{i}`, `remove_bound_{bid}` untested (and buggy) | Medium |
| `open_project_btn` | No handler exists, no test catches it | Medium |
| `import_grid_btn` | No handler exists, no test catches it | Medium |

### 8.3 Recommended New Tests

```python
# 1. Tutorial end-to-end workflow
def test_tutorial_creates_project(page):
    """Click tutorial button → fill name → confirm → verify project in list."""

# 2. Simulation page load/save cycle
def test_simulation_load_save(page):
    """Load .str file → edit → save as → verify file on disk."""

# 3. Job submission and monitoring
def test_run_job_lifecycle(page):
    """Submit shypre job → wait for completion → check output."""

# 4. Handler coverage for missing handlers
def test_open_project_btn_exists(page):
    """Verify open_project_btn has a handler (currently fails)."""
```

---

## 9. Configuration Flow (Deployed on Shiny Server)

```
Browser request
    │
    ▼
nginx (laguna.ku.lt)
    │   reverse proxy: /shyfem-ui/ → http://localhost:3838/shyfem-ui/
    ▼
Shiny Server v1.5.22 (port 3838)
    │   runs: /opt/shiny-server/python/SockJSAdapter.py
    │   imports: /srv/shiny-server/shyfem-ui/app.py
    │   which calls: from shyfem_ui.app import create_app; app = create_app()
    ▼
SHYFEM UI (Shiny for Python 1.5.1)
    │   reads: /srv/shiny-server/shyfem-ui/.env
    │     SHYFEM_UI_DEPLOYMENT_MODE=server
    │     SHYFEM_UI_SHYFEM_DIR=/home/razinka/shyfem
    │     SHYFEM_UI_WORK_DIR=/home/razinka/.shyfem-ui/projects
    ▼
SQLite DB: /home/razinka/.shyfem-ui/projects/shyfem_ui.db
```

The deployed app at `/srv/shiny-server/shyfem-ui/` is a **symlink** to `/home/razinka/shyfem/shyfem-ui/`, so code changes are automatically reflected after Shiny Server restart.

---

## 10. Bugs Fixed in This Session

| Bug | File | Root Cause | Fix |
|-----|------|-----------|-----|
| 100% CPU infinite reactive loop | `simulation.py` | Bidirectional reactive sync between editor and parsed_str | Removed `_sync_simulation_to_editor` effect; handlers update both parsed_str and editor directly |
| Tutorial button not working | `simulation.py` | CPU loop starved event loop, preventing Shiny protocol messages | Same fix (loop elimination) |
| `label=None` browser warnings | `str_editor.py`, `boundary_editor.py`, `grid_map.py` | `label=None` generates broken `<label for=...>` HTML | Changed to `label=""` (12 occurrences) |
| `ui.modal_show("save_as_modal")` | `simulation.py` | API misuse: expects Tag, not string | Create modal dynamically in handler |
| `ui.modal_remove("save_as_modal")` | `simulation.py` | API misuse: string passed as session param | Changed to `ui.modal_remove()` |
| Static modal in UI tree | `simulation.py` | Shiny modals must be created dynamically | Removed static modal from `simulation_ui()` |

---

## 11. Recommendations

### Immediate Priority
1. **Add handlers for `open_project_btn` and `import_grid_btn`** — These are visible Quick Start buttons with no functionality
2. **Add handlers for `remove_var_{i}` and `remove_bound_{bid}`** — Dynamic remove buttons that do nothing when clicked
3. **Add `project_{id}` click handlers** — Project links in the table are not interactive

### Testing Priority
4. **Add tutorial workflow E2E test** — Verify the full tutorial button → modal → project creation flow
5. **Add simulation page click tests** — Load, New, Save As, Validate buttons
6. **Add job lifecycle E2E test** — Submit → monitor → complete

### Architecture
7. **Consider extracting button handler registration into a registry pattern** — Would make it easier to audit for missing handlers
8. **Add a "handler lint" test** — Grep for `input_action_button` IDs and verify each has a corresponding `@reactive.event` handler
