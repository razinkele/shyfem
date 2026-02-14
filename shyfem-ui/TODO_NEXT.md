# SHYFEM-UI — Round 2 Improvement Plan

**Created:** 2026-02-14
**Baseline:** Phases 1–17 complete (404 collected, 387 passing, 17 pre-existing failures)
**Scope:** Security, test coverage, features, performance, multi-user, polish
**Design:** [docs/plans/2026-02-14-round2-improvements-design.md](docs/plans/2026-02-14-round2-improvements-design.md)

---

## Phase 18: Error Handling Audit

> 40+ silent `except Exception: pass` blocks across 8 files hide bugs and
> make debugging impossible. Replace with logged handlers + graceful fallbacks.

- [x] **18.1** Fix silent exceptions in `components/str_editor.py`
  - Line 146: `except Exception: pass` — add logger.warning, fall back to raw string
  - Line 171: `except Exception: continue` — log skipped parameter conversion

- [x] **18.2** Fix silent exceptions in `components/timeseries.py`
  - Lines 170, 276, 385: silent fallbacks to default columns — add logger.debug
  - Line 433: silent whitespace parse fallback — log and notify

- [x] **18.3** Fix silent exceptions in `pages/ensemble.py`
  - Line 565: `except Exception: pass` — log retry failure
  - Line 836: `except Exception: return []` — log and return empty with context

- [x] **18.4** Fix silent exceptions in `pages/postprocess.py`
  - Lines 378, 386, 776: `except Exception: pass` — add logger.warning

- [x] **18.5** Fix silent exceptions in `pages/run.py`
  - Lines 301, 565, 813: silent catches — add logger.exception

- [x] **18.6** Fix silent exceptions in `pages/compare.py`
  - Audit all exception handlers, add logging where missing

- [x] **18.7** Fix unlogged rollback in `db/base.py`
  - Line 112: `except Exception:` rollback — add `logger.exception("DB error")`

- [x] **18.8** Audit `services/job_celery.py` exception handlers
  - Lines 169, 179: asyncio.run() error handling — ensure exceptions propagate

---

## Phase 19: File Upload & Input Validation

> File uploads have no size limits. An attacker or careless user can upload
> a multi-GB file and exhaust server memory.

- [x] **19.1** Add `max_upload_size_mb` config option
  - Default: 500 MB. Add to Config class with `SHYFEM_UI_MAX_UPLOAD_SIZE_MB` env var.

- [x] **19.2** Add file size validation to file_browser component
  - `validate_upload()` checks `file_info["size"]` before callback. Shows notification if too large.
  - Wired into `file_browser_server()` with config-driven max size.

- [x] **19.3** Add filename extension validation
  - `validate_upload()` checks suffix against `accept` list (case-insensitive).
  - Applied via `file_browser_server(accept=[...])` parameter.

- [x] **19.4** ~~Content-Length ASGI middleware~~ — SKIPPED
  - Shiny uploads use WebSocket, not HTTP POST. Middleware would not intercept uploads.

---

## Phase 20: Proxy & CSRF Hardening

> Rate limiter uses raw client IP, which fails behind reverse proxies.
> No CSRF protection exists for state-changing operations.

- [x] **20.1** Add `trusted_proxies` config option
  - List of CIDR ranges (default: empty). When set, extract client IP from
    `X-Forwarded-For` header instead of ASGI `scope["client"]`.

- [x] **20.2** Update RateLimitMiddleware to use forwarded IP
  - `get_client_ip()` with rightmost-untrusted algorithm. 11 tests.
  - Fall back to raw client IP if header is missing or proxy untrusted.

- [x] **20.3** ~~CSRF token middleware~~ — SKIPPED
  - Shiny is WebSocket-first. Same-origin policy on WS handshake provides
    equivalent CSRF protection. No HTML forms exist to protect.

---

## Phase 21: Middleware & Infrastructure Tests

> Rate limiter, auth middleware, session cleanup, and Alembic migrations
> have zero unit tests. These are critical infrastructure.

