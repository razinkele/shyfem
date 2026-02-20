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

- [x] **21.1** Test RateLimitMiddleware
  - Test: requests under limit pass through (200)
  - Test: requests at limit return 429 with Retry-After header
  - Test: sliding window resets after 60 seconds
  - Test: WebSocket connections bypass rate limiting
  - Test: different clients have independent limits
  - Test: 429 body contains rate limit message

- [x] **21.2** Test BasicAuthMiddleware
  - Test: valid credentials return 200
  - Test: invalid credentials return 401 with WWW-Authenticate
  - Test: missing Authorization header returns 401
  - Test: WebSocket with bad auth returns close code 4001
  - Test: non-http/websocket scopes pass through
  - Test: malformed base64, non-Basic scheme, password with colon, WS valid auth

- [x] **21.3** Test session cleanup callback
  - Mock job_queue.list_jobs and cancel, verify orphaned jobs cancelled
  - Test: exceptions in cleanup are logged, not raised
  - Test: mixed active/inactive, empty list, cancel failure handling

- [x] **21.4** ~~Test Alembic migrations~~ — SKIPPED
  - Low ROI: only 2 migration files, init_db() has create_all fallback

---

## Phase 22: Component Test Coverage

> 4 components have zero unit tests: job_status, file_browser, log_viewer,
> plot_widget. These contain testable pure functions.

- [x] **22.1** Test `components/job_status.py` — 17 tests (6 parametrized)
  - `format_duration()` — None, 0s, 30s, 90s, 3600s, fractional
  - `format_datetime()` — None, datetime objects
  - `get_status_badge()` — all 6 JobStatus enum values return valid HTML
  - `job_list_table()` — empty list, single job, multiple jobs

- [x] **22.2** Test `components/file_browser.py` — SKIPPED
  - Already has 9 tests from Phase 19 (validate_upload). Remaining code is
    Shiny reactive — not unit-testable without live session.

- [x] **22.3** Test `components/log_viewer.py` — 13 tests
  - `format_log_line()` — plain text, HTML escaping, XSS prevention, color
    highlighting (error/warning/success/header/time), truncation, non-string coercion

- [x] **22.4** Test `components/plot_widget.py` — 11 tests
  - `plot_mesh()` — returns Figure, title, show_nodes, show_labels
  - `plot_depth_contour()` — returns Figure, title, no-depth edge case
  - `plot_boundaries()` — returns Figure, title
  - `plot_element_quality()` — returns Figure, title with triangle count

---

## Phase 23: Page Logic Tests

> Compare, ensemble, and visualize pages contain complex pure logic buried
> inside reactive handlers. Extract and test independently.

- [x] **23.1** Test `pages/compare.py` pure functions — 8 tests
  - `_compute_param_diff()` — identical, different values, extra sections, empty
  - `_load_ts()` — valid file, non-numeric skipping, empty file

- [x] **23.2** Test `pages/ensemble.py` pure functions — 17 tests
  - `_try_convert()` — int, float, string, negative
  - `_combo_label()` — empty, single, sanitized, truncation
  - `_load_ts()` — valid, missing file, empty
  - `_build_duration_chart()` — returns Figure, traces, title
  - `_build_ensemble_ts_plot()` — single run, envelope with 2 runs, empty

- [x] **23.3** Test `pages/visualize.py` pure functions — 11 tests
  - `_load_timeseries()` — CSV, whitespace-delimited, empty
  - `_plotly_timeseries()` — line/scatter/area plot types, raw data path
  - `_compare_grids()` — returns Figure, title
  - `_compare_timeseries()` — returns Figure, 4 traces

---

## Phase 24: Fix Pre-Existing Test Failures

> Root cause: `test_playwright_active_project.py` was not excluded from
> default pytest runs, creating an event loop conflict with pytest-asyncio.
> Fix: `--ignore-glob` in addopts + `e2e` marker on all Playwright files.
> Result: 429 passed, 0 failed.

