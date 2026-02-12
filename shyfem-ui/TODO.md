# SHYFEM-UI Improvement Plan - Detailed TODOs

**Created:** 2026-02-11
**Target:** Shared server deployment
**Priorities:** Interactive map/grid viz, STR editor, Job management, Result analysis

---

## Phase 1: Critical Bug Fixes & Dependency Updates

- [x] **1.1** Update `requirements.txt` and `pyproject.toml` versions:
  - `shiny>=0.6.0` -> `shiny>=1.2.0`
  - `shinyswatch>=0.4.0` -> `shinyswatch>=0.7.0`
  - `plotly>=5.15` -> `plotly>=5.24`
  - `xarray>=2023.0` -> `xarray>=2024.6`
  - Add: `ipyleaflet>=0.18`, `shinywidgets>=0.3`, `scipy>=1.12`
- [x] **1.2** [CRITICAL] Fix dynamic button handlers in `pages/run.py` (~line 250-259)
  - Replaced per-job buttons with select dropdown + static action buttons
  - Added `view_active_job_btn` and `cancel_active_job_btn` with proper handlers
- [x] **1.3** [CRITICAL] Fix editor state lost in `pages/simulation.py` (~line 142-145)
  - Wired `str_editor_server()` return values with bidirectional sync effects
  - Added `_syncing` guard to prevent infinite reactive loops
- [x] **1.4** [CRITICAL] Implement shyelab info parser in `pages/postprocess.py` (~line 383-403)
  - Implemented full parser matching shy_info output from io_shy.f90
  - Handles label:value pairs, basin info, variable descriptions, layer depths
- [x] **1.5** [HIGH] Fix progress callback sync in `pages/run.py` (~line 401-409)
  - Replaced direct mutation with buffered `_latest_progress` dict
  - Added `reactive.invalidate_later(2)` auto-polling for active jobs
- [x] **1.6** Fix datetime quoting in `pages/simulation.py` (~line 260-261)
  - Added `quote_value()` helper that strips existing quotes before wrapping
- [x] **1.7** Fix MPI parameter inconsistency in `services/job_local.py` (~line 146)
  - Use `spec.mpi_np` directly instead of reading from metadata

---

## Phase 2: Code Quality & Restructuring

- [x] **2.1** Remove dead code in `components/file_browser.py`
  - Removed `create_directory_browser`, `validate_path`, `get_file_icon` (unused)
  - Removed unused `Path` import
- [x] **2.2** Fix type hints: `Optional[callable]` -> `Optional[Callable[...]]`
  - `str_editor.py`: `Optional[Callable[[Path, str], None]]`
  - `plot_widget.py`: `Optional[Callable[[plt.Figure], None]]`
- [x] **2.3** Add temp file cleanup in `services/job_local.py`
  - Added `TEMP_FILE_RETENTION_SECS` (1 hour) and `_schedule_temp_cleanup()`
  - Temp files auto-removed via `loop.call_later()` after job completion
- [x] **2.4** Improve STR parser round-trip fidelity in `services/parser_str.py`
  - Added `_structure` list to `StrFile` for inter-section content preservation
  - Added `_modified_params` tracking to `StrSection`
  - `generate()` now overlays param changes on raw_lines, preserves comments/blanks
- [x] **2.5** Improve GRD parser robustness in `services/parser_grd.py`
  - Per-field try/except with line-number warnings in `parse_warnings`
  - Validates min node counts (3 for elements, 2 for lines)
  - Graceful handling of malformed depth, node id fields
- [x] **2.6** Add database indexes in `models/project.py`
  - Added `ix_jobs_status`, `ix_jobs_created_at`, `ix_jobs_simulation_id`
- [x] **2.7** Harden security for shared server
  - Path validation: null byte rejection, strict symlink resolution
  - Log viewer: line truncation (4096 chars), `quote=True` in `html.escape`, fixed `>>>` detection post-escape
  - Added `rate_limit_rpm` config field (120 req/min default)

---

## Phase 3: Interactive Map & Grid Visualization

