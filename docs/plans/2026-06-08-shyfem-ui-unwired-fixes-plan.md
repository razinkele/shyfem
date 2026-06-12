# Plan — Address the 2026-06-08 "Unwired UI" Audit

Source: `docs/reviews/2026-06-08-shyfem-ui-unwired-audit.md`.
Conventions for every batch below (per CLAUDE.md + this session's practice):
- Own branch, TDD (RED→GREEN), `ruff` clean, full UI suite green (`CONDA_PREFIX="" pytest`, playwright excluded by default).
- UI changes deploy to laguna (Shiny Server symlinks the tree) → **hold each merge for the owner's go-ahead**; never auto-merge UI.
- Sequence by value: P1 → P2 → P4 → P5 → (P3, P6 as decided).

Legend: **[code]** = implement now; **[decision]** = needs owner/product call before doing.

---

## Phase 1 — Wire the maintenance cleanup tasks  (branch `fix/ui-maintenance-scheduler`) **[code]**
The highest-value item: `cleanup_old_jobs` and `cleanup_expired_sessions` are implemented + tested but never invoked → unbounded growth of `jobs`, `auth_sessions`, `ws_auth_tokens`.

**Design — a single app-global periodic task (server mode only):**
1. New `services/maintenance.py`: `async def run_maintenance_loop(job_queue, auth_service, *, interval_s, job_retention_days)` — loop: `await asyncio.sleep(interval_s)`; then `await job_queue.cleanup_old_jobs(days=job_retention_days)` and `await asyncio.to_thread(auth_service.cleanup_expired_sessions)` (the session purge is sync DB work — keep it off the event loop). Wrap each tick in try/except + `logger.exception` so one failure never kills the loop. Also expose `async def run_maintenance_once(...)` (the loop body) for testing.
2. Start it once per process via an **ASGI lifespan wrapper** in `app.py` (preferred — runs without a session): a thin wrapper that on `lifespan.startup` does `asyncio.create_task(run_maintenance_loop(...))`, gated to `deployment_mode == "server"` and `interval_s > 0`. Fallback if lifespan is awkward under Shiny: guarded lazy-start in `create_app` server fn (module-level `_started` flag + `asyncio.get_running_loop().create_task(...)`), mirroring the existing pattern at `app.py:912-946`.
3. Config (`config.py`): `maintenance_interval_seconds: int = Field(default=3600, ge=0)` (0 disables) and `job_retention_days: int = Field(default=30, gt=0)`. Document the env vars.

**Tests:** `tests/test_maintenance.py` — `run_maintenance_once` calls both cleanups with the configured args; a tick that raises is swallowed (loop survives); local-mode / interval 0 → loop not started (assert no task / no calls). Reuse existing cleanup tests (already cover row/session deletion).
**Risk:** low. Cleanup logic is proven; the only new surface is the scheduler. Confirm the lifespan wrapper composes with the existing middleware stack (it wraps outermost or innermost without breaking `/health`).
**Validation:** suite green; manual: run server mode with `interval=2`, confirm a tick fires and prunes a backdated job/session.

---

## Phase 2 — Fix the two dead UI controls  (branch `fix/ui-dead-controls`) **[code]**
2a. **physics `preview_btn` ("Preview STR")** (`pages/physics.py:308`). Intended behavior: render the STR that the current panel values would generate. Wire `@reactive.effect @reactive.event(input.preview_btn)` → build the STR text from `_collect_panel_values()` (already exists) via the str generation/serialization used on save, and show it in a modal (`ui.modal` with a `<pre>` / `ui.output_text_verbatim`). If STR generation isn't reusable standalone, extract a pure `build_str_text(values)` helper (testable). 
   - *Tests:* `build_str_text` returns expected sections for sample panel values; an AST/source check that `preview_btn` now has a reader (mirrors the access-control AST tests).
2b. **visualize `equal_aspect` checkbox** (`pages/visualize.py:229`). Thread it into the plot builder: read `input.equal_aspect()` alongside `show_colorbar`/`show_grid_lines` (615-616) and pass to the figure routine; apply equal aspect (matplotlib `ax.set_aspect("equal")` or plotly `yaxis.scaleanchor="x"`). 
   - *Tests:* the plot-builder helper, given `equal_aspect=True`, sets the aspect attribute (unit-test the figure object); confirm the input is now read.
**Risk:** low/medium — 2b touches a plot path; validate the figure still renders for raster + mesh cases.

---

## Phase 3 — Honor or drop the dead config knobs  (branch `fix/ui-config-knobs`) **[code, one decision]**
- **`mpi_default_np`** → honor: use as the default for the run-page `mpi_np` input (`pages/run.py:212,375`) and as the ensemble/JobSpec default instead of hardcoded `4`.
- **`mpirun_path`** → honor: pass `config.mpirun_path` into the wrappers (`job_local.py:321`, `job_celery.py:192`, `shyfem_wrapper` run paths) instead of the literal `"mpirun"`.
- **`theme`** → **[decision]** honor (apply `config.theme` to the shinyswatch/`data-bs-theme` setup) **or** delete the field. Recommend: delete — theming is already handled by `data-bs-theme` + `plotly_theme.py`, so honoring it duplicates a mechanism. Owner picks.
**Tests:** run page default reflects `mpi_default_np`; wrappers receive `config.mpirun_path` (mock + assert arg). 
**Risk:** low (declarations/defaults). No numeric/sim impact.

---

## Phase 4 — Remove dead code  (branch `fix/ui-dead-code-removal`) **[code, one decision]**
Reduce surface; each removal deletes the symbol **and** its now-orphaned tests (or repurposes the test).
- **`middleware/basic_auth.py`** (`BasicAuthMiddleware`) — delete module + `tests/test_basic_auth.py` (superseded by SessionAuth).
- **`components/job_status.py`**: remove `job_status_ui`/`job_status_server` (keep the used helpers `get_status_badge`/`format_datetime`/`format_duration`/`job_list_table`); drop the `__init__.py` re-exports of the removed pair.
- **`project_export.import_project_zip`** — delete (app uses `import_project`/`clone_project`).
- **Unused helpers:** `file_picker.param_to_file_types`, `str_editor.get_parameter_help`, `timeseries.compute_statistics`, `parser_grd.{get_nodes_array,get_elements_array,to_geographic,clear_cache}`, `parser_str.get_param_info`, `auth_service.{get_user,deactivate_user}`, `JobQueue.set_progress_callback` (+ both impls), `LocalJobQueue.running_job_count`, `CeleryJobQueue.{health_check,worker_info}`. Delete each + its dedicated test. (For any the owner wants kept as public API, leave + add a `# public API` note instead.)
- **`Job.celery_task_id`** column — **[decision]**: (a) **drop** → Alembic migration (SQLite needs batch/table-rebuild) — clean but migration risk; or (b) **wire** → populate it in `job_celery` on submit (`row.celery_task_id = task.id`) and surface in admin/job views. Recommend (b) if Celery is a supported backend, else (a). Owner picks.
**Risk:** low for pure deletions (build/suite catch refs); the migration (4a) is the only real risk.
**Validation:** full suite green after each removal; grep confirms zero remaining refs.

---

## Phase 5 — Surface or retire built-but-unexposed capabilities  (branch `fix/ui-expose-features`) **[decision-led]**
Each needs a product call (surface vs remove); implement the chosen direction TDD'd:
- **`run_shyplot`** (`shyfem_wrapper.py:402`) — add a "Generate plot (shyplot)" action (postprocess/visualize) wired to it, **or** remove the wrapper.
- **`WorkflowEngine.cancel_workflow`** (`workflow.py:373`) — add a Cancel control on the workflow/run UI wired to it (with authz like job-cancel), **or** remove.
- **`lgr_service.filter_by_time`** (`lgr_service.py:127`) — add a time-range control to the IBM particle view wired to it, **or** remove.
- **`WorkflowEngine.list_templates`** (`workflow.py:289`) — either route the pages through it (instead of reading `WORKFLOW_TEMPLATES` directly) or delete the accessor.
**Note:** default recommendation is *surface* `cancel_workflow` (clear user value) and *decide* the rest; this phase is gated on owner intent.

---

## Phase 6 — Minor cleanup  (branch `fix/ui-minor-unwired`) **[code + 1 decision]**
- **`_active_nav`** JS signal (`app.py:529`) — remove the `Shiny.setInputValue('_active_nav', …)` setter (no reader), unless a future feature wants it. Trivial.
- **Write-only Grid/Simulation columns** (`num_layers,min_depth,max_depth,time_step,start_time,end_time`) — **[decision]**: surface them in the project/grid detail view (they're populated on import) **or** drop them. Recommend: surface in the project detail panel (cheap value from data already stored) rather than drop. Owner picks.

---

## Decision checklist (need owner input before the gated phases)
1. **theme** config field — honor or delete? (Phase 3)
2. **Job.celery_task_id** — wire (populate + show) or drop (migration)? (Phase 4)
3. **Phase 5 features** — for each of run_shyplot / cancel_workflow / lgr time-filter / list_templates: surface or remove?
4. **Write-only columns** — surface in project detail or drop? (Phase 6)

## Suggested execution order
P1 (now, highest value) → P2 → P3 → P4 (pure deletions; hold celery_task_id sub-task on decision #2) → P6 trivial part → then P5 + remaining decisions once the owner answers the checklist. Each phase: branch → TDD → suite/ruff green → present for merge/deploy.