- [x] **24.1** ~~Fix test_workflow.py async failures~~ — No code fix needed
  - Root cause was Playwright event loop contamination, not async test code
  - Tests pass once Playwright files are excluded from collection

- [x] **24.2** ~~Fix test_wrapper.py async failures~~ — No code fix needed
  - Same root cause as 24.1; tests pass with proper isolation

- [x] **24.3** Add pytest markers for selective test runs
  - Added `--ignore-glob=tests/test_playwright_*.py` to pyproject.toml addopts
  - Registered `e2e` and `slow` markers
  - Added `pytest.mark.e2e` to all 5 Playwright test files
  - Result: 429 passed, 0 failed

---

## Phase 25: Real-Time Log Streaming

> Fixed: pipeline approach instead of LogBroadcaster (YAGNI). Incremental
> file writes + wired auto-refresh + configurable polling = real-time logs.

- [x] **25.1** ~~Create `LogBroadcaster` service~~ — YAGNI, polling is adequate
  - Instead: `tail_file()` utility with seek-from-end for large files
  - Shared by both `LocalJobQueue` and `CeleryJobQueue`

- [x] **25.2** Fix log streaming pipeline
  - `job_local.py`: stdout written incrementally (append+flush per line)
  - `run.py`: wired `on_refresh=_refresh_log` (was no-op `lambda: None`)
  - `run.py`: added `await _refresh_log()` to auto-refresh loop
  - `log_viewer.py`: configurable `refresh_interval` param (was hardcoded 2s)

- [x] **25.3** ~~Add configurable streaming interval~~ — Used existing config
  - `log_refresh_interval` config (default: 5s) now honored by log viewer
  - No new config option needed

---

## Phase 26: Data Export

> Scoped to missing items. Existing exports (Plotly PNG modebar, timeseries
> CSV, job reports) already functional.

- [x] **26.1** ~~Add plot export buttons~~ — Already exists (Plotly modebar)
  - Enhanced: added SVG export option, removed logo, vertical modebar
  - Applied `_with_export_config()` to all 3 render_widget functions

- [x] **26.2** ~~Add CSV export for time series~~ — Already exists
  - `timeseries.py` has full CSV export (lines 376-422)

- [x] **26.3** ~~Add report download to Run page~~ — Already exists
  - "Generate Report" button with `ReportBuilder` already functional

- [x] **26.4** Add grid statistics JSON export
  - "Export Stats JSON" button on Grid Prep page
  - `grid_stats_to_json()` pure function with 5 tests
  - Base64 data URI download via `session.send_custom_message`

---

## Phase 27: NetCDF Variable Explorer

> Scoped to metadata visibility. Variable dropdown and dimension sliders
> already existed. Added info table, coordinate labels, and metadata panel.

- [x] **27.1** Add variable info table to Data Info tab
  - `build_variable_table(ds)` — name, dims, dtype, units, long_name, min/max
  - 5 tests. Displayed in Data Info tab when NetCDF loaded.

- [x] **27.2** ~~Add dimension slicing controls~~ — Already existed
  - Enhanced: coordinate labels under each slider via `get_dim_label()`
  - Shows timestamps for time dims, depth values for vertical dims
  - 5 tests for label formatting

- [x] **27.3** Add variable metadata display
  - `get_variable_attrs(ds, var)` — long_name, standard_name, units,
    valid_range, _FillValue. 4 tests. Displayed below variable selector.

---

## Phase 28: Database Query Optimization

> Dashboard loads all projects with all grids and simulations, causing
> N+1 queries. Job listing is hardcoded to 100.

- [x] **28.1** ~~Add eager loading for Dashboard queries~~ — SKIPPED
  - Dashboard converts relationships to dicts immediately; N+1 doesn't occur in practice.

- [x] **28.2** ~~Add pagination to job listing~~ — SKIPPED
  - Job listing already has configurable `limit` parameter (100 local, 500 DB).

