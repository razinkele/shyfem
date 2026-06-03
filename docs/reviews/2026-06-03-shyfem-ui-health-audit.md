# SHYFEM-UI Codebase-Health Audit — 2026-06-03

8-dimension multi-agent audit (correctness, error-handling, db/data-layer, async/reactive, security-nonauth, performance, maintainability, test-quality). Each crit/high adversarially verified against source.

**Severity (confirmed crit/high; all reported med/low):** critical 0, high 6, medium 13, low 17 — 42 findings total, 11 crit/high confirmed-real.

## Health summary

This is a mature, recently-hardened Shiny-for-Python codebase whose authorization/WS-identity subsystem is genuinely solid and out of scope for this audit. The remaining health issues cluster in three areas: (1) a couple of correctness bugs on real user paths (Quick Settings double-quoting corrupts .str timing params; job-completion emails silently never sent to authenticated server users due to a swallowed DetachedInstanceError), (2) a security gap where an authenticated editor can write files outside the project sandbox via an absolute upload subdir, and (3) a cluster of performance/reliability gaps in the NetCDF/grid/bathymetry data paths that defeat the intended lazy loading and can OOM or hang the single worker. There is also notable but non-blocking tech-debt: large god-files (physics.py ~2450 LOC, home.py, simulation_logic.py embedded templates), duplicated denial/project-change boilerplate across pages, and a missing-table risk in the init_db create_all fallback (audit_logs) that is masked in production but bites fresh/packaged installs. Test quality is broad but has pockets of false assurance (app-wiring test asserts nothing about wiring, E2E never runs on main, the Celery worker entry point is untested). None of the confirmed findings are critical; the codebase is in good overall shape, with the highest-value work being a handful of targeted bug/security fixes plus SQLite WAL/busy_timeout for the multi-user deployment.

## Top priorities (ranked)

### 1. [HIGH] Arbitrary file write outside project via absolute upload subdir
- **File:** `shyfem_ui/services/file_service.py:71-84` · **Lens:** security-nonauth
- **Why:** upload_file validates subdir only against '..' in parts, not absolute paths. pathlib's work_dir / '/etc/cron.d' resolves to /etc/cron.d, so an authenticated editor can write attacker-controlled bytes anywhere the shiny worker uid can write (e.g. ~/.ssh/authorized_keys), escaping the project sandbox in multi-user server mode — a realistic priv-esc/RCE vector. The hardened Config.validate_save_path exists but this path bypasses it.
- **Fix:** Reject absolute subdirs (if safe_sub.is_absolute(): raise ValueError) and enforce resolved-path containment: target = (work_dir / safe_sub / safe_name).resolve(); require target.is_relative_to(work_dir.resolve()), or reuse config.validate_save_path on the final target. Add regression tests for subdir='/etc' and '../../escape'.

### 2. [HIGH] Quick Settings corrupts .str timing params as ''value'' (double-quoted)
- **File:** `shyfem_ui/services/simulation_logic.py:839-880 (and parser_str.py:268-283)` · **Lens:** correctness-bugs
- **Why:** apply_quick_settings pre-wraps values in single quotes, then _format_value re-wraps any string already starting with ' , emitting itanf = ''2020-01-01''. Reproduced live; the app's own StrParser.parse() returns None for these tokens, so the run the user just configured has a broken start/end/timestep. Reached by the visible 'Apply quick settings' button on a common path.
- **Fix:** Store the raw stripped value in apply_quick_settings (let _format_value quote exactly once) or make _format_value not re-wrap an already-quoted string. Add a generate()->parse() round-trip test asserting exactly one quote pair.

### 3. [HIGH] Job completion emails silently never sent for authenticated users
- **File:** `shyfem_ui/services/job_local.py:161-168` · **Lens:** error-handling-reliability
- **Why:** User row is queried inside `with db_session()` but username/email are accessed after the block closes; expire_on_commit defaults to True, so attribute access raises DetachedInstanceError, caught at debug level, leaving user_dict={} and the email silently dropped. In server mode every real job carries user_id, so the entire completion/failure email feature is universally broken despite SMTP being configured.
- **Fix:** Read scalar fields into locals inside the with-block: user_dict = {'username': user.username, 'email': user.email}. Add a job_local test with user_id plus a real User row.

