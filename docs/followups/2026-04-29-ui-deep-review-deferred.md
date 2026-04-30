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