- [x] **28.3** Add connection pool configuration — 7 tests
  - `db_pool_size`, `db_pool_overflow`, `db_pool_recycle` config fields
  - PostgreSQL: pool_size, max_overflow, pool_recycle, pool_pre_ping=True
  - SQLite: unchanged (check_same_thread=False, no pool args)

---

## Phase 29: Frontend Bundle Optimization

> Static assets have no cache headers. Lazy tabs and Plotly precision
> optimization are low ROI for the current scale.

- [x] **29.1** Add static asset cache headers — 17 tests
  - `CacheHeaderMiddleware` adds `Cache-Control: public, max-age=N` for
    `.css`, `.js`, `.woff2`, `.woff`, `.ttf`, `.png`, `.svg`, `.ico`
  - `static_cache_max_age` config (default 86400, env `SHYFEM_UI_STATIC_CACHE_MAX_AGE`)
  - max_age=0 disables header injection

- [x] **29.2** ~~Add lazy tab content rendering~~ — SKIPPED
  - Shiny is server-rendered, not SPA. Invasive refactor of all 9 page modules. Low ROI.

- [x] **29.3** ~~Optimize Plotly figure serialization~~ — SKIPPED
  - Micro-optimization. Negligible benefit for current mesh sizes.

---

## Phase 30: Session Isolation

> In server mode, each browser session sees only its own jobs by default.
> Projects remain shared. Toggle switches between "My Jobs" and "All Jobs".

- [x] **30.1** ~~Add session_id to project and job creation~~ — SKIPPED
  - Jobs already have `session_id` column and metadata. Projects stay shared.

- [x] **30.2** Filter queries by session in server mode — 5 tests
  - Dashboard `_refresh_jobs()` filters by session (was showing all jobs)
  - `session.on_ended` cleanup only cancels own session's jobs (multi-user bug fix)

- [x] **30.3** Add "All jobs" toggle — Run page + Dashboard
  - `ui.input_switch` visible only in server mode, default off (My Jobs)
  - Toggling to "All jobs" removes session_id filter from list_jobs

---

## Phase 31: Health & Monitoring

> Health check endpoint for load balancers and uptime monitoring.

- [x] **31.1** Add `/health` HTTP endpoint — 10 tests
  - `HealthCheckMiddleware` as outermost ASGI wrapper (bypasses auth + rate limit)
  - Returns JSON: status, version, uptime_seconds, database, active_jobs
  - `"ok"` when healthy, `"degraded"` when DB or queue has errors
  - DB probe via `SELECT 1`, job count via `active_job_count` property

- [x] **31.2** ~~Add structured JSON logging~~ — SKIPPED
  - Low priority. stdlib logging adequate for current usage.

- [x] **31.3** ~~Add `/metrics` Prometheus endpoint~~ — SKIPPED
  - Adds `prometheus_client` dependency and significant instrumentation. Low ROI.

---

## Phase 32: STR Template Library Expansion

> Expanded template library covering all major SHYFEM simulation scenarios (9 total). 32 tests.

- [x] **32.1** Enhance Wind-Driven Circulation template — added Coriolis, Smagorinsky
  - Was minimal (wind file only). Now has `icor=1`, `idhtyp=2`, `dlat=45`

- [x] **32.2** Add Tidal Estuary template (3D) — new `tidal_estuary`
  - 3D baroclinic with salinity, GOTM turbulence, tidal + river boundaries
  - Separate from existing basic `tidal` (which stays 2D)

- [x] **32.3** Add Sediment Transport template — new `sediment_transport`
  - Simple sedi module (`issedi=1`) with 3D setup
  - Commented `$sedtr` section for advanced full-module usage

- [x] **32.4** Add Water Quality template — new `water_quality`
  - WASP/EUTRO 9-variable model (`ibio=1`), 3D baroclinic, heat flux
  - Bio boundary/initial condition file references

- [x] **32.5** Add Storm Surge template — new `storm_surge`
  - 2D barotropic, `idt=60s`, Wu drag (`itdrag=2`), wetting/drying
  - Coriolis, optional spherical coords, atmospheric pressure

