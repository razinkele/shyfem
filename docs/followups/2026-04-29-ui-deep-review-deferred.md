# Follow-up: Deferred UI Deep-Review Findings

**Origin:** 2026-04-29 deep review of `shyfem-ui/`. The 22-task hardening plan
(`docs/superpowers/plans/2026-04-29-ui-hardening-followups.md`) closes
the highest-leverage gaps. This doc tracks items that need their own plan,
their own session, or an explicit "do not fix" decision.

---

## A. Tests for the 5 large untested pages (HIGH)

**Modules without unit tests:** `pages/run.py` (1417 LOC), `simulation.py` (1389),
`grid_prep.py` (1021), `partitioning.py` (433), `postprocess.py` (1195).
~4,700 LOC combined, exercised only via Playwright.

**Why deferred:** Each page mixes UI wiring with business logic — testing
without first extracting the pure functions would mock too much of Shiny.
The right path is: per page, identify the 3–5 extractable pure helpers
(validators, builders, parsers), move them to a service-layer module,
and unit-test the service layer.

**Suggested next step:** One plan per page, scoped as "extract pure helpers
from `pages/X.py` into `services/X_logic.py` + add unit tests."

---

## B. File-picker integration across pages (MED)

**Problem:** Every page uses `ui.input_text(..., placeholder="/path/to/...")`
for file paths. The `files.py` browser exists but is never wired as a picker
from other pages.

**Pages affected:** `partitioning.py:28-35`, `grid_prep.py:265`,
`postprocess.py:128`, `physics.py:228`, `simulation.py:29`, `run.py:173`,
`ibm.py:162`.

**Why deferred:** Requires a shared "file picker modal" component
(`components/file_picker.py` exists but is not used by any page). The
redesign affects 7+ pages and needs a UX pass. Scope as its own plan.

---

## C. Direct DB access in pages (MED)

**Problem:** `home.py` (6 sites), `admin.py`, `files.py` open `db_session()`
inline rather than going through services. Mixed pattern: `run.py` routes
through `access_control` and `file_service`.

**Why deferred:** Would touch 3 large pages and require new service methods.
Scope as a refactor plan.

---

## D. God modules (LOW; technical debt)

**Modules > 1400 LOC:** `physics.py` (1764), `visualize.py` (1630),
`mesh_builder.py` service (1421+) + page (1442+), `simulation.py` (1389),
`run.py` (1417).

**Why deferred:** Each is a candidate for being split into 3–4 focused
modules. Doing so requires careful API boundary design and is a significant
risk for low immediate value. Address incrementally as parts of these
modules are touched for other reasons.

---

## E. Service-layer naming consistency (LOW)

**Problem:** `services/` has `_service.py`, `_wrapper.py`, `_loader.py`,
`_utils.py`, `_builder.py`, plus bare `workflow.py`/`report.py`. Suffixes
have no architectural meaning.

**Why deferred:** Pure rename; high blast radius (every import site updates),
zero behavior change. Defer until a major-version cleanup is planned.

---

## F. Metrics / request IDs / tracing (LOW)

**Problem:** Beyond `/health`, the app has no per-request observability.
No timing histograms, no request-correlation IDs, no per-endpoint counters.

**Why deferred:** Requires architectural decisions (Prometheus vs OTel,
sync vs async middleware, per-route timing). Standalone proposal needed.

---

## G. Postprocess flux/frequency domain UI (LOW)

**Problem:** `postprocess.py:69-76` lists `frequency` and `flux` operations
that map to bare CLI flags but provide no domain controls (node lists for
flux sections, frequency bin counts).

**Why deferred:** Requires SHYFEM-domain expertise on what controls users
need. Pair with a SHYFEM developer to scope.

---

## H. Behavioral access-control coverage via Playwright (MED)

**Problem:** Task 8's static AST check verifies each write handler *contains*
a call to `check_project_access`, but cannot verify the call is positioned
*before* the mutation, nor that the resulting refusal actually prevents
the side-effect at runtime.

**Why deferred:** True behavioral coverage requires logging in as a
non-editor user via Playwright, navigating to each of the 9 pages, attempting
the write action, and asserting the mutation did not occur (file unchanged,
job not submitted, etc.). This is 9 e2e tests — substantial work, best
batched after Task 8 lands and a single representative page (e.g. simulation)
is verified manually first.

---

## I. "Validate Partitions" depth (LOW)

**Problem:** `partitioning.py:262-280` only checks file sizes; doesn't verify
element counts vs original mesh, orphaned nodes, or empty partitions.

**Why deferred:** Requires parsing `.par` files end-to-end and cross-referencing
with the original `.grd`. Scope as a small plan once the partition-method
fix in Task 16 has soaked in production.

---