- [ ] **21.1** Test RateLimitMiddleware
  - Test: requests under limit pass through (200)
  - Test: requests at limit return 429 with Retry-After header
  - Test: sliding window resets after 60 seconds
  - Test: WebSocket connections bypass rate limiting
  - Test: different clients have independent limits

- [ ] **21.2** Test BasicAuthMiddleware
  - Test: valid credentials return 200
  - Test: invalid credentials return 401 with WWW-Authenticate
  - Test: missing Authorization header returns 401
  - Test: WebSocket with bad auth returns close code 4001
  - Test: non-http/websocket scopes pass through

- [ ] **21.3** Test session cleanup callback
  - Mock job_queue.list_jobs and cancel, verify orphaned jobs cancelled
  - Test: exceptions in cleanup are logged, not raised

- [ ] **21.4** Test Alembic migrations
  - Test: upgrade from empty DB creates all tables
  - Test: downgrade removes all tables
  - Test: existing DB without alembic_version gets stamped

---

## Phase 22: Component Test Coverage

> 4 components have zero unit tests: job_status, file_browser, log_viewer,
> plot_widget. These contain testable pure functions.

- [ ] **22.1** Test `components/job_status.py`
  - `format_duration()` — None, 0s, 30s, 90s, 3600s, negative
  - `format_datetime()` — None, datetime objects, timezone handling
  - `get_status_badge()` — all JobStatus enum values return valid HTML
  - `job_list_table()` — empty list, single job, multiple jobs

- [ ] **22.2** Test `components/file_browser.py`
  - Path validation edge cases (empty, None, non-existent)
  - Extension filtering logic
  - File selection callback invocation

- [ ] **22.3** Test `components/log_viewer.py`
  - Content truncation for very long logs
  - Empty content rendering
  - Reactive value updates

- [ ] **22.4** Test `components/plot_widget.py`
  - `plot_mesh()` returns valid matplotlib Figure with expected axes
  - `plot_depth_contour()` with synthetic GrdFile
  - `plot_boundaries()` with known boundary data
  - `plot_element_quality()` produces figure with colorbar

---

## Phase 23: Page Logic Tests

> Compare, ensemble, and visualize pages contain complex pure logic buried
> inside reactive handlers. Extract and test independently.

- [ ] **23.1** Extract and test `pages/compare.py` logic
  - Parameter diff computation (two .str configs → diff dict)
  - Timeline alignment for overlaying two job timelines
  - Statistics comparison (runtime, memory, return codes)

- [ ] **23.2** Extract and test `pages/ensemble.py` logic
  - Sweep combination generation (grid mode vs zip mode)
  - Parameter substitution into .str template
  - Result aggregation (min/max envelope, mean, std)

- [ ] **23.3** Extract and test `pages/visualize.py` logic
  - `_load_timeseries()` — CSV/TSV parsing with header detection
  - `_plotly_netcdf()` — contour/heatmap/surface figure generation
  - `_build_vertical_profile()` and `_build_transect()` — NetCDF slicing

---

## Phase 24: Fix Pre-Existing Test Failures

> 17 tests in test_workflow.py (6) and test_wrapper.py (11) fail due to
> async event loop issues. These have been failing since the test suite
> was created.

- [ ] **24.1** Fix test_workflow.py async failures
  - Root cause: `asyncio.run()` inside tests that already have an event loop
  - Fix: use `pytest-asyncio` `@pytest.mark.asyncio` decorator consistently
  - 6 tests: stores_step_results, custom_name, cancel_workflow,
    cancel_nonexistent, list_workflows, workflow lifecycle

- [ ] **24.2** Fix test_wrapper.py async failures
  - Root cause: similar event loop conflict with `asyncio.run()`
  - Fix: refactor to use `await` directly in async test functions
  - 11 tests: run_command_success/failure/callback/args/stderr/
    nonexistent/duration

- [ ] **24.3** Add pytest markers for selective test runs
  - `@pytest.mark.slow` for tests > 5 seconds
  - `@pytest.mark.e2e` for Playwright tests (already in separate files)
  - Update pyproject.toml `[tool.pytest.ini_options]` with marker definitions
  - Target: 0 failures, 430+ passing

