# Batch 3: UI Job Lifecycle & Data Integrity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax. This batch is Python WITH a test suite — TDD is mandatory: every task writes its failing test(s) first, and its report carries RED and GREEN evidence.

**Goal:** Fix the 17 Batch-3 items: N12 (init_db Alembic dead code), N13 (WS disconnect auto-cancels jobs), N14 (cancel never kills the subprocess), N40 (output_files never persisted), N41 (boundary-editor reactive mutate), N42 (restart selection never applied), N46 (phantom RUNNING rows), N47 (export/import blocks event loop), N48 (output discovery globs everything), F17 (list by session_id), F22 (remaining sync persists), F24 (FK cascade), F25 (CWD-relative database_url), F48 (timeseries blank line), F49 (run_shyfem mutates options), F50 (GRD silent drops), F51 (sync history load).

**Tech stack:** Python 3.13 (`/opt/micromamba/envs/shiny/bin/python`), Shiny for Python, SQLAlchemy+Alembic (SQLite), pytest. Run tests: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q` (Playwright excluded by default). Lint: `ruff check shyfem_ui tests && black --check shyfem_ui tests` (same env bin).

## Global Constraints

- TDD per task: failing test first (RED pasted), minimal implementation, suite green (GREEN pasted). New behavior ⇒ regression test in the same commit.
- conftest pins a session-temp DATABASE_URL — never rely on or touch the real `shyfem-ui/shyfem_ui.db` (it is production's file; see F25 note in Task 8).
- Respect the repo's Shiny gotchas (from CLAUDE.md/memory): server-validated identity only (never client-pushed role signals); no synchronous `Shiny.setInputValue` at connect; reactive effects need dedup guards; `set()` must receive a NEW object for list reactivity.
- Never touch/stage `src/tools/shynetcdf/` (user WIP) or `testcases/examples/mar_menor/mm_hyd_conz.*` (Batch 1 fixtures).
- Branch `fix/b3-ui-jobs-data` off `fix/b2-build-truthfulness` (stacked: #40←#41←#42←this). One commit per task; ruff+black clean before each commit.
- Findings' full details (defect mechanics + failure scenarios) are in `docs/reviews/2026-07-18-full-codebase-deep-review.md` §2 — task briefs cite the IDs; read the finding's row before implementing.

---

### Task 0: Branch + baseline suite

- [ ] `cd /home/razinka/shyfem && git checkout -b fix/b3-ui-jobs-data`
- [ ] Baseline: run the full suite once; record pass count (expect ~2137 passing) + ruff/black clean. This is the regression floor for every later task.

### Task 1: N12 — init_db's Alembic branch is dead (wrong parents index)

**Files:** Modify `shyfem-ui/shyfem_ui/db/base.py:97`; Test `shyfem-ui/tests/test_db_init_alembic.py` (new)

The bug (verified): `ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"` — `parents[1]` is the `shyfem_ui` package dir; `alembic.ini` lives one level higher at `shyfem-ui/alembic.ini` (`parents[2]`). The `.exists()` check therefore always falls back to `create_all()`, so real installs are never migrated or stamped.

- [ ] **RED:** new test file with two tests (use a tmp_path SQLite URL + monkeypatched engine):
  1. `test_fresh_db_is_migrated_to_head` — call `init_db()` on an empty DB; assert `alembic_version` table exists AND its version equals the repo's head revision (read head via `alembic.script.ScriptDirectory.from_config`), and a known table (e.g. `feedbacks`) exists.
  2. `test_legacy_create_all_db_is_stamped` — pre-create tables via `Base.metadata.create_all`, then `init_db()`; assert `alembic_version` now exists at head and no table was dropped.
  Both must FAIL against the current code (they exercise the Alembic branch, which never runs — assert specifically that alembic_version exists, which create_all never makes).
- [ ] **GREEN:** change `parents[1]` → `parents[2]`. Nothing else.
- [ ] Full suite + lint; commit `fix(ui): resolve alembic.ini one level above the package so init_db really migrates (N12)`.