## J. End-to-end Celery worker test (MED)

**Problem:** Phase B Task 7 added DB persistence + notifications to
`CeleryJobQueue`, but the tests only verify kwarg propagation and the
helper functions in isolation. The end-to-end path through
`execute_shyfem_job`'s `finally` block (which fires both helpers) is
not exercised by any test in the suite.

**Why deferred:** Requires either eager Celery mode or a test fixture
that stages the full task lifecycle. Both are non-trivial. Scope alongside
the multi-process Celery worker_init signal wiring (Task 7's design note).

---

## K. Multi-process Celery worker bootstrapping (MED)

**Problem:** Phase B Task 7's design uses module-level globals
(`_queue_session_factory`, `_queue_notification_service`) for the Celery
task body to find its session/notification handles. This works in
single-process / embedded-worker mode (laguna.ku.lt today). In a true
multi-process Celery deployment, the worker process never sees the
globals being set when the queue is constructed in the app server.

**Why deferred:** No production deployment uses multi-process Celery
today. When it does, the right fix is `celery.signals.worker_init` to
re-bootstrap globals from config in the worker process. Track here so
the limitation isn't silently inherited.

## L. Output-directory picker (DEFERRED 2026-05-08, LOW)

**Source:** Section B pilot (partitioning file-picker integration, 2026-05-01).

The pilot wires file pickers for INPUT files (`.bas`, `.grd`) but not for
the OUTPUT directory (`output_dir` text input on partitioning, grid_prep,
postprocess pages). Output picking is a different abstraction — directory
picker, not file picker — and was deferred from the pilot.

**Status (2026-05-08):** A design pass was completed
(`docs/superpowers/specs/2026-05-08-section-l-directory-picker-design.md`)
proposing a parallel `components/directory_picker.py` module with `+ Create`
modal. An 8-agent review found ~50 issues (11 critical) AND a strategic
challenge from the independent reviewer: the followups doc itself rates
Section L as **LOW priority**, no user complaints, the fallback at use-time
(`output_dir = input.output_dir() or str(<input_file>.parent)`) handles the
empty case unchanged, and the Pattern Drift Audit on 2026-05-11 has higher
concrete value. **Deferred** with trigger conditions and pre-pickup actions
below. Same playbook as Section M.1.

**Trigger conditions for picking up Section L:**
- Concrete user complaint about the copy-paste-the-absolute-path workflow
  on partitioning, grid_prep, or postprocess; OR
- Next non-trivial change to one of the 3 pages' output-flow that needs
  to interact with the picker (e.g., per-page output-format selectors); OR
- A second deferred picker abstraction (e.g., remote-file picker) is also
  picked up — at that point address Section L + the picker module's name
  drift (see action 3 below) together.

**Pre-pickup actions (do these first when Section L is reactivated):**

1. **Re-design with `active_project` directly, not `project_id`.** Three
   reviewers (type-design + bug-focused + test analyzer) converged on
   passing `active_project: reactive.Value[ProjectContext | None] | None`
   into `directory_picker_server` instead of `project_id`. Pages already
   maintain `active_project` from Section M; threading it directly
   eliminates the per-refresh DB query AND eliminates the `load_project_context(pid)`
   access-control bypass entirely (server-mode security gap, 95% confidence
   from the bug-focused reviewer).

2. **Add containment guard at mkdir time.** The `+ Create` flow's
   `(Path(wd) / name).mkdir(...)` doesn't re-run the `resolve_picker_path`
   containment guard. If `wd/runs` is a pre-existing symlink to `/etc`,
   `name="runs/passwd"` writes outside work_dir even though every individual
   path component looks safe. Mirror `resolve_picker_path`'s
   `is_relative_to(root)` check on the resolved path BEFORE `mkdir`.

3. **Decide on `file_picker.py` rename.** Once Section L lands, the file
   `components/file_picker.py` houses BOTH file-specific UI/server AND the
   shared helpers (`resolve_picker_path`, `fill_picker_input`, `PickerTargetId`)
   used by both pickers. The filename becomes a misnomer. Independent
   reviewer recommends rename to `picker_helpers.py` OR splitting helpers
   into a separate module. Decide and commit before adding the second picker.

4. **Switch to `Path.walk(follow_symlinks=False)` (3.12+) or `os.walk(followlinks=False)`.**
   The original spec used `Path.rglob("*")` which follows symlinks by
   default — both data-leakage risk (foreign tree pushes real subdirs past
   the cap) and infinite-loop risk (symlink loops on non-POSIX FS hang the
   reactive effect; bare except doesn't catch `RuntimeError`).

5. **Re-read the 2026-05-08 spec's review findings** (8 reviewer reports;
   summary in this doc + memory `feedback_subagent_driven_dev.md`). Notable
   defects to fix in any new spec: missing `import logging`; modal `footer=`
   slot pattern violation (codebase canonical at `admin.py:370-383`); `# Refresh
   + select` comment factually wrong about reactive causality; cap truncation
   silent (deferred indicator unshippable per multiple reviewers); 5 distinct
   `list_project_directories` failure modes collapse to `[]` (return tagged
   status instead); validator missing null-byte / backslash / length checks;
   modal `input_text` no `maxlength=255`; project-switch race during Create
   modal submit; tests for project-switch refresh / mkdir failure branches
   / `on_selected` fires on mkdir / symlink-loop all missing; test file
   naming should be `test_<page>_directory_picker.py` (not `_dir_picker.py`)
   for symmetry with Section M's `_file_picker.py` siblings.

6. **Reconsider whether the `+ Create` flow belongs in the picker at all.**
   The picker shifts from "read-only selector" to "filesystem mutator" with
   the Create modal. Independent reviewer suggests evaluating whether
   `directory_create_button` should be a separate component wired into
   the same row, so the picker stays read-only and the create flow is
   independently testable.

**Tracked but not scheduled.** Spec at
`docs/superpowers/specs/2026-05-08-section-l-directory-picker-design.md`
remains in the repo as design-history, marked DEFERRED with reasoning.

## Section M — File-picker rollout to remaining 6 pages — COMPLETE 2026-05-05

**Original problem:** 6 pages (`grid_prep`, `postprocess`, `physics`,
`simulation`, `run`, `ibm`) had free-text path inputs not wired to
FileService. Duplicating the partitioning pilot's wrapper across pages
would have caused user-visible string drift.

**Shipped:** 2026-05-05, branch `feat/section-m-file-picker-rollout`,
commits `ff3e6a1` (lagrangian taxonomy) → `54e1480` (ibm picker). The
file-picker pattern is now live on all 7 pages: partitioning (pilot),
grid_prep, postprocess, physics, simulation, run, ibm.

**Helper extraction:** `fill_picker_input(target_id: PickerTargetId,
project: ProjectContext | None, rel_path: str)` in
`components/file_picker.py` owns the resolve+log+notify+update_text
branching. All 7 pages delegate via lambdas that unwrap the active
project (`active_project.get() if active_project else None`) before
calling.

**Taxonomy addition:** `.lgr → "lagrangian"` added to FileService
(`_infer_file_type`); legacy rows backfilled by Alembic migration
`379248193d58_lagrangian_file_type_for_lgr`.

**Pattern adoption per page:** `_on_project_changed` effects get
`reactive.isolate()` + empty-guard. `_on_tutorial_context` effects
get `reactive.isolate()` only (no empty-guard — tutorial nav is
intentional override). Pages with project-tied directory prefills
(`postprocess.shy_path` ← `work_dir`, `run.working_dir` ← `work_dir`)
also get a `last_project_id` change-detector that forces re-fill on
ACTUAL project switch (A → B), but preserves user input on metadata
refresh and on first project load (None → A). `physics.py` had no
prior `_on_project_changed`; one was added as part of the rollout.

**Test coverage shipped:**
- 5 helper-level unit tests for `fill_picker_input` branches
  (success / no-project / empty-rel_path / traversal-warning /
  target_id-in-log).
- 2 unit tests per page (UI render + import-style/wiring guard) ×
  6 pages = 12 new unit tests.
- 4 Playwright tests per page (placeholder / isolate-regression /
  empty-guard / traversal-warning) for `grid_prep`, `postprocess`,
  `physics`, `simulation`, `ibm` = 20 tests; 2 Playwright tests for
  `run.py` (placeholder + traversal — fewer because the stub server
  doesn't replicate auto-fill semantics).
- Pilot's 5 partitioning Playwright tests still pass after the
  helper-extraction refactor (no behavioural regression).

**Test infrastructure additions:**
- `tests/_test_helpers.py:get_server_source` — closure-unwrap helper
  for `@module.server`-decorated functions. Required because
  `inspect.getsource` on the decorated name returns the wrapper, not
  the inner body. Used by all 6 per-page wiring assertions.
- All Playwright classes now use an autouse `_reset_active_project`
  fixture so test order is no longer load-bearing across files
  (`pw_page` is session-scoped).

**Outstanding gaps:**
- Section M.1 — `run_server`'s reactive-effect deadlock blocks
  end-to-end test mounting. Picker coverage works around this via
  `_stub_run_server` extension; the underlying deadlock remains
  unresolved. **DEFERRED 2026-05-06** after design + 8-agent review
  found ~30 issues plus a strategic "no consumer waiting" challenge.
  See the M.1 entry below for trigger conditions and pre-pickup steps.
- ~~Section M.2 — `pages/ibm.py` retains a glob fallback for `.lgr`
  files outside the FileService index. Picker dropdown and the glob
  can disagree on which file is shown; provenance is unobservable.~~
  **CLOSED 2026-05-06 (commit `2660bcf`):** glob-fill branch now emits
  a `logger.info` naming the file path so log consumers can distinguish
  picker-click provenance from glob-fallback provenance. Glob retained
  to preserve auto-discovery of mid-run-generated `.lgr` files; the log
  closes the observability gap. Pinned by `TestGlobFallbackProvenance`
  in `test_ibm_file_picker.py`.

**Section L (output-directory picker) remains deferred** — different
abstraction (directory picker, not file picker). Tracked separately.

## Section M.1 — run.py reactive-effect deadlock (DEFERRED 2026-05-06)

**Source:** Section M file-picker rollout (2026-05-04 → 2026-05-05).

`run_server` cannot be mounted in the test app due to event-loop
deadlocks in its reactive effects (job-queue + tutorial-context
interplay). The Section M rollout works around this for picker
coverage by extending `_stub_run_server` to mount the picker without
the deadlocking effects (`_test_app.py:48-146`).

**Open work:** the underlying deadlock means run_server cannot be
exercised end-to-end in tests at all. Picker coverage is workable but
fragile: any future picker-adjacent change to run_server must also
update the stub, or stub drift silently breaks Playwright coverage.

**Status (2026-05-06):** A design pass was completed
(`docs/superpowers/specs/2026-05-06-section-m1-run-server-job-poller-di-design.md`)
proposing a DI seam on `_auto_refresh`'s polling body. An 8-agent
review found ~30 concrete issues PLUS a strategic "no consumer
waiting, stub is stable, cost-benefit doesn't justify shipping
preventive maintenance now" challenge. **Deferred** with the trigger
conditions and pre-pickup actions below.

**Trigger conditions for picking up M.1:**
- Next non-trivial change to `run_server`'s reactive surface (esp.
  `_auto_refresh`, `_refresh_jobs`, `_refresh_log`, `_on_tutorial_context`,
  any new polling effect) needs end-to-end test coverage that the stub
  can't provide; OR
- Observable drift bug — a Section M-style picker rollout shows the
  stub diverged from the real `run_server` and the divergence wasn't
  caught in review; OR
- A future contributor needs to refactor `run_server`'s polling cadence
  (e.g., make the 2s interval configurable, or replace polling with
  push notifications) — at that point the test seam pays for itself.

**Pre-pickup actions (do these first when M.1 is reactivated):**

1. **Phase 0 — confirm the deadlock-causer hypothesis.** The 2026-05-06
   spec ASSUMED `_auto_refresh` is the deadlock-causer. The stub omits
   ALL ~20 effects, so the existing evidence supports "*one or more of
   them deadlocks*", not the specific identity. Cheap experiment
   (~30 min): in a throwaway branch, modify `_stub_run_server` to add
   ONE more thing at a time (event-gated handlers first since they're
   idle by construction; then `_on_tutorial_context`; then
   `_auto_refresh` last). If everything except `_auto_refresh` mounts
   cleanly, the hypothesis is confirmed and proceed with that design.
   If something else also deadlocks, the M.1 design is materially
   wrong and needs re-architecture.

2. **Reconsider the design alternative.** The 2026-05-06 spec proposed
   a 7-arg factory closure injecting an async callable. An independent
   reviewer suggested `polling_enabled: reactive.value(True)` —
   single-boolean DI-lite, 1 closure capture, much less surface to
   test. Compare both before committing.

3. **Re-read the 2026-05-06 spec's review findings** (8 reviewer
   reports). Notable defects to fix in any new spec: construction-order
   bug (workflow_engine/active_workflow_id/_refresh_tick at lines
   1139-1141, NOT 491/539); tests fail to execute due to missing
   reactive context (use `reactive.isolate()` or mock); factory belongs
   in `services/run_logic.py` not `pages/run.py`; `from collections.abc`
   not `from typing`; `asyncio_mode="auto"` means `async def` tests, not
   `asyncio.run()`; `tests/test_run_helpers.py` already exists (extend,
   don't create); silent-swallow `try/except + logger.debug` should
   become `warning` minimum; missing DI-seam test, multi-cycle test,
   workflow-engine sub-branch tests, production smoke test for
   `job_queue.list_jobs(limit=50, ...)` call shape; comment rot
   ("today's _auto_refresh body", "See Section M.1 design").

**Tracked but not scheduled.** Spec at
`docs/superpowers/specs/2026-05-06-section-m1-run-server-job-poller-di-design.md`
remains in the repo as design-history, marked DEFERRED with reasoning.

