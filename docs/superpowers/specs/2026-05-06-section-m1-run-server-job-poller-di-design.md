# Section M.1 — `run_server` Job-Poller DI Design

**Origin:** Section M file-picker rollout (2026-05-04 → 2026-05-05) flagged
that `pages/run.py:run_server` cannot be mounted in `tests/_test_app.py`
due to event-loop deadlocks during initial flush. The Section M rollout
worked around this by mounting `_stub_run_server` (a parallel
implementation that omits the deadlocking effects). Section M.1 is the
underlying fix.

## Goal

Replace the `_stub_run_server` workaround with dependency injection on
the suspected deadlock-causing effect (`_auto_refresh`), so the real
`run_server` mounts in tests with a no-op poller. Every other reactive
effect, render output, and event handler in `run_server` then runs in
test coverage instead of being stubbed.

## Non-goals

- **No production behavior change.** When `job_poller` is `None`,
  `run_server` constructs the same poller body that exists today via a
  default factory. End users see no change.
- **No diagnosis of the precise deadlock cycle.** Whether it's a sync
  call inside an async wrapper, an `invalidate_later(2)` scheduling
  contention with the flush loop, or a Shiny-internal bug, we sidestep
  it rather than root-cause it. The symptom is contained.
- **No refactor of the other 19 `@reactive.effect` blocks** in
  `run_server`. If any of them ALSO deadlocks in tests after the swap,
  M.1 becomes "narrow further" — but we expect not, given the stub
  comment specifically calls out "polling/refresh effects" as the
  culprit.

## Context — what already exists

`shyfem-ui/shyfem_ui/pages/run.py:run_server` (lines 252–1370):
- Receives `input, output, session, config, job_queue, active_project,
  tutorial_context, user_role` (8 parameters today).
- Defines `_auto_refresh` at line 512: an async `@reactive.effect` that
  reads `active_jobs_data`, `active_workflow_id`, conditionally fires
  `reactive.invalidate_later(2)` to self-reschedule, and awaits
  `_refresh_jobs()` + `_refresh_log()`.
- `_refresh_jobs` (line 539) awaits `job_queue.list_jobs(limit=50, ...)`.
- `_refresh_log` (line 491) awaits `job_queue.get_output(job.id, ...)`.
- 19 OTHER `@reactive.effect` decorators handle user-triggered events
  (button clicks, project changes, tutorial nav). None self-reschedule;
  most are `@reactive.event(input.X)` gated.

`shyfem-ui/tests/_test_app.py:_stub_run_server` (lines 47–134):
- Decorated with `@module.server`, parameter list mirrors
  `run_server`'s with `tutorial_context` and `user_role` omitted.
- Initialises 5 reactive values (`active_jobs_data`, `all_jobs_data`,
  `selected_job_id`, `selected_job`, `log_content`) but never updates
  them after construction.
- Mounts the picker (`fp_input` → `fill_picker_input("input_file", ...)`)
  identical to `run_server`'s call.
- Renders 4 `@render.ui` placeholder outputs (dashboard, job_details,
  mpi-checkbox, etc.) that the page UI requires.
- Does NOT replicate `_auto_refresh`, `_refresh_log`, `_on_tutorial_context`,
  empty-guard semantics on `_on_project_changed`, or any of the
  user-triggered handlers.

The stub has been stable since 2026-02-13 (`9c75def`). It currently
absorbs all the test-side picker coverage that Section M ships.

## Architecture

**One change in `run_server`'s signature:** add an optional
`job_poller: JobPollerFn | None = None` kwarg.

```python
from typing import Awaitable, Callable

JobPollerFn = Callable[[], Awaitable[None]]
```

**One module-level factory** that constructs the production poller
closure given the reactive state it needs:

```python
def _make_default_job_poller(
    job_queue: "JobQueue",
    active_jobs_data: "reactive.Value[list[JobInfo]]",
    active_workflow_id: "reactive.Value[int | None]",
    workflow_engine: "WorkflowEngine",
    refresh_tick: "reactive.Value[int]",
    refresh_jobs_fn: Callable[[], Awaitable[None]],
    refresh_log_fn: Callable[[], Awaitable[None]],
) -> JobPollerFn:
    """Build the production async poller body.

    Returns a coroutine function that, when awaited inside a Shiny
    @reactive.effect, performs ONE poll cycle: reads state, conditionally
    schedules a 2s re-fire via reactive.invalidate_later, awaits the two
    refresh functions. Verbatim port of today's _auto_refresh body.
    """
    async def _poll() -> None:
        try:
            active = active_jobs_data.get()
            wf_id = active_workflow_id.get()
            wf_active = False
            if wf_id:
                wf = workflow_engine.get_workflow(wf_id)
                wf_active = wf.is_active if wf else False
            if active or wf_active:
                reactive.invalidate_later(2)
                refresh_tick.set(refresh_tick.get() + 1)
            await refresh_jobs_fn()
            await refresh_log_fn()
        except Exception:
            logger.debug("Auto-refresh poll failed, retrying in 5s", exc_info=True)
            reactive.invalidate_later(5)
    return _poll
```