- [x] **3.1** Create `components/grid_map.py` - Plotly-based interactive grid map
  - Zoomable/pannable mesh via Plotly Scattergl, depth coloring, hover-to-inspect nodes
  - Boundary highlighting with color-coded line types
  - Partition overlay coloring with 20-color palette
  - `build_mesh_figure()` reusable function for all view modes
  - Registered in `components/__init__.py`
- [x] **3.2** Integrate grid map into `pages/grid_prep.py` (alongside static matplotlib)
  - New "Interactive Map" tab as primary view, static plot kept as "Static Plot" tab
  - Added "Node Inspector" tab with first-20 nodes/elements tables
  - `grid_map_server` wired to `current_grd` reactive
- [x] **3.3** Integrate grid map into `pages/partitioning.py`
  - Color elements by partition using `partition_map_data` reactive
  - Added Plotly bar chart for load balance with avg line and imbalance %
  - Grid file loader for visualization alongside partitioning
  - `_analyze_partitions` builds element-to-partition mapping from .par files
- [x] **3.4** Rewrite `pages/visualize.py` with Plotly (full rewrite)
  - Grid: reuses `build_mesh_figure()` from grid_map component
  - Time series: Plotly Scattergl for line/scatter/area, range slider for navigation
  - NetCDF: contour, heatmap, 3D surface plots with variable selector + dimension sliders
  - Side-by-side comparison tab for grids and overlaid time series
  - Removed matplotlib dependency entirely
- [x] **3.5** Add geographic coordinate support in `services/parser_grd.py`
  - `CoordinateSystem` class: geographic, cartesian, UTM detection
  - `detect_coordinate_system()` heuristic on GrdFile bounds
  - `to_geographic()` UTM-to-lat/lon in-place conversion (~100m accuracy)
  - `_utm_to_latlon()` standalone WGS84 converter (no pyproj dependency)
  - `get_statistics()` now includes coordinate_system field

---

## Phase 4: Enhanced STR File Editor

- [x] **4.1** Rich parameter editor in `components/str_editor.py`
  - Split view: raw text (left) + structured form (right) with Raw/Split/Form toggle
  - Color-coded section badges, tooltips with default/range/units from param database
  - Enumerated params get dropdown selects, others get text inputs
  - "Apply Form Changes" button syncs form edits back to raw text
- [x] **4.2** Expand COMMON_PARAMS in `services/parser_str.py`
  - 100+ parameters across $para, $name, $bound with 5-tuple metadata:
    (description, type, default, units, options/range)
  - Categories: timing, output, physics, advection, Coriolis, depth, friction,
    wind, heat flux, 3D layers, vertical/horizontal mixing, T/S, tracers, modules
  - `get_param_info()` helper for flat lookup across sections
  - Updated param_reference table with Default and Options/Range columns
- [x] **4.3** Template library expansion in `pages/simulation.py`
  - Added Baroclinic (T/S with 3D layers, GOTM turbulence, Smagorinsky)
  - Added Lagrangian (particle tracking with water age tracer, TVD advection)
  - Template preview: shows sections, param count, first 300 chars of content
  - "Apply Template" button separated from select (no accidental overwrite)
- [x] **4.4** Create `components/boundary_editor.py`
  - Add/remove boundary cards with node list, type select, time series file,
    scale factor, interpolation method
  - CSV import (nodes, type, file, zfact, intpol per line)
  - "Generate $bound" produces ready-to-paste section text
  - Integrated as "Boundaries" tab in simulation page
  - Registered in components/__init__.py
- [x] **4.5** Validation engine in `components/str_editor.py`
  - Required sections ($para mandatory, $title warning)
  - Time params: itanf/itend/idt presence, itanf < itend, idt > 0
  - Depth sanity: hzmin < hzoff warning
  - Value range checks from COMMON_PARAMS ([min,max], >0, >=0)
  - Unknown parameter warnings in $para
  - Optional file existence checks for $name entries
  - Boundary section ibtyp presence check

---

## Phase 5: Job Management & Monitoring

- [x] **5.1** Rewrite `components/log_viewer.py` for real-time streaming
  - `reactive.invalidate_later(2)` auto-polling, tail last 500 lines
  - Auto-scroll toggle, search/filter input, separate stdout/stderr/all tabs
  - Download button via base64 data URI, log stats badges
  - XSS-safe: html.escape with quote=True, line truncation at 4096 chars