### 4. [MEDIUM] SQLite engine has no busy_timeout or WAL -> 'database is locked' under concurrent writes
- **File:** `shyfem_ui/db/base.py:33-38` · **Lens:** db-data-layer
- **Why:** Production DB on laguna is SQLite with only check_same_thread=False. Default busy_timeout=0 means concurrent writers (audit log on login vs job-status persist vs concurrent uploads) raise 'database is locked' immediately. Job-persist failures are swallowed, so a locked-out terminal write silently drops completed/failed status from the DB. Single highest-leverage reliability fix for the multi-user deployment.
- **Fix:** Attach an @event.listens_for(engine, 'connect') listener for SQLite URLs that runs PRAGMA busy_timeout=5000 and PRAGMA journal_mode=WAL; pair with a single retry on OperationalError for the terminal job-state persist.

### 5. [MEDIUM] NetCDF variable table + statistics fully materialize every variable, defeating lazy load
- **File:** `shyfem_ui/pages/visualize.py:65-96 and 1330-1349` · **Lens:** performance
- **Why:** Dataset is opened lazily (chunks='auto') but build_variable_table and _netcdf_statistics call var.values.flatten() on every variable, forcing a full dask compute. Both are reactive @render.ui keyed on loaded_data, so a single loaded file triggers two independent full reads and re-reads on each invalidation. On large 3D SHYFEM output this degrades badly and can OOM the shared worker.
- **Fix:** Use dataset metadata only for the table (dims/shape/dtype/attrs); compute min/max/mean/std via dask-aware reductions (ds[var].min().compute()) with a single compute, and skip/sample when var.nbytes exceeds a configurable cap. Avoid the flatten()+boolean-mask copy.

### 6. [HIGH] GeoTIFF bathymetry sampled with per-pixel Python double loop
- **File:** `shyfem_ui/services/mesh_builder.py:896-905` · **Lens:** performance
- **Why:** _load_bathymetry_raster loops over every pixel calling src.xy() and transformer.transform() per pixel — O(rows*cols) pure Python with no downsampling or size cap (max_upload_size_mb bounds compressed bytes, not pixel count). A 10k x 10k DEM (100M px) effectively hangs, and it runs synchronously in a reactive handler so it blocks the single-threaded event loop and stalls all sessions.
- **Fix:** Vectorize: build row/col index grids, compute world coords once via rasterio.transform.xy on arrays, mask nodata with numpy, batch one transformer.transform(x_array, y_array) call; optionally subsample large rasters. Offload via asyncio.to_thread.

### 7. [HIGH] init_db() create_all fallback never registers AuditLog -> audit_logs silently absent
- **File:** `shyfem_ui/db/base.py:68 (and shyfem_ui/models/__init__.py:16-18)` · **Lens:** db-data-layer
- **Why:** init_db imports only project/user/workflow, so Base.metadata lacks audit_logs and the create_all fallback never creates it; the first AuditService.log()/query() then fails with 'no such table'. Same omission already caused an incident and was patched in migrations/env.py but left unfixed here. Masked on git-tree production but hits fresh/packaged installs.
- **Fix:** Add audit_log to the init_db import and to models/__init__.py so create_all covers every table; add a guard test asserting Base.metadata.tables matches the full model set.

### 8. [MEDIUM] log_viewer calls async on_refresh callback without awaiting it
- **File:** `shyfem_ui/components/log_viewer.py:150-159 (caller run.py:508)` · **Lens:** async-reactive
- **Why:** on_refresh is typed sync but run.py passes an async def; calling it builds a discarded coroutine, so the component's own Refresh button and Auto-refresh checkbox are dead and emit RuntimeWarnings. Once a job finishes, the page-level auto-refresh stops, so the manual Refresh (the intended way to pull the final log) silently does nothing.
- **Fix:** In the log_viewer effects, detect coroutine functions (inspect.iscoroutinefunction / isawaitable) and await them inside async effect variants; widen the type hint to Callable[[], Awaitable[None] | None].

### 9. [MEDIUM] Job stuck RUNNING and _running_count leaks if stdout open() fails
- **File:** `shyfem_ui/services/job_local.py:275-294` · **Lens:** error-handling-reliability
- **Why:** touch()/open() for the stdout file happens after _running_count is incremented but before the try whose finally decrements it. If open fails (ENOSPC, permissions, deleted dir), the exception escapes the fire-and-forget task: the job stays persisted as RUNNING forever and effective concurrency is permanently reduced.
- **Fix:** Move stdout_fh setup inside the try so the existing finally always runs, and ensure _running_count is decremented in a finally covering the whole semaphore-held region; mark the job FAILED on open error.