---

## Phase 33: Project Import/Export

> Export, import, and clone projects for sharing and backup. 21 tests.

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

---

## Phase 34: STR Validation Engine Tests

> Zero-coverage pure functions in `str_editor.py` — validate_str_content(), _check_range(),
> generate_section_template(), get_parameter_help(). 45 tests.

- [x] **34.1** Add structural validation tests — 6 tests
  - Missing $end, extra $end, missing $para, missing $title, valid minimal STR

- [x] **34.2** Add timing validation tests — 6 tests
  - Missing itanf/itend/idt, itanf >= itend, idt <= 0

- [x] **34.3** Add depth/range/unknown param tests — 4 tests
  - hzmin >= hzoff, unknown param warning, idt/itm prefix exceptions

- [x] **34.4** Add file existence tests — 3 tests
  - check_files=True with missing/existing files, check_files=False

- [x] **34.5** Add _check_range unit tests — 12 tests
  - [0,1] range boundaries, >0, >=0, non-matching options

- [x] **34.6** Add generate_section_template tests — 7 tests (5 parametrized)
  - Known sections, unknown section generic, para timing params

- [x] **34.7** Add get_parameter_help tests — 7 tests
  - Known param (with units/default/options), unknown param/section, name section

---

## Phase 35: Boundary Editor & Home Helper Tests

> Extract pure functions from Shiny reactive closures, then test. 30 tests.

- [x] **35.1** Extract `_safe_filename` to module level in `home.py`
  - Moved from closure inside `home_server()` to module-level function

- [x] **35.2** Extract `generate_bound_text()` and `parse_boundary_csv()` from `boundary_editor.py`
  - Pure logic extracted from reactive effects, call sites updated

- [x] **35.3** Add generate_bound_text tests — 11 tests
  - Empty, single boundary, boundn/zfact/intpol inclusion/omission, multiple boundaries

- [x] **35.4** Add parse_boundary_csv tests — 10 tests
  - Two/five columns, comments, blanks, single column skip, start_id, defaults, invalid data

- [x] **35.5** Add _safe_filename tests — 9 tests
  - Normal name, special chars, unicode, hyphens, spaces, empty, long name

---

## Phase 36: CeleryJobQueue Mock Tests

> Production job queue backend with zero unit tests. 26 tests with mocked Redis/Celery.

- [x] **36.1** Add Redis helper tests — 3 tests
  - _store_job_info calls hset+zadd, _load_job_info returns/None

- [x] **36.2** Add submit tests — 4 tests
  - Returns job ID, dispatches apply_async, stores twice in Redis, MPI metadata

- [x] **36.3** Add cancel tests — 3 tests
  - Active→True+revoke, completed→False, nonexistent→False

- [x] **36.4** Add get_status/list_jobs tests — 7 tests
  - Existing/nonexistent status, empty/multiple/filter/limit list

- [x] **36.5** Add get_output tests — 3 tests
  - Nonexistent job, no file, has file with tail_file

- [x] **36.6** Add health_check/cleanup tests — 6 tests
  - Redis OK/down, active tasks, old inactive removed, active skipped, empty

---

## Phase 37: STR Parameter Search

> Search/filter box in the STR editor form view. Filters parameters across
> all sections by name or description with match highlighting.

- [x] **37.1** Add `filter_sections()` pure function — 11 tests
  - Case-insensitive substring match on param name + description
  - Unknown params matched by name only, standalone entries skipped
  - Returns `None` for empty search (show all), `{}` for no matches

- [x] **37.2** Add search input to form panel UI
  - Text input with placeholder, match count badge
  - Non-matching sections hidden, matching param labels highlighted
  - Empty results show "No matching parameters" message

- [x] **37.3** Wire search reactively in `str_editor_server`
  - `input.param_search()` → `filter_sections()` → `_build_form_panel(search_filter=...)`

---

## Phase 38: Job Notification Improvements