- [x] **5.2** Live progress dashboard in `pages/run.py`
  - Real-time progress bars (% complete, ETA estimation from elapsed/progress)
  - Summary stat cards (Running/Queued/Completed/Failed)
  - Job Timeline tab with Plotly horizontal bar chart (Gantt-style, last 20 jobs)
  - Job dependency support via metadata["depends_on"]
  - Auto-refresh via `reactive.invalidate_later(2)` for active jobs
- [x] **5.3** Create `services/workflow.py` for job chaining
  - `WorkflowEngine` with sequential step execution and auto-chaining
  - `WorkflowStep`, `WorkflowInstance`, `WorkflowStatus` dataclasses
  - 3 templates: full_simulation (shypre→shyparts→shyfem→shyelab),
    grid_only (shypre→shybas), simulation_postprocess (shyfem→shyelab)
  - Template argument resolution: `{param}`, `{step.output_files[N]}`, `{step.output_dir}`
  - `continue_on_failure` per-step, cancel propagation
- [x] **5.4** Create `pages/compare.py` for job comparison
  - Runtime Stats: side-by-side metric table with diff highlighting
  - Parameter Diff: STR file comparison showing differing params by section
  - Time Series: overlaid Plotly plot (solid vs dashed) with range slider
  - Summary: speed ratio, diff count
- [x] **5.5** Complete `services/job_celery.py` implementation
  - Full CeleryJobQueue: submit, cancel, get_status, list_jobs, get_output, cleanup
  - Redis persistence with hash + sorted set for time-ordered listing
  - `health_check()`: Redis ping, worker ping, active/scheduled/reserved counts
  - `worker_info()`: per-worker stats (name, active tasks, processed, concurrency, pool)
- [x] **5.6** Create `pages/ensemble.py` for parameter sweeps
  - Parameter variation editor with dynamic add/remove rows
  - Grid (cartesian product) and Zip (parallel) sweep modes
  - Quick presets: friction, timestep, viscosity sweeps
  - Preview table showing all parameter combinations
  - Batch submit with per-run STR file generation via StrParser
  - Progress tracking with auto-refresh, per-run status table
  - Results: overlaid time series with min/max envelope and mean line
  - Duration comparison bar chart fallback when no time series available
  - Summary: runtime statistics (avg/min/max), failed run details
  - Registered in `pages/__init__.py`

---

## Phase 6: Result Analysis & Post-Processing

- [x] **6.1** Rewrite `pages/postprocess.py` with full shyelab integration
  - All 10 shyelab operation modes: info, extract_ts, extract_nc, split_vars,
    spatial_avg, temporal_avg, minmax, residual, frequency, custom
  - 3 presets: quick_extract, full_analysis, netcdf_split
  - Variable/layer selection from `shyelab -info` scan results
  - Time range filtering, batch processing with progress table
  - Output file browser with size/type badges
  - `_parse_shyelab_info()` parser for Fortran output format
- [x] **6.2** Create `components/timeseries.py`
  - Multi-variable Plotly time series with selectable columns
  - Dual Y-axis support via `make_subplots(specs=[[{"secondary_y": True}]])`
  - Plot styles: line, scatter, line+markers, area
  - Statistics panel: min/max/mean/std/range/count per variable
  - Observation data overlay (CSV/whitespace file loader, diamond markers)
  - CSV export via base64 data URI + `session.send_custom_message`
  - `compute_statistics()` utility with percentiles (p25, p50, p75)
  - Registered in `components/__init__.py`
- [x] **6.3** Complete NetCDF visualization in `pages/visualize.py`
  - Vertical profile plots (`_build_vertical_profile`) with auto-detection
    of depth dimension (level/depth/z/sigma/layer/lev), reversed Y-axis
  - Transect extraction (`_build_transect`) along spatial dimensions
  - Variable statistics tables for both NetCDF and time series data
  - NetCDF difference maps (`_compare_netcdf`) with 3-panel layout
    (primary, comparison, difference using RdBu_r colormap)
  - Integrated reusable `timeseries_server` component
  - New plot types: "profile" and "transect" for NetCDF data