### 10. [MEDIUM] No timeout on SHYFEM subprocess; hung tool wedges job and workflow forever
- **File:** `shyfem_ui/services/shyfem_wrapper.py:157-188 (with workflow.py:521-529)` · **Lens:** error-handling-reliability
- **Why:** run_command awaits proc.wait() with no wall-clock cap and no kill path; combined with workflow._wait_for_job's unbounded poll loop, a single hung Fortran tool holds a concurrency slot indefinitely and starves other jobs, recoverable only by manual cancel.
- **Fix:** Wrap the gather/proc.wait in asyncio.wait_for with a configurable timeout; on TimeoutError call proc.kill()/terminate() and return a FAILED CommandResult. Give workflow._wait_for_job a max-wait deadline.

## Strengths

- The WebSocket auth / authorization subsystem (access_control, per-page write guards, ws_identity, tutorial read-only) was hardened over 8 adversarial review rounds and is genuinely solid — no new auth defects found.
- Subprocess execution consistently uses asyncio.create_subprocess_exec (no shell=True), so even the unvalidated 'custom' shyelab option pass-through is bounded to argument injection into one tool rather than OS command injection.
- A hardened Config.validate_save_path already exists and resolves+enforces work_dir containment — the right primitive is in the codebase; the upload path just needs to reuse it.
- Strong overall test breadth: ~1342+ unit tests plus 167 Playwright E2E tests, with deliberate two-server local/server-mode test architecture and documented Shiny reactive pitfalls.
- Correct async offloading patterns already demonstrated (mesh_builder uses asyncio.to_thread for heavy work) — a known-good template the visualize/bathymetry paths can follow.
- Best-effort error handling around job persistence and notifications keeps a single failure from crashing the worker, even where it currently swallows too much.
- Lazy/dask-backed NetCDF open was chosen intentionally (explicit comment), showing performance awareness — the regressions are localized misuse, not an architectural miss.
- Good institutional memory: prior incidents (audit_logs, proxy root_path, WS query-string stripping) are documented and mostly remediated, indicating a healthy fix-and-record culture.

## All findings (by lens)