---

## Phase 25: Real-Time Log Streaming

> Log viewer polls at a fixed interval (default 5s). For long-running
> simulations, users want instant feedback as lines are written.

- [ ] **25.1** Create `LogBroadcaster` service
  - Watches a log file path with `asyncio` file polling (100ms interval)
  - Pushes new lines to registered callbacks via reactive invalidation
  - Auto-stops when file hasn't changed for 30 seconds

- [ ] **25.2** Integrate LogBroadcaster into Run page
  - Replace polling `@reactive.poll` with push-based LogBroadcaster
  - Fall back to polling if broadcaster fails (graceful degradation)
  - Show "Live" indicator when streaming is active

- [ ] **25.3** Add configurable streaming interval
  - `SHYFEM_UI_LOG_STREAM_INTERVAL_MS` (default: 100)
  - Throttle at the UI level to avoid flooding WebSocket with rapid updates

---

## Phase 26: Data Export

> Users cannot download plots, data, or reports from the UI. Everything
> is view-only.

- [ ] **26.1** Add plot export buttons to Visualize page
  - Client-side "Download PNG" and "Download SVG" buttons using
    `Plotly.downloadImage()` JavaScript call
  - Add to main_plot and profile_plot outputs

- [ ] **26.2** Add CSV export for time series data
  - "Download CSV" button that serializes the loaded DataFrame
  - Use `shiny.render.download` handler to serve the file

- [ ] **26.3** Add report download to Run page
  - "Download Report" button on completed jobs
  - Calls `generate_job_report()` and serves HTML via download handler

- [ ] **26.4** Add grid statistics JSON export
  - "Export Stats" button on Grid Prep page
  - Serializes `GrdParser.get_statistics()` output as formatted JSON

---

## Phase 27: NetCDF Variable Explorer

> NetCDF files can contain dozens of variables across multiple dimensions.
> Currently users must know variable names in advance.

- [ ] **27.1** Add variable list panel to Visualize page
  - When NetCDF is loaded, show table: variable name, dimensions, dtype,
    units (from attrs), min/max preview
  - Clickable rows auto-select the variable for plotting

- [ ] **27.2** Add dimension slicing controls
  - Time step slider (for time dimension)
  - Depth layer slider (for vertical dimension)
  - Bind to plot updates via reactive values

- [ ] **27.3** Add variable metadata display
  - Show `attrs` dict (long_name, units, valid_range) in sidebar panel
  - Display coordinate reference system if available

---

## Phase 28: Database Query Optimization

> Dashboard loads all projects with all grids and simulations, causing
> N+1 queries. Job listing is hardcoded to 100.

- [ ] **28.1** Add eager loading for Dashboard queries
  - Use `joinedload(Project.grids)` and `joinedload(Project.simulations)`
  - Reduces query count from O(N) to O(1) for project listing

- [ ] **28.2** Add pagination to job listing
  - Replace `limit=100` with configurable page size (default 50)
  - Add "Load More" or page navigation to Run page job history

- [ ] **28.3** Add connection pool configuration
  - Expose `pool_size`, `max_overflow` as Config options for PostgreSQL
  - SQLite: keep current `check_same_thread=False` approach

---

## Phase 29: Frontend Bundle Optimization

> Static assets have no cache headers. Tab content renders eagerly even
> when hidden.

- [ ] **29.1** Add static asset cache headers
  - ASGI middleware that adds `Cache-Control: public, max-age=86400` for
    CSS, JS, and font files served by Shiny

- [ ] **29.2** Add lazy tab content rendering
  - Use `ui.nav_panel(..., value=...)` with conditional rendering so
    heavy tabs (Visualize, Ensemble) only render when selected

- [ ] **29.3** Optimize Plotly figure serialization
  - Reduce decimal precision for large mesh coordinates (6 → 2 decimals
    for display-only plots)
  - Use `plotly.io.to_json(fig, engine="json")` for faster serialization