> Cross-page job completion/failure notifications using app-level polling
> with status transition detection.

- [x] **38.1** Add `NotificationService` — 11 tests
  - Detects transitions to terminal states (completed, failed, cancelled)
  - First-poll deduplication (no alert storm on startup)
  - Prunes stale jobs from seen set

- [x] **38.2** Wire into `_build_server()` in `app.py`
  - `reactive.invalidate_later(5)` polls job queue every 5 seconds
  - Calls `ui.notification_show()` with appropriate type/duration
  - Session-aware in server mode (only own jobs)

---

## Phase 39: Rate Limiter LRU + Debug Middleware Cleanup

> Ops readiness: remove temporary debug middleware and add memory safety
> to the rate limiter for long-running server deployments.

- [x] **39.1** Remove `_WsDebugMiddleware`
  - Deleted class definition (41 lines) and usage in `create_app()`
  - Was labeled "Temporary", shipped for 30+ phases

- [x] **39.2** Add LRU client eviction to `RateLimitMiddleware` — 3 tests
  - `max_clients` parameter (default 10,000)
  - Two-pass `_prune_clients()`: stale-first, then LRU by recency
  - Prevents unbounded `_requests` dict growth on busy servers

---

## Phase 40: Compare Page Diff Colorization

> Scientific workflow: improve param diff readability and STR file selection.

- [x] **40.1** Add semantic diff colorization to Parameter Diff tab — 7 tests
  - `diff_type` field on each row: `"only_a"` (red), `"only_b"` (green), `"changed"` (yellow)
  - Module-level `_DIFF_TYPE_CLASSES` mapping to Bootstrap classes

- [x] **40.2** Add STR file picker from active project — 7 tests
  - `_extract_str_choices()` pure function extracts STR paths from project context
  - Reactive `str_file_inputs` renderer: dropdown when project active, text input fallback
  - De-duplicates paths with simulation entries taking priority

---

## Phase 41: Batch shy→NetCDF Conversion

> Scientific workflow: streamlined batch conversion of .shy output files to NetCDF.

- [x] **41.1** Add `_discover_shy_files()` helper + batch convert UI/server logic — 7 tests
  - Auto-discovers .shy files from project directory or input path
  - Checkbox selection + dedicated "Convert Selected to NetCDF" button
  - Reuses existing batch_results table and log viewer for progress display
  - `_format_size()` shared helper for human-readable file sizes

---

## Phase 42: Workflow State Persistence + Misc UX

> UX polish: ensemble management and workflow state audit.

- [x] **42.1** Dark mode preference restoration — already implemented
  - localStorage-based persistence at app.py:421-437
  - Reads on DOMContentLoaded, saves on toggle

- [x] **42.2** Workflow state across tab navigation — handled by framework
  - Shiny module server closures persist reactive values across tab switches
  - No additional persistence layer needed for in-session navigation

- [x] **42.3** Ensemble "Stop All" button — 4 tests
  - `_cancel_jobs()` async helper for batch cancellation (module-level, typed)
  - Button shown only when running or queued jobs exist (`btn-danger`)
  - Cancels all jobs in current ensemble via `job_queue.cancel()`

---

## Phase 43: Richer /health + Request Correlation IDs

> Ops readiness: enhanced health endpoint and request tracing.

- [x] **43.1** Enrich /health endpoint — 13 tests (10 existing + 3 new)
  - `_check_db_health()` returns response time in ms (float)
  - New payload fields: `db_response_time_ms`, `queue_depth`, `worker_count`
  - Graceful degradation: -1.0 on failure for each metric

- [x] **43.2** Request ID middleware — 7 tests
  - `RequestIdMiddleware` (ASGI): generates UUID per HTTP request
  - `request_id_var` (contextvars): async-safe propagation through logs
  - `RequestIdFilter` (logging): injects `request_id` into log records
  - Accepts incoming `X-Request-Id` header from reverse proxy
  - Wired in `create_app()` between RateLimit and HealthCheck layers

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