- **[high]** (correctness-bugs) Quick Settings corrupts .str file: timing params written as ''value'' (double-quoted) — `shyfem_ui/services/simulation_logic.py:839-880 (and parser_str.py:268-283)`
- **[high]** (error-handling-reliability) Job completion emails silently never sent for authenticated users (DetachedInstanceError swallowed) — `shyfem_ui/services/job_local.py`
- **[high]** (error-handling-reliability) Pre-flight simulation file validation fails OPEN — all errors swallowed — `shyfem_ui/services/run_logic.py`
- **[high]** (db-data-layer) init_db() create_all fallback never registers AuditLog -> audit_logs table is silently absent — `shyfem_ui/db/base.py:68 (and shyfem_ui/models/__init__.py:16-18)`
- **[high]** (async-reactive) log_viewer calls async on_refresh callback without awaiting it — `shyfem_ui/components/log_viewer.py`
- **[high]** (security-nonauth) Arbitrary file write outside project via absolute upload subdir — `shyfem_ui/services/file_service.py`
- **[high]** (performance) NetCDF variable summary table fully materializes every variable, defeating lazy loading — `shyfem_ui/pages/visualize.py`
- **[high]** (performance) NetCDF statistics panel loads every variable in full (same defeat-lazy-load problem) — `shyfem_ui/pages/visualize.py`
- **[high]** (performance) GeoTIFF bathymetry sampled with a per-pixel Python double loop calling src.xy() each pixel — `shyfem_ui/services/mesh_builder.py`
- **[high]** (maintainability) physics.py is a 2450-LOC god file with 30+ panel builders in one server function — `shyfem_ui/pages/physics.py:329-2450`
- **[high]** (test-quality) Celery worker entry point execute_shyfem_job has no direct test — `shyfem_ui/services/job_celery.py`
- **[medium]** (error-handling-reliability) Job stuck RUNNING forever and _running_count leaks if stdout file open() fails — `shyfem_ui/services/job_local.py`
- **[medium]** (error-handling-reliability) No timeout on SHYFEM subprocess execution — a hung tool blocks the worker indefinitely — `shyfem_ui/services/shyfem_wrapper.py`
- **[medium]** (db-data-layer) Default SQLite engine has no busy_timeout or WAL mode -> 'database is locked' under concurrent writes in server mode — `shyfem_ui/db/base.py:33-38`
- **[medium]** (async-reactive) Synchronous grid/NetCDF/timeseries loading blocks the event loop in visualize page — `shyfem_ui/pages/visualize.py`
- **[medium]** (async-reactive) Cross-page notification poll spawns an untracked task every 5s via get_event_loop().create_task — `shyfem_ui/app.py`
- **[medium]** (performance) Time-series loader stores both the DataFrame and a full list-of-lists copy, doubling memory — `shyfem_ui/services/timeseries_loader.py`
- **[medium]** (performance) read_csv uses the slow python engine with delimiter sniffing and no row cap — `shyfem_ui/services/timeseries_loader.py`
- **[medium]** (maintainability) Editor/write-denial preamble copy-pasted ~17 times across 11 page modules — `shyfem_ui/pages/physics.py:444-451`
- **[medium]** (maintainability) Page server signatures inconsistently typed/ordered for active_project, current_user, config — `shyfem_ui/pages/ibm.py:225`
- **[medium]** (maintainability) _on_project_changed reactive effect reimplemented in 8 pages with subtly different rules — `shyfem_ui/pages/postprocess.py:242`
- **[medium]** (maintainability) STR param/section wiring relies on three parallel untyped string maps with silent-drop failure — `shyfem_ui/pages/physics.py:383-439`
- **[medium]** (test-quality) test_app_wiring.py claims to regression-test service wiring but asserts nothing about the wiring — `tests/test_app_wiring.py`
- **[medium]** (test-quality) 167 Playwright E2E tests never run on push to main — `.github/workflows/ui-ci.yml`
- **[low]** (correctness-bugs) ilagr-without-$lagrg validation is dead code (reads wrong section) — `shyfem_ui/services/str_validator.py:123-135`
- **[low]** (correctness-bugs) Audit-log 'Next' pager has no upper bound; shows empty page past the last — `shyfem_ui/pages/admin.py:656-684`
- **[low]** (error-handling-reliability) Convenience run_* methods mutate the caller's options list (append/extend in place) — `shyfem_ui/services/shyfem_wrapper.py`
- **[low]** (error-handling-reliability) Email template separator warning logic is inverted and would drop a body line if templates lacked CRLF — `shyfem_ui/services/notification_service.py`
- **[low]** (db-data-layer) _persist_job swallows all DB exceptions, so dropped writes leave DB job state stale — `shyfem_ui/services/job_local.py:144-145`
- **[low]** (async-reactive) NetCDF dimension-label text renderers are re-registered inside a reactive effect without a dedup guard — `shyfem_ui/pages/visualize.py`
- **[low]** (async-reactive) Per-session _latest_progress dict accumulates one entry per job and is never pruned — `shyfem_ui/pages/run.py`
- **[low]** (async-reactive) Background workflow task is fire-and-forget; exceptions outside the per-step loop are unhandled — `shyfem_ui/services/workflow.py`
- **[low]** (security-nonauth) Unvalidated free-text CLI options passed to shyelab subprocess — `shyfem_ui/services/postprocess_logic.py`
- **[low]** (security-nonauth) Ensemble run directory name derived from param values without traversal sanitization — `shyfem_ui/pages/ensemble.py`
- **[low]** (performance) Log tail and DB persistence do synchronous file/DB I/O on the async event loop — `shyfem_ui/services/job_local.py`
- **[low]** (performance) CSV export uses df.iterrows() and builds the whole file as an in-memory base64 data URI — `shyfem_ui/components/timeseries.py`
- **[low]** (maintainability) access_control symbols imported module-level in 9 pages but lazily inside functions in 14 sites — `shyfem_ui/pages/files.py:300`
- **[low]** (maintainability) home.py dashboard is 1342 LOC with 38 nested render functions in one server — `shyfem_ui/pages/home.py:285`
- **[low]** (maintainability) simulation_logic.py embeds ~17 full STR templates as inline triple-quoted strings (~820 LOC of data-in-code) — `shyfem_ui/services/simulation_logic.py:16-839`
- **[low]** (maintainability) visualize.py concentrates all Plotly figure construction (56 go.Figure/update_layout sites) while sibling result pages use unrelated approaches — `shyfem_ui/pages/visualize.py:551-1000`
- **[low]** (test-quality) Job-eviction test uses a fixed sleep and a slack-padded assertion — `tests/test_job_local.py`
- **[low]** (test-quality) Several job_local status tests observe async state via a single fixed sleep(0.1) — `tests/test_job_local.py`