**Inside `run_server`**, after `_refresh_jobs` and `_refresh_log` are
defined (currently lines 491, 539), construct the default poller if the
caller didn't inject one, and use it in `@reactive.effect`:

```python
def run_server(
    input, output, session,
    config: Config,
    job_queue: JobQueue = None,
    active_project=None,
    tutorial_context=None,
    user_role=None,
    job_poller: JobPollerFn | None = None,
) -> None:
    """Job execution page server logic.

    job_poller: optional async callable replacing the default per-cycle
        polling body. Defaults to None — when None, _make_default_job_poller
        constructs the production poller. Tests pass `lambda: None` (or
        a dedicated _noop_poller) to mount run_server without the
        deadlock-causing polling against job_queue.
    """
    # ... existing setup, reactive values, _refresh_jobs, _refresh_log ...

    if job_poller is None:
        job_poller = _make_default_job_poller(
            job_queue, active_jobs_data, active_workflow_id,
            workflow_engine, _refresh_tick, _refresh_jobs, _refresh_log,
        )

    @reactive.effect
    async def _auto_refresh():
        await job_poller()
```

The existing `_auto_refresh` body (lines 513–529) is moved verbatim
into `_make_default_job_poller`. The only NEW code in `run_server` is
the conditional construction + the one-line `await job_poller()` body.

## Test app change

`tests/_test_app.py`:

1. Delete `_stub_run_server` (lines 47–134, 88 LOC).
2. Add a module-level no-op poller:

```python
async def _noop_job_poller() -> None:
    """Test poller — does nothing. Replaces run_server's _auto_refresh
    body so the test app can mount the real run_server without the
    job_queue polling that deadlocks the asyncio event loop during
    initial flush. See Section M.1 design.
    """
    return
```

3. Replace the `_stub_run_server("run", ...)` call (line 275) with:

```python
run.run_server(
    "run", config, job_queue,
    active_project=active_project,
    tutorial_context=tutorial_context,
    user_role=None,
    job_poller=_noop_job_poller,
)
```

The picker server, render.ui placeholders, button handlers, and 19 other
reactive effects from the real `run_server` now run in tests instead of
being stubbed. The picker's behavioral contract (file_types, lambda
delegation, isolate-guard) is now exercised in the real production
function.

## Data flow

**Production (job_poller=None):**

```
run_server starts
  → _make_default_job_poller(...) returns _poll closure
  → @reactive.effect registers _auto_refresh, body awaits _poll()
  → _poll reads active_jobs_data.get(), maybe invalidate_later(2)
  → _poll awaits job_queue.list_jobs(limit=50, ...)
  → _poll awaits job_queue.get_output(job.id, ...)
  → effect completes, possibly re-fires in 2s
```

**Test (job_poller=_noop_job_poller):**

```
run_server starts
  → job_poller already non-None, skip default factory
  → @reactive.effect registers _auto_refresh, body awaits _noop_job_poller()
  → coroutine returns immediately
  → effect completes, no reschedule, no job_queue contact
```

The reactive scaffolding fires identically; only the body's side
effects differ.

## Risks and mitigations

- **Risk:** another reactive effect in `run_server` ALSO deadlocks in
  tests once the stub is removed. The stub omitted everything, so we
  don't know which others (if any) might. **Mitigation:** the
  full Playwright suite is the verification. If a new deadlock surfaces,
  identify which effect, extract it the same way, repeat. Worst case is
  iterative: M.1 might land in N rounds (N=1 expected). The default
  factory pattern means each round is non-breaking for production.

- **Risk:** the `tutorial_context` parameter is currently passed in
  `_test_app.py`'s real run_server call site for non-test code paths.
  Verify the test app's `tutorial_context` reactive is properly wired
  before run_server starts trying to dereference it. **Mitigation:**
  trivial inspection — `tutorial_context = reactive.value(None)` already
  exists in `_test_app.py:243`, same pattern as `active_project`.

- **Risk:** `user_role=None` might trigger access-control branches in
  `run_server` that the stub didn't exercise. **Mitigation:** look for
  `user_role()` checks in `run.py:run_server`. If access control gates
  important UI elements behind a non-None user role, the test app's
  no-role mount would fail differently than stub did. Verify by reading
  `run_server` lines 565–700 (submit handler region) for `user_role`
  references.

- **Risk:** silent regression — the stub omitted `_on_tutorial_context`
  empty-guard / isolate semantics. The Section M wiring tests for run.py
  asserted the behavior via source-inspection (no actual session test).
  Once the real run_server mounts, `_on_tutorial_context` runs in tests
  for the first time. If its empty-guard semantics diverge from
  Section M expectations, tests may fail in a new way.
  **Mitigation:** verify the existing test_playwright_run_picker.py
  tests still pass after the swap; if not, the real behavior tells us
  what the spec needs to say.

