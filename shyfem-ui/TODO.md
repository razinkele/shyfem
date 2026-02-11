# SHYFEM-UI Improvement Plan - Detailed TODOs

**Created:** 2026-02-11
**Target:** Shared server deployment
**Priorities:** Interactive map/grid viz, STR editor, Job management, Result analysis

---

## Phase 1: Critical Bug Fixes & Dependency Updates

- [ ] **1.1** Update `requirements.txt` and `pyproject.toml` versions:
  - `shiny>=0.6.0` -> `shiny>=1.2.0`
  - `shinyswatch>=0.4.0` -> `shinyswatch>=0.7.0`
  - `plotly>=5.15` -> `plotly>=5.24`
  - `xarray>=2023.0` -> `xarray>=2024.6`
  - Add: `ipyleaflet>=0.18`, `shinywidgets>=0.3`, `scipy>=1.12`
- [ ] **1.2** [CRITICAL] Fix dynamic button handlers in `pages/run.py` (~line 250-259)
  - Buttons with `f"view_job_{job.id}"` have no registered handlers
  - Replace with single handler + `reactive.Value` for selected job ID
- [ ] **1.3** [CRITICAL] Fix editor state lost in `pages/simulation.py` (~line 142-145)
  - `str_editor_server()` return value assigned but never used
  - Wire returned reactive values to save/template logic
- [ ] **1.4** [CRITICAL] Implement shyelab info parser in `pages/postprocess.py` (~line 383-403)
  - `_parse_shyelab_info()` is a stub (only basic key:value split)
  - Implement proper parser matching shyelab actual output format
- [ ] **1.5** [HIGH] Fix progress callback sync in `pages/run.py` (~line 401-409)
  - `on_progress` modifies job object without reactivity
  - Use `reactive.Value` wrapper + `reactive.invalidate_later(2)` polling
- [ ] **1.6** Fix datetime quoting in `pages/simulation.py` (~line 260-261)
- [ ] **1.7** Fix MPI parameter inconsistency in `services/job_local.py` (~line 146)

---

## Phase 2: Code Quality & Restructuring

- [ ] **2.1** Remove dead code in `components/file_browser.py` (lines 84-125: unused functions)
- [ ] **2.2** Fix type hints: replace `Optional[callable]` with `Optional[Callable[...]]` in `str_editor.py`, `plot_widget.py`
- [ ] **2.3** Add temp file cleanup in `services/job_local.py` (stdout/stderr on job completion)
- [ ] **2.4** Improve STR parser round-trip fidelity in `services/parser_str.py` (preserve comments, support multiline values)
- [ ] **2.5** Improve GRD parser robustness in `services/parser_grd.py` (mixed tri/quad, malformed files)
- [ ] **2.6** Add database indexes in `models/project.py` (Job.status, Job.created_at, Job.simulation_id)
- [ ] **2.7** Harden security for shared server: rate limiting, HTML sanitization in log_viewer, path validation

---

## Phase 3: Interactive Map & Grid Visualization

- [ ] **3.1** Create `components/grid_map.py` - ipyleaflet-based interactive grid map
  - Zoomable/pannable mesh, depth coloring, clickable nodes, boundary highlighting
  - Partition overlay coloring, layer controls
- [ ] **3.2** Integrate grid map into `pages/grid_prep.py` (replace static matplotlib)
  - Side panel with grid stats, click-to-inspect nodes/elements
- [ ] **3.3** Integrate grid map into `pages/partitioning.py`
  - Color elements by partition, load balance chart alongside map
- [ ] **3.4** Add Plotly result visualization in `pages/visualize.py` (major rewrite)
  - Contour plots for scalars, quiver/streamline for velocity
  - Time slider animation, side-by-side comparison, configurable colorbar
- [ ] **3.5** Add geographic coordinate support in `services/parser_grd.py`
  - Detect Cartesian vs geographic, auto-project UTM to lat/lon

---

## Phase 4: Enhanced STR File Editor

- [ ] **4.1** Rich parameter editor in `components/str_editor.py`
  - Split view: raw text (left) + structured form (right)
  - Documentation tooltips, auto-complete, type validation, color-coded sections
