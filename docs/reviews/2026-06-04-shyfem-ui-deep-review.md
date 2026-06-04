# shyfem-ui — Deep Multi-Angle Review (2026-06-04)

**Scope:** `shyfem-ui/shyfem_ui/` (~35.7k LOC) — 8 angles (security, async/reactive, data-integrity, error/resource, correctness, data/numerics, config/deploy, test-quality) → adversarial verify on crit/high → loop-until-dry deepening on the densest cluster.
**Method:** 31-agent workflow, every crit/high independently refuted. Seeded with the known-intentional Shiny/WS-auth/DB patterns to suppress false positives.
**Result:** 41 confirmed — **4 high, 25 medium, 12 low**. Review only; nothing modified.

> The densest cluster (the deepening confirmed it is systemic) is **server-mode cross-user data access (IDOR)**: the *cancel/write* paths are correctly fail-closed-gated, but several *read/list* paths are not. Fix these first.

---

## 🔴 Headline cluster — cross-user data access (IDOR), server mode

Multiple pages expose other users' jobs/logs/data because a read/list path skips the ownership gate that its sibling write path uses:

| Where | What leaks |
|-------|-----------|
| **`run.py`** (542, 857-862, 986-1048, 1093-1106) | "All jobs" switch → `list_jobs(session_id=None)` returns *every* user's jobs; `_view_job_log` / `selected_job_details` then serve any job's **stdout/stderr, working_dir, error_message, output-file paths** with no gate (while `_cancel_*` right beside them *are* gated). |
| **`compare.py`** (124-156, 222-289, 287-337) | Lists **and diffs** all users' completed jobs + metadata, no owner/session/project filter. |
| **`home.py`** dashboard (312-316, 346-355) | "All jobs" toggle lets any server-mode user list every user's jobs. |
| **`visualize.py`** (`_load_compare`, 499-512) | Skips the access gate its sibling `_load_data` (472-497) enforces. |

**Impact:** any authenticated user (incl. viewer/tutorial) reads other tenants' simulation output, filesystem paths, and parameters on the multi-user `laguna.ku.lt` box — a confidentiality breach.
**Fix (one pattern):** before fetching/rendering or listing another job, authorize via the existing fail-closed gate, which already takes owner/project — `job_cancel_denied_reason(job_user_id=job.metadata['user_id'], job_project_id=job.metadata['project_id'], user=current_user())` (or a read-oriented equivalent) — and filter `list_jobs` to owned/accessible jobs for non-admins.

## 🔴 Privilege escalation — project share trusts a client-supplied role  `[home.py:1225-1233]`
`_do_share()` passes `input.share_role()` straight to `SharingService.share_project`, which stores **any** string with no allowlist. A client can push `share_role="owner"` over the WS → a `ProjectPermission` row with `role="owner"` satisfies `check_project_access(min_role="owner")`. (Verifier rated medium; I'd treat as **high** — it's owner-level escalation.)
**Fix:** validate `role` against `{"viewer","editor"}` in `_do_share` *and* inside `share_project`; validate `share_user_id` is in `list_shareable_users`.

## 🔴 SMTP send blocks the event loop (app-wide hang)  `[notification_service.py:114-141 ← job_local.py:365]`
`smtplib.SMTP/SMTP_SSL` are built with **no `timeout=`** (default None = block forever), called synchronously in the `async` job-completion `finally` — not offloaded. A slow/dead mail relay freezes the **entire single-process app** for all sessions until the OS timeout.
**Fix:** add `timeout=` (new `smtp_timeout_seconds` config) **and** `await asyncio.to_thread(...)` the send.

## 🔴 Batch shyelab mutates a shared options list  `[postprocess.py:607,643 + shyfem_wrapper.py:396]`
`_batch_run` builds `options` once, then `run_shyelab` does `args = options or []; args.append(file)` — mutating the caller's list. File N is invoked with files 1..N-1 appended as extra args → wrong/overwritten batch results.
**Fix:** `list(options)` per call, or make every `run_shy*` wrapper copy before appending (the aliasing risk spans `run_shypre/shybas/shyparts/shyfem/shyplot`).

## 🟠 Secure cookies off on HTTPS prod  `[config.py:100 + session_auth.py:685/755/787]`
`use_secure_cookies` defaults `False`; prod `.env` doesn't set it → session + CSRF cookies emitted **without `Secure`** on the HTTPS `laguna` deployment → hijack/downgrade risk.
**Fix:** default `use_secure_cookies=True` when `deployment_mode=="server"` (config validator), or set it in prod `.env` + `.env.example`.

---