- **Risk:** `_make_default_job_poller`'s parameter list is long (7
  args). If the production poller's body grows to need more state,
  the factory signature grows in lockstep. **Mitigation:** acceptable —
  the alternative (bundle into a config dataclass) adds a layer of
  indirection without buying anything for the current scope. If the
  list grows past 10, revisit.

## Tests

### `tests/test_run_helpers.py` — NEW unit tests for the factory

5 tests, all sync (no Shiny session needed — the factory returns a
coroutine but we test the closure construction and one execution path
via mocks):

1. **test_make_default_job_poller_returns_async_callable** — call the
   factory with mocks, assert the return value is callable and
   `asyncio.iscoroutinefunction(...)` is True.

2. **test_poller_invalidates_later_when_active_jobs** — set
   `active_jobs_data.get()` to a non-empty list, mock
   `reactive.invalidate_later`, run the poller via
   `asyncio.run(poller())`, assert `invalidate_later` was called with
   `2`.

3. **test_poller_does_not_invalidate_later_when_idle** — empty
   active_jobs + None workflow_id, run the poller, assert
   `invalidate_later` was NOT called.

4. **test_poller_calls_refresh_jobs_and_log** — pass two AsyncMock
   functions as `refresh_jobs_fn` and `refresh_log_fn`; run the poller;
   assert both were awaited exactly once.

5. **test_poller_swallows_exceptions_with_5s_retry** — make
   `refresh_jobs_fn` raise; run the poller; assert no exception
   propagates AND `invalidate_later(5)` was called as the
   exception-path reschedule.

### Existing tests — updated, not new

- `tests/test_run_file_picker.py` (Section M) — its source-inspection
  assertions should pass unchanged (the lambda + isolate-guard pattern
  is preserved).
- `tests/test_playwright_run_picker.py` (Section M) — existing 2 tests
  (placeholder + traversal-warning) should pass unchanged. The
  conftest active_project reset fixture (commits `22a2288`, `9fb5654`,
  `2dddf51`, `2f212e6`, hardened during the post-Section-M Playwright
  verification cycle) handles cross-test pollution; the noop poller
  handles the deadlock side. Both must work together.

### What is NOT tested (acknowledged)

- The actual production poller body running end-to-end against a real
  job_queue. We don't have a Playwright fixture that creates a real
  job + waits for the polling to update the dashboard view. Out of
  scope for M.1 — closing the deadlock workaround is the goal, not
  adding new full-stack coverage.

## Files

- Modify: `shyfem-ui/shyfem_ui/pages/run.py` — extract
  `_make_default_job_poller` to module level (~30 LOC), add
  `job_poller` kwarg + conditional construction, replace
  `_auto_refresh` body with `await job_poller()`. Net add ~35 LOC, net
  remove ~15 LOC.
- Modify: `shyfem-ui/tests/_test_app.py` — delete `_stub_run_server`
  (lines 47–134, ~88 LOC), add `_noop_job_poller` (~5 LOC), replace
  the call site (line 275). Net remove ~80 LOC.
- Create: `shyfem-ui/tests/test_run_helpers.py` — 5 unit tests for the
  factory (~80 LOC).
- Modify: `docs/followups/2026-04-29-ui-deep-review-deferred.md` —
  mark Section M.1 CLOSED with the date + commit SHA.

## Verification

After implementation:

1. `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py -v` → 5 pass.
2. `pytest tests/test_run.py tests/test_run_logic.py tests/test_run_file_picker.py -v` → all pre-existing pass (no regression).
3. `pytest -q --ignore-glob='tests/test_playwright_*.py'` → ≥1900 pass + 5 new = ≥1905 pass.
4. `pytest tests/test_playwright_*.py -q --override-ini="addopts="` → 185 pass (no regression from the M.2 + Playwright fixture work).
5. Manual smoke: start app in local mode, navigate to Run, submit a job, watch the auto-refresh update the dashboard. Confirms production poller still works after the extraction.
6. `ruff check --select F401,I shyfem_ui/pages/run.py tests/_test_app.py tests/test_run_helpers.py` → clean.
7. `black --check shyfem_ui/pages/run.py` → clean.

## Lessons captured for the next session

- The deadlock root cause (whatever it is) remains unfixed. If anyone
  in the future wants the production poller to NOT use
  `reactive.invalidate_later(2)` self-rescheduling, the DI seam already
  exists — they swap the default factory.
- `_stub_run_server`-style parallel implementations are anti-patterns:
  they drift over time (Section M almost shipped a stub-vs-real
  divergence on picker wiring before catching it in review). Future
  test-mounting issues should reach for DI first; only fall back to a
  parallel stub if the test surface area is genuinely tiny.
