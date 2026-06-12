# SHYFEM Shiny UI — "Defined but Not Wired In" Audit

**Date:** 2026-06-08
**Scope:** `shyfem-ui/shyfem_ui/` — pages, components, services, middleware, config, models, JS.
**Method:** 6 parallel static audits (components+nav+middleware, services dead-code, config fields, reactive input/output orphans ×2, models+JS). Each finding has file:line evidence; false positives from dynamic dispatch / module namespacing / JS-set inputs were filtered out.

**Headline:** all 15 pages are reachable and reactively well-wired (only **2 truly dead UI controls**). The real gaps are **backend capabilities that exist but nothing invokes** — most importantly the **two cleanup tasks that are never scheduled**, so the jobs table and auth sessions grow unbounded.

---

## P1 — Operational: maintenance tasks that exist but are never run
These are implemented (and `cleanup_old_jobs` was just hardened on 2026-06-08 to delete DB rows) but **nothing in the app ever calls them** — no startup task, scheduler, or cron:

- **`JobQueue.cleanup_old_jobs`** (`job_queue.py:186` abstract; `job_local.py:452`, `job_celery.py:545`) — zero call sites. The jobs table is never auto-pruned → unbounded growth (the exact buildup we cleaned from prod). *The recent row-deletion fix only matters once this is wired.*
- **`AuthService.cleanup_expired_sessions`** (`auth_service.py:412`) — zero call sites. Expired `auth_sessions` are only purged lazily one-at-a-time in `validate_session`; this bulk purge (which also clears expired `ws_auth_tokens`) never runs → `auth_sessions` / `ws_auth_tokens` grow unbounded.

**Fix:** wire both into a periodic task (startup `asyncio` task on an interval, or a `/health`-adjacent tick), gated to server mode.

## P2 — Dead UI controls (user can interact; nothing happens)
- **`physics.py:308` `preview_btn` ("Preview STR")** — no `input.preview_btn()` reader anywhere. Clicking it does nothing. (confidence: high)
- **`visualize.py:229` `equal_aspect` checkbox ("Equal Aspect Ratio")** — never read by any plot builder (siblings `show_colorbar`/`show_grid_lines` are read at 615-616). Toggling has no effect. (high)

**Fix:** either wire each to its intended effect, or remove the control.

## P3 — Backend capabilities present but not exposed in the UI
- **`ShyfemWrapper.run_shyplot`** (`shyfem_wrapper.py:402`) — the `shyplot` CLI wrapper is never invoked. Plot-via-shyplot is unreachable (all other `run_shy*` wrappers are wired).
- **`WorkflowEngine.cancel_workflow`** (`workflow.py:373`) — no UI path cancels a running workflow.
- **`lgr_service.filter_by_time`** (`lgr_service.py:127`) — particle-track time filtering exists but isn't wired into the IBM page.
- **`WorkflowEngine.list_templates`** (`workflow.py:289`) — pages read the `WORKFLOW_TEMPLATES` constant directly instead.

**Fix:** decide per item whether to surface it (button/control) or drop it.

## P4 — Dead config knobs (env-bindable, look wired, do nothing)
| Field | Env var | Reality |
|---|---|---|
| `mpi_default_np` | `SHYFEM_UI_MPI_DEFAULT_NP` | never read; run page hardcodes `value=4`, JobSpec defaults stand in |
| `mpirun_path` | `SHYFEM_UI_MPIRUN_PATH` | never read; callers pass the literal `"mpirun"` |
| `theme` | `SHYFEM_UI_THEME` | never read; theming is via `data-bs-theme` + `plotly_theme.py` |

`mpi_default_np`/`mpirun_path` are especially misleading (near-identical local names look wired). **Fix:** either consume them or delete the fields.

## P5 — Dead code (superseded / never mounted — safe-to-remove candidates)
- **`BasicAuthMiddleware`** (`middleware/basic_auth.py:8`) — never mounted; fully superseded by `SessionAuthMiddleware`. Test-covered dead middleware.
- **`job_status_ui` / `job_status_server`** (`components/job_status.py:50,59`) — a reusable job-status widget never mounted by any page (run.py uses its own inline UI). Its *helpers* (`get_status_badge`, `format_duration`, `job_list_table`) are used; the widget pair is not.
- **`project_export.import_project_zip`** (`project_export.py:128`) — third project-import variant; app uses `import_project` + `clone_project`.
- **`Job.celery_task_id`** column (`models/project.py:225`) — never written or read; only in the model + initial migration. Dead column (drop needs a migration).
- **Unused helpers (tested but unwired):** `file_picker.param_to_file_types`, `str_editor.get_parameter_help`, `timeseries.compute_statistics`.
- **Unused parser/queue API:** `parser_grd.{get_nodes_array,get_elements_array,to_geographic,clear_cache}`, `parser_str.get_param_info`, `auth_service.{get_user,deactivate_user}`, `JobQueue.set_progress_callback` (superseded by `add/remove_progress_callback`), `LocalJobQueue.running_job_count`, `CeleryJobQueue.{health_check,worker_info}`.

## P6 — Minor / low-confidence
- **`_active_nav` JS signal** (`app.py:529`) — `Shiny.setInputValue('_active_nav', …)` fires on every nav, but no server reads it. Harmless dead client→server signal.
- **Write-only DB columns** (medium/low — likely intended for future display; don't drop without product intent): `Grid.{num_layers,min_depth,max_depth}`, `Simulation.{time_step,start_time,end_time}` — populated only on project import, never read back as attributes.

---

## What's healthy (verified, not findings)
- **Nav:** all 15 page panels ↔ sidebar entries map 1:1; nothing unreachable, no dangling nav.
- **Reactive wiring:** across all 15 pages, only the 2 P2 controls are orphaned. Every other `ui.input_*`/`ui.output_*` has a server counterpart; dynamic handler-factory patterns (per-row/per-project f-string ids) are structurally symmetric.
- **JS ↔ server:** `current_user_role`, `_wsauth`, `_dark_mode` all have readers; custom message handlers (`shyfem_nav`, `download_file`) all have senders. No phantoms.
- **Models:** all 13 ORM classes are used. Middleware: 5 of 6 mounted (the 6th is the dead `BasicAuthMiddleware`).

## Suggested order if/when fixes are authorized
1. **P1 cleanup tasks** (real unbounded-growth bug; the job-cleanup fix is already in, just needs invoking).
2. **P2 dead controls** (visible broken UX — wire or remove).
3. **P4 config knobs** (delete or honor — misleading as-is).
4. **P5 dead-code removal** (BasicAuthMiddleware, job_status widget, import_project_zip, celery_task_id) — reduces surface.
5. **P3** — product decision on whether to surface run_shyplot / cancel_workflow / lgr time-filter.