### Task 2: N14 + F49 — cancel must kill the child process; run_shyfem must not mutate the caller's list

**Files:** Modify `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py` (`run_command` ~150-230, `run_shyfem` ~365-366); Test `shyfem-ui/tests/test_wrapper_cancel.py` (new)

Mechanics (verified): jobs spawn via `asyncio.create_subprocess_exec` with no `start_new_session`, cancel goes through `task.cancel()` (job_local.py:385) and `CancelledError` propagates through `run_command` uncaught (only TimeoutError and generic Exception are handled) — the child keeps running.

- [ ] **RED:** test that (a) `run_command` spawned child leads its own process group (`os.getpgid(pid) == pid`); (b) cancelling the asyncio task running `run_command` (against a long-running `sleep`-style script registered as a fake tool) leaves NO live child within ~2s (`os.kill(pid, 0)` raises `ProcessLookupError`); (c) `run_shyfem(options=my_list)` leaves `my_list` unchanged.
- [ ] **GREEN:**
  - `create_subprocess_exec(..., start_new_session=True)`.
  - Wrap the drain/wait in `try/except asyncio.CancelledError/finally` such that on cancellation (and on the existing timeout path, refactored to share it) the child's process GROUP gets SIGTERM, a short grace (~1.5s), then SIGKILL, then `await proc.wait()`; re-raise CancelledError after cleanup. Use `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)` guarded for ProcessLookupError.
  - `run_shyfem`: `args_list = list(options) if options else []` (mirror run_shypre's fixed pattern).
- [ ] Full suite + lint; commit `fix(ui): cancelled jobs kill the spawned process group; run_shyfem copies options (N14, F49)`.

### Task 3: N13 + N46 + F17 — job ownership: no disconnect-cancel, reconcile phantoms, list by user

**Files:** Modify `shyfem-ui/shyfem_ui/services/job_queue.py` (`cancel_active_jobs_for_session` + its call sites — grep `cancel_active_jobs_for_session` across shyfem_ui/), `shyfem-ui/shyfem_ui/services/job_local.py` (`_load_history_from_db`), `shyfem-ui/shyfem_ui/pages/run.py:571-572`; Tests: extend `tests/test_job_queue*.py` / new `tests/test_job_reconciliation.py`

- [ ] **RED (three tests):**
  1. A running job survives a session-end event (call whatever hook currently invokes `cancel_active_jobs_for_session`; assert job still active).
  2. `_load_history_from_db` marks DB rows stuck in RUNNING/PENDING/QUEUED with no live process as FAILED with error `"orphaned at server restart"` (create such a row, instantiate the queue, assert status).
  3. Server-mode job listing filters by `user_id`, not `session_id` (two users' jobs; assert the requesting user sees only their own).
- [ ] **GREEN:**
  - N13: delete the disconnect→cancel coupling — remove `cancel_active_jobs_for_session` invocations at session teardown (keep the function only if a test/api still needs it; otherwise delete it and its imports). Jobs end by completing, explicit cancel, or reconciliation.
  - N46: in `_load_history_from_db`, any loaded row in an active status becomes FAILED/"orphaned at server restart" and is persisted back (no pid tracking needed: a fresh queue instance by definition has no live children of a previous process).
  - F17: `run.py` passes `user_id=<server-validated current user id>` (the page already resolves the authenticated user for its guards — reuse that source, never a client-pushed signal); `list_jobs` gains/uses a `user_id` filter in server mode; local mode unchanged.
- [ ] Full suite + lint; commit `fix(ui): jobs owned by users - no disconnect cancel, orphan reconciliation, per-user listing (N13, N46, F17)`.

### Task 4: N48 + N40 — output discovery by snapshot; persist output_files

**Files:** Modify `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py` (`run_command` + `_find_output_files`), `shyfem-ui/shyfem_ui/services/job_local.py` (`_persist_job` ~122, `_load_history_from_db` ~80); Tests: `tests/test_wrapper_outputs.py` (new) + extend persistence tests

- [ ] **RED:** (a) a pre-existing `.shy` file in the working dir with an old mtime is NOT reported; a file created during the run IS; a pre-existing file MODIFIED during the run IS. (b) round-trip: persist a job with `output_files=[...]`, reload history, assert the list survives (the `jobs.output_files` column exists via migration 7e41388e2c8d and is currently never written).
- [ ] **GREEN:** snapshot `{path: mtime}` for the tool's extensions before launch; after completion return files that are new or have `mtime > snapshot`. Persist `output_files` as JSON text in `_persist_job`; parse it in `_load_history_from_db` (tolerate NULL/invalid as `[]`).
- [ ] Full suite + lint; commit `fix(ui): job outputs = files the run actually produced, persisted across restarts (N48, N40)`.

### Task 5: F22 + F51 — async hygiene for persistence

**Files:** Modify `shyfem-ui/shyfem_ui/services/job_local.py`; Tests: extend existing job_local tests

- [ ] **RED:** grep-level lock test (AST or source scan, mirroring the repo's source-lock test style in `tests/test_dead_controls_wired.py`) asserting no bare synchronous `self._persist_job(` call remains on async paths (allowed: inside `asyncio.to_thread` or from sync-only contexts like `__init__` reconciliation), plus a functional test that `JobQueue` construction schedules/loads history without blocking the running loop (constructor completes < threshold with a slow-DB monkeypatch, or history loads lazily on first use — implementer picks the mechanism and asserts it).
- [ ] **GREEN:** wrap the remaining execution-path `_persist_job` call sites in `await asyncio.to_thread(...)` (commit d4cfa9a already did lines 280/286/367 — find the stragglers, incl. cancel/reconcile paths added in Tasks 3-4 if any); move `_load_history_from_db` off the constructor's sync path (`to_thread` at first-use or a background task at startup — keep reconciliation semantics from Task 3).
- [ ] Full suite + lint; commit `fix(ui): persistence and history load never block the event loop (F22, F51)`.

### Task 6: N47 — export/import off the event loop

**Files:** Modify `shyfem-ui/shyfem_ui/services/project_export.py` (`export_project`, `import_project` — and their page call sites found via grep); Tests: extend `tests/test_project_export.py`

- [ ] **RED:** test that the loop stays responsive during a large export: monkeypatch the zip work to sleep 0.5s, run export via its public async entry, assert a concurrently-scheduled coroutine ticks meanwhile (loop not blocked). Plus a size-cap test: export refuses (clear error) beyond `max_export_bytes` config (add field, sensible default e.g. 2 GiB).
- [ ] **GREEN:** make the public entries `async` wrappers running the existing sync bodies in `asyncio.to_thread`; enforce the size cap by pre-summing file sizes. Update call sites accordingly.
- [ ] Full suite + lint; commit `fix(ui): project export/import run in a worker thread with a size cap (N47)`.

### Task 7: N41 + N42 — boundary-editor reactivity; restart selection actually applied

**Files:** Modify `shyfem-ui/shyfem_ui/components/boundary_editor.py:198` area, `shyfem-ui/shyfem_ui/pages/run.py:678` area; Tests: extend component/page tests

- [ ] **RED:** (a) boundary editor: after Add/CSV-import, the reactive value's object identity CHANGES (the current code appends in place then `set()`s the same ref, so Shiny sees no change — assert `id(before) != id(after)` via the module's testable seam, or the rendered row count updates in the existing component-test harness). (b) run page: building the run config with a selected restart job produces an STR containing `restrt` pointing at the chosen restart file (currently only metadata records it; grep the generated STR text in the test).
- [ ] **GREEN:** (a) `set(list(current) + [new_row])` pattern (copy-on-write). (b) wire the selection into the STR generation path (`$name` section `restrt` param) — follow the finding N42 row for the exact gap; keep the tutorial write-guard intact.
- [ ] Full suite + lint; commit `fix(ui): boundary editor copy-on-write reactivity; restart selection wired into STR (N41, N42)`.

### Task 8: F24 + F25 — FK cascade migration; anchored database_url

**Files:** Modify `shyfem-ui/shyfem_ui/models/user.py` (ProjectPermission FKs) + new Alembic migration under `shyfem-ui/alembic/versions/`; `shyfem-ui/shyfem_ui/config.py:48-49`; Tests: extend `tests/test_db_fk.py` + config tests

- [ ] **RED:** (a) deleting a project with permissions succeeds and removes its permission rows (currently fails or orphans — assert cascade); same for user deletion. (b) config test: default `database_url` is ABSOLUTE (independent of CWD): instantiate config from a different CWD and assert the resolved path is the same `shyfem-ui/shyfem_ui.db` location.
- [ ] **GREEN:** (a) add `ondelete="CASCADE"` to both ProjectPermission FKs + an Alembic migration using `batch_alter_table` (SQLite requires table-rebuild for FK changes); chain it onto the current head. (b) default becomes `f"sqlite:///{(Path(__file__).resolve().parents[1] / 'shyfem_ui.db')}"` — **same physical file laguna prod already uses** (the app runs from the git tree there), so prod behavior is preserved while CWD sensitivity dies; env `SHYFEM_UI_DATABASE_URL`/`DATABASE_URL` still overrides. Do NOT make server mode hard-require the env var (laguna's worker may rely on the default).
- [ ] Full suite + lint (conftest's temp DATABASE_URL keeps tests off the real file); commit `fix(ui): permission FK cascade migration; CWD-independent database_url default (F24, F25)`.

### Task 9: F48 + F50 — parser honesty

**Files:** Modify `shyfem-ui/shyfem_ui/services/timeseries_loader.py:80-87`, `shyfem-ui/shyfem_ui/services/parser_grd.py` (the four `except ValueError: pass/break` sites ~342/400/411/438); Tests: extend `tests/test_timeseries_loader.py`, `tests/test_parser_grd.py`

- [ ] **RED:** (a) a timeseries file with a leading blank line then a header parses identically to the same file without the blank line. (b) a GRD file with a malformed optional field yields a parser WARNING (collected in the parser's existing warnings/issues channel — follow how other GRD warnings surface) instead of silence; parsing still succeeds.
- [ ] **GREEN:** (a) skip leading blank lines before header detection (index-independent). (b) replace silent `pass`/`break` with a warning record naming line number + field; keep tolerant behavior.
- [ ] Full suite + lint; commit `fix(ui): timeseries leading-blank header detection; GRD drops warn instead of silence (F48, F50)`.

### Task 10: Verification + roadmap tick + final reviews + PR

- [ ] Full suite (paste count vs Task 0 baseline: same+new tests), ruff+black clean.
- [ ] Tick Batch 3 in the roadmap checklist (` — DONE (commits <range>)`); commit.
- [ ] (Controller) final whole-branch review (most capable model) **plus a ui-security-reviewer agent pass** (repo's dedicated UI failure-mode reviewer); one fix subagent for combined findings if any.
- [ ] (Controller) push + `gh pr create --base fix/b2-build-truthfulness` with summary/test plan.

## Self-review notes

- Coverage: N12→T1, N14+F49→T2, N13+N46+F17→T3, N48+N40→T4, F22+F51→T5, N47→T6, N41+N42→T7, F24+F25→T8, F48+F50→T9. 17/17.
- Tasks 3, 6, 7 specify requirements + exact test obligations rather than final code (their surrounding code must be read in-task); Tasks 1, 2, 4, 8, 9 carry the exact mechanism. Every task's acceptance is its RED→GREEN evidence + full-suite pass — the per-task reviewer verifies tests are real (assert actual behavior, not mocks).
- F25 deliberately preserves laguna's physical DB path — flag any deviation to the controller instead of "improving" it.