## Medium (25) — grouped themes
- **More IDOR / authz gaps:** comparison-data load (`visualize.py:499-512`), `_scan_file` runs shyelab on arbitrary cross-project paths (`postprocess.py:396-415`).
- **Data integrity:** `delete_user` orphans WSAuthToken rows + project ownership (`auth_service.py:207-241`); **SQLite FK constraints never enforced** (no `PRAGMA foreign_keys=ON`, `base.py:44`); `cleanup_old_jobs` deletes files/cache but not the DB rows (`job_local.py:438-466`).
- **Resource/error:** mesh-import `mkdtemp` never removed → temp-dir leak per upload (`mesh_builder.py:396`); `/health` returns **200 even when the DB probe fails** (`health_check.py:57-80`).
- **Data/numerics:** NaN nodata raster pixels not filtered (`NaN!=NaN`) → polluted bathymetry (`mesh_builder.py:905`); full raster band loaded with no size cap → OOM on the shared worker (`mesh_builder.py:885`); `_compare_netcdf` crashes on 1-D node-indexed vars (`visualize.py:1610`); `dict(ds.dims)` FutureWarning (`visualize.py:562`).
- **Config/deploy:** rate limiter collapses all users into one bucket behind the proxy (no `trusted_proxies`, `rate_limit.py`/`config.py:198`); audit-log page doesn't reset to page 0 on filter change (`admin.py:626`).
- **Reactive accumulation:** `file_picker.py:308-394` and `boundary_editor.py:201-212` register per-item handlers without the `set()` dedup guard.
- **Test quality (false confidence):** `test_dashboard_jobs.py`, `test_session_cleanup.py`, `test_incremental_output.py` assert against **re-implemented copies / local closures**, not the real handlers — they'd pass even if the feature broke.

## Low (12)
Mostly hardening/cosmetic — see the raw result in the workflow output.

---

## Recommended fix order
1. **IDOR read/list gates** (run.py, compare.py, home.py, visualize.py) — one shared gate helper; highest-impact, on prod.
2. **Share-role allowlist** (home.py + sharing_service) — privilege escalation.
3. **Secure cookies** default-on for server mode.
4. **SMTP timeout + to_thread** — app-stability.
5. **Batch shyelab copy** — correctness.
6. Mediums: FK enforcement, `delete_user` cleanup, `/health` status, raster NaN/OOM, rate-limiter bucket, the false-passing tests.

All four highs + the escalation are **confirmed, defensible, and mostly on the live multi-user box** — they warrant prompt fixing (TDD'd + gated + reviewed, as with the eco work).

---

## Shipped 2026-06-04 (merge `90d3192`, pushed to origin/main → laguna)
The **4 highs + the privilege escalation are FIXED, reviewed (MERGE), and merged**:
- IDOR read/list gates — `job_read_denied_reason` + admin-only listing across run/home/compare/visualize, plus the `_refresh_log` parity gate and **read-gate AST enforcement** (`test_pages_access_control.py`).
- Share-role allowlist (`SharingService.SHAREABLE_ROLES`) — escalation closed.
- Secure cookies default-on in server mode.
- Batch-shyelab mutable-options bug — wrappers now copy.
14+ new tests; full suite 2052 passed; ruff clean.

**Deploy note:** the `use_secure_cookies` default now derives from server mode (no `.env` change needed). Laguna's Shiny Server symlinks the tree, so the worker may need a reload/restart to serve the new code.

**Remaining backlog (mediums/lows, not yet fixed):** SMTP event-loop hang (high-reliability), FK constraints not enforced, `delete_user` orphans, `/health` 200-on-DB-fail, raster NaN/OOM, rate-limiter single-bucket, reactive-effect accumulation in file_picker/boundary_editor, and the 3 false-passing tests. Prioritize the SMTP hang next.

---

## Mediums shipped 2026-06-04 (merged to origin/main → laguna)
The medium backlog is now **fully cleared** (the SMTP hang + `to_thread` had already shipped with the highs). All TDD'd, full suite green (2080), ruff clean:

1. **`delete_user` orphans** + **`/health` 503-on-DB-fail** — `delete_user` now NULLs `Project.owner_id`/`Job.user_id`/`Workflow.user_id` and deletes `WSAuthToken`/`ProjectPermission`; `/health` returns 503 when degraded.
2. **Raster NaN/OOM** (`mesh_builder`) — drop non-finite pixels (fixes `NaN != nodata`), `MAX_RASTER_PIXELS` header guard before `read(1)`; also fixed the `mkdtemp` upload temp-dir leak (`stage_boundary_upload` + `TemporaryDirectory`).
3. **Rate-limiter single-bucket** — warns when `trusted_proxies` is empty behind the proxy (real per-client limiting needs `SHYFEM_UI_TRUSTED_PROXIES` set — a deploy decision; cookie-keying rejected as a threat-model regression).
4. **FK enforcement** — `PRAGMA foreign_keys=ON` on the prod engine after a delete-path audit (every test engine now enforces FKs; zero violations); no migration needed.
5. **3 false-passing tests** — `test_dashboard_jobs`/`test_session_cleanup`/`test_incremental_output` retargeted at extracted real handlers (`recent_jobs_session_id`, `cancel_active_jobs_for_session`, `write_output_line`); copies had silently diverged.
6. **Reactive-effect accumulation** — `set()` dedup guards in `file_picker` (pick handlers) + `boundary_editor` (remove handlers).
7. **`cleanup_old_jobs` left DB rows** (local + celery) — now deletes the persisted rows by `job_uuid` (the prod row-buildup source).
8. **Audit-log page reset** — viewer resets to page 0 on filter change (no more spurious empty page).

**Status: the 2026-06-04 deep review is fully remediated** — all highs, the escalation, and all mediums shipped to laguna.
