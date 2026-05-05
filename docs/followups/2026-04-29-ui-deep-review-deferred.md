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

## L. Output-directory picker (LOW)

**Source:** Section B pilot (partitioning file-picker integration, 2026-05-01).

The pilot wires file pickers for INPUT files (`.bas`, `.grd`) but not for
the OUTPUT directory (`output_dir` text input on partitioning, run, and
similar pages). Output picking is a different abstraction — directory
picker, not file picker — and was deferred from the pilot.

When designing this:
- The picker must list directories (not files) under `work_dir`, and
  optionally allow creating a new subdirectory.
- It should integrate via the same coexistence pattern (picker + text
  input) the file picker uses, so the migration cost matches.
- Consider whether to share infrastructure with `components/file_picker.py`
  (e.g. a `directory_picker_server` sibling) or build a separate component.

## M. File-picker rollout to remaining 6 pages (MED)

**Source:** Section B pilot (partitioning file-picker integration, 2026-05-01).

The pilot scopes only `pages/partitioning.py`. The remaining pages with
free-text path inputs are:

- `pages/grid_prep.py` (mesh import paths)
- `pages/postprocess.py` (input `.shy`/`.nc` files)
- `pages/physics.py` (forcing files)
- `pages/simulation.py` (STR file)
- `pages/run.py` (STR file)
- `pages/ibm.py` (Lagrangian config — `.lgr` may not map to a FileService
  category; check the taxonomy first)

Apply the same pattern as the pilot:
1. Add `file_picker_ui` above each text input.
2. Add `file_picker_server` with the appropriate `file_types` filter.
3. Add an `_fill_X` wrapper that calls `resolve_picker_path`, logs +
   notifies on resolution failure.

**Hard deadline (from spec lessons):** by the SECOND follow-up page,
extract the per-page `_fill_X` wrapper bodies into a shared helper
`fill_picker_input(text_input_id, active_project, rel_path)` in
`components/file_picker.py`. This prevents user-visible string drift
across pages.

Before each page is wired:
- Confirm the page's file inputs map cleanly to `FileService` file_types.
  `.lgr` for ibm.py may need a new taxonomy entry (`lagrangian` or
  similar).
- Audit `_on_project_changed` (or equivalent) for the same patterns
  fixed in the pilot: missing `reactive.isolate()` around input reads,
  missing empty-guards on auto-fill.

## Section M.1 — run.py reactive-effect deadlock (open)

**Source:** Section M file-picker rollout (2026-05-04 → 2026-05-05).

`run_server` cannot be mounted in the test app due to event-loop
deadlocks in its reactive effects (job-queue + tutorial-context
interplay). The Section M rollout works around this for picker
coverage by extending `_stub_run_server` to mount the picker without
the deadlocking effects (`_test_app.py:245`).

**Open work:** the underlying deadlock means run_server cannot be
exercised end-to-end in tests at all. Picker coverage is workable but
fragile: any future picker-adjacent change to run_server must also
update the stub, or stub drift silently breaks Playwright coverage.

**Resolution options:**
1. Refactor run_server to extract the deadlock-causing effects into a
   helper that the test can replace via dependency injection.
2. Identify the specific deadlocking interaction and break the cycle
   directly (likely the right fix; needs investigation).

Tracked but not scoped.