- [ ] **4.2** Expand COMMON_PARAMS in `services/parser_str.py`
  - All params from manual: name, type, default, units, description, valid range
- [ ] **4.3** Template library expansion in `pages/simulation.py`
  - Templates: Basic 2D/3D, Wind-driven, Tidal, Baroclinic, Lagrangian
  - Preview before applying, "diff from template" view
- [ ] **4.4** Create `components/boundary_editor.py`
  - Visual boundary node selection on map, configure type/time series
  - Auto-generate $bound sections, import from CSV
- [ ] **4.5** Validation engine in `services/parser_str.py`
  - Required sections, time param checks, grid file existence, unusual param warnings

---

## Phase 5: Job Management & Monitoring

- [ ] **5.1** Rewrite `components/log_viewer.py` for real-time streaming
  - `reactive.invalidate_later(2)` auto-polling, tail last 500 lines
  - Auto-scroll toggle, search/filter, separate stdout/stderr tabs, download button
- [ ] **5.2** Live progress dashboard in `pages/run.py`
  - Real-time progress bars (% complete, timestep, ETA)
  - Multi-job sortable table, job dependency chains
- [ ] **5.3** Create `services/workflow.py` for job chaining
  - Multi-step workflows: Grid Prep -> Partition -> Simulate -> Post-process
  - Auto-chain on completion, workflow templates, pipeline diagram
- [ ] **5.4** Create `pages/compare.py` for job comparison
  - Compare 2+ simulations: runtime, stats, parameter diff, overlaid time series
- [ ] **5.5** Complete `services/job_celery.py` implementation
  - All JobQueue methods, job persistence, Redis health check, worker scaling
- [ ] **5.6** Create `pages/ensemble.py` for parameter sweeps
  - Vary parameters across runs, batch submit, aggregate results (mean/std/envelope)

---

## Phase 6: Result Analysis & Post-Processing

- [ ] **6.1** Rewrite `pages/postprocess.py` with full shyelab integration
  - All shyelab options GUI, output preview, batch post-processing
- [ ] **6.2** Create `components/timeseries.py`
  - Interactive Plotly time series, multi-variable axes, statistics panel
  - Export CSV/Excel, observation data overlay for comparison
- [ ] **6.3** Complete NetCDF visualization in `pages/visualize.py`
  - Replace stub `_plot_netcdf()`: variable browser, dimension slicing
  - Spatial plots, vertical profiles, transect plots
- [ ] **6.4** Create `services/report.py` for report generation
  - HTML/PDF summary: parameters, grid info, runtime stats, result plots
  - Jinja2 templates, auto-generate on completion (optional)

---

## Phase 7: Testing & Documentation

- [ ] **7.1** Expand test suite in `tests/`
  - `test_parser_str.py`: error cases, complex .str files, round-trip
  - `test_parser_grd.py`: malformed files, mixed elements
  - `test_wrapper.py`: MPI, timeout, error cases
  - New: `test_job_local.py`, `test_pages.py` (ShinyTestDriver), `test_grid_map.py`
  - Target: >80% coverage on services/, >60% on pages/
- [ ] **7.2** Update `README.md`: install guide, config reference, screenshots, Docker guide
- [ ] **7.3** Add docstrings and type hints to all public functions

---

## Implementation Order

```
Phase 1 (Critical fixes)     ~2 days   - Must do first
Phase 2 (Code quality)       ~1 day    - Before new features
Phase 4 (STR editor)         ~2 days   - Independent
Phase 3 (Map visualization)  ~3 days   - Needs updated deps
Phase 5 (Job management)     ~3 days   - Needs Phase 1 fixes
Phase 6 (Result analysis)    ~3 days   - Needs Phase 3 viz
Phase 7 (Testing & docs)     ~2 days   - After all features
```

## Verification (after each phase)
1. `cd shyfem-ui && pip install -e .`
2. `python -m shyfem_ui.app` - app launches
3. Navigate all pages in browser
4. Submit test job (shypre + shyfem on mar_menor)
5. `pytest tests/ -v` - all tests pass
6. Final: full workflow end-to-end + multi-user test (two browser sessions)