---

## Phase 30: Session Isolation

> In server mode, all users see all jobs and projects. No filtering by
> session or user identity.

- [ ] **30.1** Add session_id to project and job creation
  - Store `session.id` when creating projects and submitting jobs
  - Add `session_id` column to Project model (nullable for backwards compat)

- [ ] **30.2** Filter queries by session in server mode
  - `list_jobs()`, project listing, job history — filter by current session
  - In local mode, show everything (no filtering)

- [ ] **30.3** Add "My Jobs" / "All Jobs" toggle
  - Toggle switch on Run page and Dashboard
  - "All Jobs" only available when auth is enabled (admin view)

---

## Phase 31: Health & Monitoring

> No way to check if the app is healthy or monitor performance in production.

- [ ] **31.1** Add `/health` HTTP endpoint
  - Bypass auth middleware. Return JSON: `{"status": "ok", "version": "0.1.0",
    "uptime_seconds": N, "database": "ok|error", "queue_depth": N}`
  - Implement as ASGI middleware that intercepts `/health` path

- [ ] **31.2** Add structured JSON logging
  - `SHYFEM_UI_LOG_FORMAT=json` config option
  - Use `python-json-logger` or custom formatter
  - Fields: timestamp, level, logger, message, extra context

- [ ] **31.3** Add `/metrics` Prometheus endpoint
  - Server mode only. Expose: requests_total, request_duration_seconds,
    active_websocket_connections, job_queue_depth, job_status_counts
  - Use `prometheus_client` library (optional dependency)

---

## Phase 32: STR Template Library Expansion

> Only 3 simulation templates exist. SHYFEM supports many more scenarios.

- [ ] **32.1** Add Wind-Driven Circulation template
  - Pre-filled: wind forcing, Coriolis, constant depth, 2D barotropic

- [ ] **32.2** Add Tidal Estuary template
  - Pre-filled: tidal boundary, river inflow, salinity transport, 3D baroclinic

- [ ] **32.3** Add Sediment Transport template
  - Pre-filled: sediment module, settling velocity, erosion/deposition params

- [ ] **32.4** Add Water Quality template
  - Pre-filled: oxygen, nutrients, temperature, biological modules

- [ ] **32.5** Add Storm Surge template
  - Pre-filled: atmospheric pressure, wind fields, wetting/drying, high resolution

---

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
  - Useful for parameter variations without re-uploading files

---

## Implementation Priority

```
Phase 18 (Error handling audit)        ~0.5 day   — Immediate (silent failures)
Phase 19 (File upload validation)      ~0.5 day   — Immediate (security)
Phase 20 (Proxy & CSRF)               ~1 day     — High (server security)
Phase 21 (Middleware tests)            ~1 day     — High (untested infra)
Phase 22 (Component test coverage)     ~1 day     — High (4 untested components)
Phase 23 (Page logic tests)            ~1.5 days  — Medium (extract & test)
Phase 24 (Fix test failures)           ~0.5 day   — Medium (clean baseline)
Phase 25 (Real-time log streaming)     ~1 day     — Medium (UX)
Phase 26 (Data export)                 ~1 day     — Medium (user-facing)
Phase 27 (NetCDF variable explorer)    ~1 day     — Medium (feature)
Phase 28 (Database optimization)       ~0.5 day   — Lower (scalability)
Phase 29 (Frontend optimization)       ~0.5 day   — Lower (performance)
Phase 30 (Session isolation)           ~1 day     — Lower (multi-user)
Phase 31 (Health & monitoring)         ~1 day     — Lower (production ops)
Phase 32 (STR template expansion)      ~1 day     — Lower (content)
Phase 33 (Project import/export)       ~1.5 days  — Lower (feature)
```

## Verification Checklist (per phase)

1. `make lint` — **0 errors**
2. `make test` — **0 new failures**
3. `make coverage` — **coverage does not decrease**
4. `python -m shyfem_ui.app` — app launches without warnings
5. Navigate all 9 tabs in browser — no console errors