- [x] **6.4** Create `services/report.py` for report generation
  - `ReportBuilder` class with fluent API for composing report sections
  - Self-contained HTML reports with inline CSS and embedded Plotly.js
  - `add_parameters()`: simulation params from StrFile
  - `add_grid_info()`: grid stats from GrdParser.get_statistics()
  - `add_job_info()`: runtime stats with status badges and duration
  - `add_output_files()`: file inventory with type badges and sizes
  - `add_plotly_figure()`: embedded interactive Plotly charts
  - `add_statistics_table()`: variable statistics summary
  - `generate_job_report()`: convenience one-call report generator
  - `generate_comparison_report()`: multi-job comparison reports
  - Print-friendly CSS with `@media print` rules
  - Registered in `services/__init__.py`

---

## Phase 7: Testing & Documentation

- [x] **7.1** Expand test suite in `tests/`
  - `test_parser_str.py`: +19 tests — edge cases (missing $end, empty content,
    comments-only, duplicate sections, case-insensitive names, double-quoted strings,
    negative values, exclamation comments, file round-trip), _structure preservation,
    _modified_params tracking, generate overlay, format_value, COMMON_PARAMS database,
    get_param_info with section scoping
  - `test_parser_grd.py`: +12 tests — mixed triangle+quad grids, blank lines,
    large node IDs, multiple line types, file round-trip, depth statistics,
    CoordinateSystem defaults/geographic/UTM, detect_coordinate_system (geographic/
    UTM/cartesian/empty), _utm_to_latlon basic conversion, to_geographic already-
    geographic and UTM conversion
  - `test_wrapper.py`: +12 tests — multiple output extensions, shyelab outputs,
    empty directory, unknown tool, progress parsing variants, stderr capture,
    nonexistent tool error, duration measurement, OUTPUT_EXTENSIONS mapping,
    multi-tool availability
  - New `test_job_local.py`: 20 tests — submit, get_status, nonexistent status,
    job completion, output files, list_jobs (all/status/simulation_id/limit),
    cancel (running/nonexistent/completed), get_output (normal/nonexistent/tail),
    MPI metadata, progress callback, active_job_count, cleanup (old/recent),
    eviction under MAX_STORED_JOBS cap
  - New `test_workflow.py`: 24 tests — template existence/structure/step types/
    full_simulation steps, WorkflowEngine list_templates/create/invalid_template/
    get/nonexistent/list/completes/step_results/custom_name/cancel/cancel_nonexistent,
    WorkflowInstance is_active/progress/empty/current_step/out_of_range/duration/
    not_completed, _resolve_args (param/step_output_files/step_output_dir/mixed/
    no_substitution/unresolved)
  - New `test_report.py`: 28 tests — ReportBuilder render_empty/add_section/
    add_text/preformatted/add_parameters(with filter/empty)/add_grid_info/
    add_job_info(normal/MPI/failed)/add_output_files(with files/empty)/
    add_statistics_table(with data/empty)/table_of_contents/save/save_creates_dirs/
    html_escaping/multiple_sections, generate_job_report(basic/all data),
    generate_comparison_report(basic/empty), helpers (_esc, _format_duration
    seconds/minutes/hours, _format_size bytes/KB/MB)
  - New `test_config.py`: 28 tests — defaults (deployment_mode/host/port/
    max_workers/mpi/auth/theme/celery/rate_limit), properties (bin_dir/
    testcases_dir/get_executable/ensure_work_dir), path validation (within_work/
    within_shyfem/within_tmp/outside_allowed/null_bytes/must_exist/must_exist_ok),
    save path validation (within_work/outside/null_bytes), global config
    (get/set/caches), path resolver (string/tilde)
  - **Total: 201 tests, all passing** (up from 40)
- [x] **7.2** Update `README.md`: full feature list, complete config reference
    (17 env vars), workflow guide, architecture tree (all pages/components/
    services), test coverage summary, Celery worker guide, troubleshooting section
- [x] **7.3** Docstrings and type hints — all public functions across services/,
    components/, pages/ already have docstrings and type hints from Phases 1-6
    implementation. No additional work needed.

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
