# Deferred UI Issues — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the **11 actionable** deferred items from `docs/followups/2026-04-29-ui-deep-review-deferred.md` (A, C, D, E, F, G, H, I, J, K, plus the IBM-LGR P3 items). Items **L and M.1 remain DEFERRED** — their phases below are reference-only and MUST NOT be executed until a tracker trigger condition fires AND the user approves pickup (see the banner below).

> ⚠️ **DEFERRED-WORK BANNER — read before executing anything.**
> **Phase L** (output-directory picker) and **Phase M.1** (run.py job-poller DI seam) were each killed twice by 8-agent strategic reviews: *"no consumer waiting; cost-benefit doesn't justify shipping preventive maintenance now."* They are documented here for completeness only. An executing agent MUST treat their task checkboxes as inert. Do not write code for L or M.1 unless (a) a trigger condition in the tracker has fired and (b) the user has explicitly approved pickup. Each phase repeats this STOP gate inline.

**Architecture:** Every phase follows the codebase's established "Section A" pattern — extract pure logic into a `services/*_logic.py` (or `*_service.py`) module, re-export from the page for backward compat, and unit-test the service directly with plain pytest (no Shiny harness). Behavioral/integration coverage uses the existing two-server Playwright architecture. No phase changes the Fortran engine.

**Note on item B:** the tracker's item B (file-picker integration) is **already complete** — the Section M rollout (commits `ff3e6a1`→`54e1480`, 2026-05-05) wired the picker to all 7 pages and M.2 is CLOSED (`2660bcf`). It is intentionally not a phase here. The only residual sliver of B's original scope (the *output*-directory picker) lives as the deferred Phase L.

**Tech Stack:** Python 3.13, Shiny for Python, Starlette/ASGI, SQLAlchemy, Celery+Redis (optional), Playwright, pytest + pytest-asyncio.

**Conventions for every phase:**
- Run tests with `CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest` from `/home/razinka/shyfem/shyfem-ui/`.
- Playwright tests are excluded from default pytest (`--ignore-glob` in `pyproject.toml`); run them explicitly.
- Commit after each task with conventional-commit messages.
- All paths below are relative to `/home/razinka/shyfem/shyfem-ui/` unless absolute.

**Phase ordering (by value × readiness):**
1. Phase A — page-helper extraction + tests (HIGH)
2. Phase C — `ProjectService` for home.py DB access (MED)
3. Phase H — behavioral access-control Playwright tests (MED)
4. Phase J — end-to-end Celery task test (MED)
5. Phase K — multi-process Celery worker bootstrapping (MED)
6. Phase I — deepen partition validation (LOW)
7. Phase F — request-timing/metrics middleware (LOW; **decision checkpoint**)
8. Phase G — flux/frequency postprocess controls (LOW; **domain checkpoint**)
9. Phase E — service-layer naming consistency (LOW)
10. Phase D — split god modules (LOW; highest risk)
11. Phase P3 — IBM-LGR enhancements
— — — (deferred — reference only, DO NOT execute) — — —
D1. Phase L — output-directory picker (DEFERRED)
D2. Phase M.1 — run.py job-poller DI seam (DEFERRED)

---

## Phase A — Extract pure helpers from 5 large pages + unit tests

**Goal:** Add unit coverage to `run.py`, `simulation.py`, `grid_prep.py`, `partitioning.py`, `postprocess.py` by moving still-inline pure logic into their existing `services/*_logic.py` companions.

**Established pattern (follow exactly):** the five `services/*_logic.py` companions **already exist** (`run_logic`, `simulation_logic`, `grid_prep_logic`, `partitioning_logic`, `postprocess_logic` — verified present). Service module has `from __future__ import annotations`, keyword-only args, full docstrings; the page re-imports each name with a `# re-exported for backward compat` comment (see `pages/run.py:38-46`); tests live in `tests/test_<page>_logic.py` and import straight from the service (see `tests/test_postprocess_logic.py:71-105`).

**Data-model note (critical for the run.py tasks):** the `run.py` dashboard/timeline/restart logic operates on `JobInfo` **objects** whose `.status` is a `JobStatus` **enum** (not string dicts), and "queued" is the union `PENDING | QUEUED`. Extracted run.py helpers below take `list[JobInfo]` and compare against `JobStatus.*`. Where a task shows dict-shaped test data, that is illustrative — use real `JobInfo`/`JobStatus` (import from the same module `run.py` uses) so the test reflects production types.

Each extraction below is one task with the same 5-step shape. Task A1 is written out in full as the template; A2–A18 repeat the shape against the listed target.

### Task A1: `summarize_job_counts` (run.py dashboard tallies)

**Files:**
- Modify: `shyfem_ui/services/run_logic.py` (add function)
- Modify: `shyfem_ui/pages/run.py:712-716` (delegate) + import block `run.py:38-46`
- Test: `tests/test_run_logic.py`

- [ ] **Step 1: Write the failing test** in `tests/test_run_logic.py`. First open `pages/run.py` and `services/job_queue.py` to confirm the `JobInfo`/`JobStatus` import path and enum members, then:

```python
from shyfem_ui.services.run_logic import summarize_job_counts
from shyfem_ui.services.job_queue import JobInfo, JobStatus  # confirm exact path

def _job(status):
    # JobInfo requires id, name, tool_name, args, working_dir, status (all no-default).
    return JobInfo(id="x", name="n", tool_name="shyfem", args=[],
                   working_dir="/tmp", status=status)

class TestSummarizeJobCounts:
    def test_tallies_by_status(self):
        jobs = [
            _job(JobStatus.RUNNING), _job(JobStatus.RUNNING),
            _job(JobStatus.QUEUED), _job(JobStatus.COMPLETED),
            _job(JobStatus.FAILED), _job(JobStatus.COMPLETED),
        ]
        counts = summarize_job_counts(jobs)
        assert counts == {"running": 2, "queued": 1, "completed": 2, "failed": 1}

    def test_pending_counts_as_queued(self):
        assert summarize_job_counts([_job(JobStatus.PENDING)])["queued"] == 1

    def test_empty_has_exactly_four_keys(self):
        counts = summarize_job_counts([])
        assert counts == {"running": 0, "queued": 0, "completed": 0, "failed": 0}
        assert set(counts) == {"running", "queued", "completed", "failed"}

    def test_unknown_status_not_added_as_key(self):
        # A status outside the four buckets must NOT create a new dict key.
        counts = summarize_job_counts([_job(JobStatus.CANCELLED)])  # or any non-bucketed
        assert set(counts) == {"running", "queued", "completed", "failed"}
```

(Adjust `JobInfo(...)` construction to the real required fields; the point is to use real `JobInfo`/`JobStatus`, not string dicts.)

- [ ] **Step 2: Run to verify it fails**

Run: `CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_logic.py::TestSummarizeJobCounts -v`
Expected: FAIL — `ImportError: cannot import name 'summarize_job_counts'`.

- [ ] **Step 3: Implement** in `shyfem_ui/services/run_logic.py`:

```python
def summarize_job_counts(jobs: list["JobInfo"]) -> dict[str, int]:
    """Tally jobs by status for the dashboard summary cards.

    Args:
        jobs: JobInfo objects whose .status is a JobStatus enum.
    Returns:
        Counts keyed exactly by running/queued/completed/failed.
        "queued" is the union of PENDING and QUEUED; unknown statuses ignored.
    """
    from shyfem_ui.services.job_queue import JobStatus  # local import; confirm path
    counts = {"running": 0, "queued": 0, "completed": 0, "failed": 0}
    bucket = {
        JobStatus.RUNNING: "running",
        JobStatus.PENDING: "queued",
        JobStatus.QUEUED: "queued",
        JobStatus.COMPLETED: "completed",
        JobStatus.FAILED: "failed",
    }
    for job in jobs:
        key = bucket.get(job.status)
        if key:
            counts[key] += 1
    return counts
```

- [ ] **Step 4: Delegate from the page.** In `run.py:38-46` add `summarize_job_counts` to the `run_logic` import block. Replace the inline tally at `run.py:713-716` (line 712 is the `# Summary stats` comment) with `counts = summarize_job_counts(all_jobs)` and read `counts["running"]` etc.

- [ ] **Step 5: Run + commit**

Run: `CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_logic.py -v` → PASS
```bash
git add shyfem_ui/services/run_logic.py shyfem_ui/pages/run.py tests/test_run_logic.py
git commit -m "refactor(run): extract summarize_job_counts into run_logic + tests"
```

### Tasks A2–A5 (run.py), same 5-step shape, target → service signature:
- [ ] **A2** `build_solver_hint(num_nodes: int, threshold: int, petsc_available: bool) -> dict` — pure core of `run.py:400-430`. **First read the existing `get_solver_recommendation` in `run_logic` (already returns a dict read as `rec["hint"]`)** — extend or wrap it rather than inventing a new return shape; only the PETSc-availability check + warning flag are genuinely new. Test the 3 branches (small mesh→sparskit, large+petsc→petsc, large+no-petsc→warning) against the actual `get_solver_recommendation` contract.
- [ ] **A3** `build_restart_choices(jobs: list["JobInfo"], rst_paths: list[str]) -> dict[str, str]` — `run.py:439-450`. Pass the glob results in as `rst_paths` so the function is pure (no filesystem); iterate completed `JobInfo` objects. Test label formatting + empty case.
- [ ] **A4** `build_timeline_traces(jobs: list["JobInfo"]) -> list[dict]` — `run.py:919-963`. Operates on `JobInfo` objects (`.status` enum, `.started_at`/`.completed_at`/`.created_at`/`.duration`, `.name`). Returns plotly-ready trace dicts (status color map, last-20 slice, per-job duration seconds). Page calls `go.Figure()` on the result. Test color mapping + slice cap + duration math.
- [ ] **A5** `build_workflow_params(input_str: str, input_grd: str, mpi_np: int) -> dict` — `run.py:1193-1199`. Trivial; test dict shape.

### Tasks A6–A9 (simulation.py):
- [ ] **A6** `partition_validation(msgs: list) -> tuple[list, list, list]` — the 3-way error/warning/info bucketing at `simulation.py:435-437` (in `template_preview`). Note: `simulation.py:379-383` is a *2-level* notification loop (error/warning only, no info bucket), so it is NOT a second identical call site — extract the single real bucketing site and, if desired, have `_confirm_save` reuse the error/warning subsets. Test bucketing incl. the empty-info case.
- [ ] **A7** `summarize_template(parsed, msgs) -> dict` — `simulation.py:417-462` (section_names, param_count of non-`_` keys, validation buckets via A6). Test count + bucket pass-through.
- [ ] **A8** `suggest_save_path(current_path: str | None, work_dir: str) -> str` — `simulation.py:316-320`. Test both branches.
- [ ] **A9** `flatten_section_params(section) -> list[dict]` — `simulation.py:526-544` (`_standalone` node-list vs `key=value`). Test both section shapes.

### Tasks A10–A14 (grid_prep.py):
- [ ] **A10** `build_quality_histogram(qualities: list[float]) -> str` — `grid_prep.py:700-710` ASCII bars. **Preserve the existing fixed 11-edge bin array `[0, 0.1, …, 1.01]` and the `min(hi, 1.0)` label clamp** (don't generalize to a configurable `bins` int — that changes behavior). Test row count + bar scaling against the fixed edges.
- [ ] **A11** `quality_status_class(below_03: int, count: int) -> str` — `grid_prep.py:712-716`. The real logic branches on `below_03 == 0` → success, then `below_03 < count * 0.05` → warning, else danger — so it needs **both** args. **A12** `angle_quality_badge(min_angle: float) -> tuple[str, str]` — `grid_prep.py:797-805`. Test all thresholds incl. the middle warning band.
- [ ] **A13** `build_shypre_options(opti: bool, renumber: bool) -> list[str]` — `grid_prep.py:330-334`. Test 4 combos.
- [ ] **A14** `sanitize_grid_name(filename: str) -> str` — `grid_prep.py:600-602`. Test path-separator stripping.

### Tasks A15–A16 (partitioning.py):
- [ ] **A15** `build_balance_traces(elements: list[int], metrics: dict) -> dict` — `partitioning.py:370-403` (colors + title). Test color cycling.
- [ ] **A16** `imbalance_class(pct: float) -> str` — `partitioning.py:474-478` (`<10`/`<20`/else). Test boundaries.

### Tasks A17–A18 (postprocess.py):
- [ ] **A17** `parse_timeseries_text(text: str) -> dict | None` — **strongest candidate**, `postprocess.py:1042-1078` (header-vs-numeric detection, float-row parse). Test: header row skipped, numeric rows parsed, malformed → None, empty → None.
- [ ] **A18** `group_file_info(info: dict) -> dict[str, list]` — `postprocess.py:866-900` (basic/grid/time/var key partition + remaining). Test partition + leftover bucket.

**Phase A self-check:** every extracted name appears in both the service module and the page's import block; every `tests/test_<page>_logic.py` runs green; the existing Playwright suites for these 5 pages still pass (run `tests/test_playwright_workflows.py`).

---

## Phase C — `ProjectService` for home.py inline DB access

**Goal:** Route the **6** inline `db_session()` sites in `pages/home.py` (lines 282, 491, 592, 826, 952, 1052) through a new `services/project_service.py`.

> **Tracker drift note:** the 2026-04-29 tracker lists `admin.py` and `files.py` as also having inline DB access. **Re-verified 2026-05-27: both are now clean** — `grep -n "db_session" pages/admin.py pages/files.py` returns zero hits; `admin.py` routes through `auth_service`/`audit_service`/`NotificationService` and `files.py` through `FileService`. They were cleaned up since the tracker was written. No work needed there; update the tracker's item C accordingly when closing this phase.

**Files:**
- Create: `shyfem_ui/services/project_service.py`
- Create: `tests/test_project_service.py`
- Modify: `shyfem_ui/pages/home.py` (6 functions delegate; drop `db_session`/model imports where no longer used)

**Design:** A `ProjectService` with static methods, each taking an explicit `db` session (so tests pass a fixture session) OR opening its own — match the existing `FileService` static-method style. Move the pure helper `get_visible_projects` (`home.py:37-61`) into the service.

| Method | Replaces | home.py site |
|---|---|---|
| `list_visible_projects(db, *, user_id, role, limit=10) -> list[dict]` | `get_visible_projects` + admin branch | 37-61, 282-299, 286 |
| `create_project(db, *, name, description, work_dir, owner_id) -> Project` | inline `Project(...)+add` | 491-507 |
| `create_tutorial_project(db, *, name, work_dir, owner_id, tutorial_content) -> Project` | multi-entity tx (project+grid+sims) | 592-629 |
| `add_grid(db, *, project_id, name, grd_file) -> Grid` | inline `Grid(...)+add` | 826-832 |
| `create_project_records(db, *, meta: dict, owner_id) -> Project` | clone + import multi-entity tx (import is superset of fields; one method, optional columns) | 952-986, 1052-1096 |

### Task C1: `list_visible_projects` (read path)

**Files:** Create `services/project_service.py` + `tests/test_project_service.py`; modify `home.py`.

**Contract decisions (lock these before writing the test):**
- **Return type is `list[dict]`, not ORM objects.** Today `get_visible_projects` returns `.all()` (ORM) and the dict projection (`{"id": p.id, "name": p.name, ...}`) happens inline in `_refresh_projects` at `home.py:287-298`. The service method must **absorb that projection** so the page no longer touches ORM objects. (Otherwise logic splits across two layers and the "no inline DB" self-check passes while the projection leaks.)
- **Preserve the `user is None` branch.** At `home.py:283`, `if user and user.get("role") != ROLE_ADMIN:` means a **None user falls into the admin branch and sees ALL projects** (local/unauth mode). The new signature must handle `user_id=None`/`role=None` and reproduce this exact behavior — pin it with a dedicated test. Do NOT silently drop it.

- [ ] **Step 0: Define fixtures (concrete — these don't exist; without them the tests can't be collected).** `tests/test_access_control.py` only exposes `db_factory` + a `setup` fixture returning an ID dict — there are NO `db`/`alice`/`bob`/`admin`/`alice_project` fixtures. Add to the top of `tests/test_project_service.py` (confirm the real `User`/`Project` constructor fields and `init_db` helper against the codebase first):

```python
import pytest
from shyfem_ui.db.base import get_session_factory, init_db
from shyfem_ui.models.user import User, ROLE_ADMIN, ROLE_USER
from shyfem_ui.models.project import Project

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    init_db()                                  # create schema (confirm helper name)
    factory = get_session_factory()
    session = factory()
    yield session
    session.close()

def _user(db, username, role):
    u = User(username=username, role=role, email=f"{username}@example.com")
    db.add(u); db.flush(); return u

@pytest.fixture
def alice(db): return _user(db, "alice", ROLE_USER)
@pytest.fixture
def bob(db):   return _user(db, "bob", ROLE_USER)
@pytest.fixture
def admin(db): return _user(db, "admin", ROLE_ADMIN)

@pytest.fixture
def alice_project(db, alice):
    p = Project(name="A", description="", work_dir="/tmp/a", owner_id=alice.id)
    db.add(p); db.flush(); return p
```

(Adjust `User(...)`/`Project(...)` kwargs and the `init_db`/schema-setup call to the real signatures — verify before running.)

- [ ] **Step 1: Failing test** in `tests/test_project_service.py`:

```python
import pytest
from shyfem_ui.services.project_service import ProjectService
from shyfem_ui.models.user import ROLE_ADMIN, ROLE_USER

class TestListVisibleProjects:
    def test_owner_sees_own_as_dict(self, db, alice, alice_project):
        rows = ProjectService.list_visible_projects(
            db, user_id=alice.id, role=ROLE_USER, limit=10
        )
        assert any(r["id"] == alice_project.id for r in rows)
        assert isinstance(rows[0], dict)  # projection absorbed into the service

    def test_admin_sees_all(self, db, admin, alice_project):
        rows = ProjectService.list_visible_projects(
            db, user_id=admin.id, role=ROLE_ADMIN, limit=10
        )
        assert any(r["id"] == alice_project.id for r in rows)

    def test_stranger_sees_none(self, db, bob, alice_project):
        rows = ProjectService.list_visible_projects(
            db, user_id=bob.id, role=ROLE_USER, limit=10
        )
        assert rows == []

    def test_none_user_sees_all(self, db, alice_project):
        # Preserves the local/unauth-mode behavior from home.py:283.
        rows = ProjectService.list_visible_projects(
            db, user_id=None, role=None, limit=10
        )
        assert any(r["id"] == alice_project.id for r in rows)
```

- [ ] **Step 2: Run → FAIL** (`ImportError`). Run: `... pytest tests/test_project_service.py -v`
- [ ] **Step 3: Implement** `ProjectService.list_visible_projects` in `services/project_service.py` by lifting the body of `get_visible_projects` (home.py:37-61) **plus** the dict-projection loop (home.py:287-298), and reproducing the `user is None → admin branch` logic.
- [ ] **Step 4: Delegate.** In `home.py:282-299` (`_refresh_projects`) call `ProjectService.list_visible_projects(db, user_id=..., role=..., limit=10)` and use the returned dicts directly; delete the inline `db.query(Project)` admin branch at 286, the projection loop, and the old `get_visible_projects` helper.
- [ ] **Step 5: Run + commit.**
```bash
git add shyfem_ui/services/project_service.py shyfem_ui/pages/home.py tests/test_project_service.py
git commit -m "feat(services): add ProjectService.list_visible_projects, route home.py through it"
```

### Task C2: `create_project` (write path)
- [ ] Test: calling `ProjectService.create_project(db, name=..., description=..., work_dir=..., owner_id=alice.id)` inserts a row owned by alice and returns it. Then delegate `home.py:491-507`. Commit.

### Task C3: `create_tutorial_project` (atomic multi-entity tx)
- [ ] Test: returns a project with the expected grid + N simulation rows in one transaction (assert counts via `db.query`). Pass `tutorial_content` as plain data. Delegate `home.py:592-629`. Commit.

### Task C4: `add_grid`
- [ ] Test: inserts a `Grid` for an existing project. Delegate `home.py:826-832`. Commit.

### Task C5: `create_project_records` (clone + import)
- [ ] Test two cases: a minimal `meta` (clone) and a full `meta` (import superset: num_nodes/elements/layers/min_max_depth, start/end_time, time_step, mpi_enabled/np). Assert grids+sims created and `grid_name_to_id` mapping is honored. **The method must NOT open its own `db_session()` — it takes the caller's `db`, and must call `db.flush()` after each `db.add(project)` and `db.add(grid)`** (mirroring `home.py:963, 975, 1063, 1080`) so the auto-generated `id` is populated before the next entity references it. Omitting `flush()` binds `None` foreign keys silently — add a test asserting `grid.id is not None` before the simulation rows reference it. Delegate BOTH `home.py:952-986` (clone) and `home.py:1052-1096` (import). Commit.

> **Multi-entity atomicity (C3 + C5):** `create_tutorial_project` and `create_project_records` must run the whole project+grid+sims insert on the caller's single `db` session so the `with db_session()` block commits/rolls back atomically. Same `db.flush()`-after-each-add requirement applies to C3.

**Phase C self-check:** `grep -n "db_session" shyfem_ui/pages/home.py` returns nothing; `home.py` no longer imports `Grid`/`Simulation`/`Project` directly unless still needed for type hints; full suite green.

---

## Phase H — Behavioral access-control Playwright tests

**Goal:** Prove that an account-role `user` with only `viewer` project permission cannot perform the 9 editor-gated writes (the static AST check in the 2026-04-29 plan only verified a `check_project_access` call *exists*).

**Role model (do not conflate):** account roles are `admin`/`user`/`tutorial` (`models/user.py:12-14`); project roles are `owner`/`editor`/`viewer` (`access_control.py:6`). A "non-editor" = account `user` + `viewer` permission. Behavioral tests MUST run against the **auth server** (`_test_auth_app.py`, which mounts `SessionAuthMiddleware`), NOT the local stub app.

**The 9 editor-gated write handlers (one test each):**

| # | Page | Handler | Guard line | Mutation to assert *did not happen* |
|---|---|---|---|---|
| 1 | partitioning.py | `_run_shyparts` | 243 | no new `.par` in output dir |
| 2 | grid_prep.py | `_run_shypre` | 283 | no `.bas` written |
| 3 | files.py | `_handle_upload` | 303 | no new ProjectFile row / file |
| 4 | files.py | `_do_delete` | 433 | target file still present |
| 5 | ensemble.py | `_submit_ensemble` | 514 | no new jobs |
| 6 | simulation.py | `_confirm_save` | 350 | STR file unchanged |
| 7 | physics.py | `save_file` | 448 | STR file unchanged |
| 8 | run.py | `_submit_job` | 592 | no new job in queue |
| 9 | postprocess.py | `_run_shyelab` | 498 | no shyelab output |

> **PRECONDITION: Phase C must be merged first.** Task H1 seeds a project via `ProjectService.create_project` (Phase C, Task C2). If Phase C isn't done, either complete it first or temporarily seed with the inline `Project(...) + db.add` pattern. The phase ordering (C before H) already reflects this — do not start H before C.

### Task H1: Seed a viewer user + shared project fixture

**Files:** Modify `tests/_test_auth_app.py` (seed at startup) + `tests/conftest.py` (add `pw_viewer_page` fixture).

**Three API corrections baked in below (the naive versions don't exist / are misused):** `AuthService` has **no `get_user_by_username`** (use a direct `db.query(User).filter_by(username=...)`); `SharingService.share_project` is an **instance method** (`SharingService().share_project(...)`, see app.py:151-152); the workdir in scope is **`args.workdir`** (a CLI arg string), not a bare `workdir`. Reuse the existing `"testpass"` test credential (don't introduce a second weak password). Make the seed **idempotent** (skip if `viewer1` already exists) so re-boots are safe.

- [ ] **Step 1:** In `tests/_test_auth_app.py` after `create_app(config)` (line ~43), before `run_app`, seed into the subprocess's own SQLite DB (this runs before `_wait_for_server` returns, so no race):

```python
# Seed a non-editor viewer for behavioral access-control tests (Item H). Idempotent.
from pathlib import Path
from shyfem_ui.services.auth_service import AuthService
from shyfem_ui.services.sharing_service import SharingService
from shyfem_ui.services.project_service import ProjectService  # Phase C (Task C2)
from shyfem_ui.db.base import db_session
from shyfem_ui.models.user import User

auth = AuthService(config)
with db_session() as db:                       # idempotency probe
    already = db.query(User).filter_by(username="viewer1").first() is not None
if not already:
    # create_user commits in its own session.
    auth.create_user("viewer1", "testpass", role="user", email="viewer1@example.com")
    # Create + COMMIT the project FIRST (share_project opens its own session, so the
    # project row must be committed before the FK reference is inserted).
    with db_session() as db:
        admin = db.query(User).filter_by(username="admin").first()
        proj = ProjectService.create_project(
            db, name="Shared", description="",
            work_dir=str(Path(args.workdir) / "shared"), owner_id=admin.id,
        )
        db.flush()                              # populate proj.id within the tx
        proj_id = proj.id
        viewer_id = db.query(User).filter_by(username="viewer1").first().id
    # outer block committed → project persisted. Share via SharingService's own session.
    SharingService().share_project(proj_id, viewer_id, role="viewer")  # no-arg ctor
```

> **Two ordering corrections baked in:** (1) use `SharingService()` with **no** `session_factory` arg — `db_session` is a `@contextmanager`, not a `sessionmaker`, so passing it makes `share_project` call `.query()` on a context-manager object and crash (the no-arg ctor falls back to the real factory, matching `app.py:151-152`). (2) `share_project` runs **after** the `with db_session()` block commits, else its independent session inserts a `ProjectPermission` FK pointing at an uncommitted project row (FK violation at startup).

- [ ] **Step 2:** Add `pw_viewer_page` fixture to `conftest.py` mirroring `pw_auth_page` (conftest.py:338-348) but `_login(page, auth_live_server, "viewer1", "testpass")`.
- [ ] **Step 3:** Smoke test — `test_viewer_can_login` asserts `/api/whoami` returns `{"role": "user"}` and the viewer lands on `/`.
- [ ] **Step 4:** Run `... pytest tests/test_playwright_auth.py -v` → PASS (existing auth tests must still pass with the new seed).
- [ ] **Step 5:** Commit.

### Tasks H2–H10: one behavioral test per handler

**Critical design (the naive template was a false positive):**
1. The auth server (`_test_auth_app.py`) does **NOT** expose `window.__test_set_active_project` — that JS hook lives only in the local `_test_app.py`. The viewer must reach the shared project through the **real UI**: log in (via `pw_viewer_page`) → Dashboard → click the "Shared" project card to activate it. Add a helper `_open_shared_project(page)` that performs this navigation and waits for activation (assert the project name appears in the active-project indicator).
2. Assertions must use **`and`**, never a disjunct that's trivially true on a fresh page. Assert BOTH: (a) the permission error toast appeared, AND (b) the mutation did NOT occur (job count unchanged / file unchanged / file still present). A test that can pass without the guard firing is worse than no test.

- [ ] **Step 0 (REQUIRED selector-discovery — these tests are invalid without it):** Run the auth server manually, log in as `viewer1`, and inspect the live DOM to record three real selectors: (i) the **active-project indicator** that only appears/changes once a project is activated (sidebar badge / breadcrumb — NOT the Dashboard card label, which is present before activation), (ii) the exact **error-toast text** each guard's `ui.notification_show(...)` emits (so the `has_text=` filter matches reality — confirm it actually says "permission"/"access"/etc.), (iii) for job/file handlers, the canonical mutation marker. Per CLAUDE.md's UI-testing rule, a behavioral test built on guessed selectors is not validated. Vacuous selectors (matching nothing) make `before == after == 0` trivially true — guard against that by asserting the baseline is non-trivial (below).

- [ ] **Step 1:** New file `tests/test_playwright_access_behavioral.py` (selectors below are placeholders to replace with the Step 0 findings):

```python
import pytest
pytestmark = [pytest.mark.e2e]
from tests.conftest import _dismiss_modals

ACTIVE_PROJECT_INDICATOR = "#active-project-name"   # REPLACE via Step 0
GUARD_TOAST_TEXT = "permission"                      # REPLACE via Step 0

def _switch_tab(page, name):
    _dismiss_modals(page)
    page.locator(f".sf-nav-item[data-nav='{name}']").click(force=True)

def _open_shared_project(page):
    """Activate the seeded 'Shared' project; assert activation via a real indicator."""
    _switch_tab(page, "Dashboard")
    page.wait_for_timeout(500)
    page.locator(".project-card", has_text="Shared").first.click(force=True)
    # Activation proof: an indicator that is ABSENT before activation.
    page.locator(ACTIVE_PROJECT_INDICATOR).filter(has_text="Shared").wait_for(
        state="visible", timeout=10000
    )

class TestViewerCannotWrite:
    def test_viewer_cannot_submit_job(self, pw_viewer_page):
        page = pw_viewer_page
        _open_shared_project(page)
        _switch_tab(page, "Run")
        page.locator("#run-submit_btn").wait_for(state="visible")  # on Run w/ project
        page.locator("#run-submit_btn").click(force=True)
        page.wait_for_timeout(1500)
        # Primary signal: the guard fired (error toast with the real guard text).
        toast = page.locator(".shiny-notification").filter(has_text=GUARD_TOAST_TEXT)
        assert toast.count() >= 1, "expected the access-denied toast (guard fired)"
```

- [ ] **Step 1b (mutation-absence — prefer out-of-band over DOM):** the test process runs on the same machine as the seeded project, so assert the mutation did NOT happen by checking the **filesystem/DB directly**, not a DOM count (DOM counts go vacuous on a wrong selector). For each handler: snapshot the target before the click and compare after — e.g. job handlers: `JobQueue.list_jobs()`/DB row count for the shared project unchanged; file-write handlers (simulation/physics save, shypre/shyparts/shyelab outputs): the target file's mtime+size (or `os.listdir(work_dir)`) is identical before/after; delete handler: the target file still exists. This is the assertion that proves the *side effect* was blocked, independent of any toast.

- [ ] **Step 2:** Run → if a test FAILS it has found a real bug (guard positioned after the mutation, or no toast). Investigate per `superpowers:systematic-debugging` — do NOT weaken the assertion to make it pass.
- [ ] **Step 3–5:** No product change expected (guards exist); if a test reveals a guard-ordering bug, fix the page then re-run. Repeat the template for H2–H9 (partitioning `.par`, grid_prep `.bas`, files upload, files delete, ensemble submit, simulation save, physics save, postprocess shyelab) asserting each row's specific mutation-absence. Commit.

**Phase H self-check:** 9 behavioral tests + 1 viewer-login smoke test; each uses real UI project-selection (no JS hook), and each assertion is a conjunction of (toast present) AND (mutation absent) — no trivially-true disjuncts. Run the full Playwright auth + behavioral files.

---

## Phase J — End-to-end Celery task test

**Goal:** Exercise `execute_shyfem_job`'s full `finally` chain (`_store_job_info` → `_persist_job_to_db` → `_send_completion_notification`, `job_celery.py:236-242`) — currently zero coverage. The task body is never invoked by any existing test.

**Approach (simplest, per research):** call `execute_shyfem_job(...)` directly (the Celery task wrapper at `job_celery.py:359-361` just calls it), with Redis mocked and `ShyfemWrapper.run_shyfem` patched. No real broker needed.

**Files:**
- Modify: `tests/test_job_celery.py` (extend — do NOT create a new file)

**Pre-work (do before J1 Step 1): write the test helpers.** None of `_make_mock_redis`, `_seed_fake_redis`, `_ok_result`, `_fail_result` exist. Add to `tests/test_job_celery.py`:
- `_make_mock_redis()` + `_seed_fake_redis(rc, job_id)` — **`MagicMock`'s `hset` and `hget` are independent**, so calling `_store_job_info(rc, job)` does NOT make `rc.hget(...)` return the data. You MUST explicitly configure the read: `rc.hget.return_value = _job_info_to_json(job)` (a PENDING `JobInfo`), matching the key/shape `_load_job_info` reads. If skipped, `_load_job_info` returns falsy and `execute_shyfem_job` early-returns at `job_celery.py:158`, skipping the whole try/finally — a silent false pass (the exact trap this phase exists to avoid).
- `_ok_result()` / `_fail_result()` — minimal objects matching what `ShyfemWrapper.run_shyfem` returns (inspect its return type; likely a result object with `.success`/`.return_code`).
- Patch the **existing** `_get_redis_client` (module function at `job_celery.py:66`, called at line 156), NOT a new `_get_redis_client_for`. No product-code seam is needed.
- **Patch `ShyfemWrapper.__init__` to a no-op** (`monkeypatch.setattr(mod.ShyfemWrapper, "__init__", lambda self, *a, **k: None)`), else constructing it with a fake `shyfem_dir="/tmp/shyfem"` may raise *before* the `try` block — the `finally` chain never runs and the test fails with a misleading constructor error instead of an assertion. Use a real temp dir for `working_dir` (e.g. `tmp_path`) so the `working_dir.mkdir(...)` inside the task is harmless.
- `run_shyfem` is **async** — patch it with `unittest.mock.AsyncMock(return_value=_ok_result())`, not a plain lambda (`asyncio.run(await None)` would raise).

### Task J1: success path fires persist + notify

- [ ] **Step 1: Failing test** in `tests/test_job_celery.py`:

```python
from unittest.mock import AsyncMock
from shyfem_ui.services.job_queue import JobStatus

class TestExecuteShyfemJobEndToEnd:
    def test_success_persists_and_notifies(self, monkeypatch):
        import shyfem_ui.services.job_celery as mod
        persisted, notified = [], []
        monkeypatch.setattr(mod, "_persist_job_to_db", lambda ji, **k: persisted.append(ji))
        monkeypatch.setattr(mod, "_send_completion_notification", lambda ji: notified.append(ji))
        fake_rc = _make_mock_redis()                 # existing mock pattern
        _seed_fake_redis(fake_rc, "job-1")           # store a PENDING JobInfo
        monkeypatch.setattr(mod, "_get_redis_client", lambda url: fake_rc)
        monkeypatch.setattr(mod.ShyfemWrapper, "run_shyfem",
                            AsyncMock(return_value=_ok_result()))
        mod.execute_shyfem_job("job-1", "redis://x", "/tmp/shyfem")
        assert len(persisted) == 1 and persisted[0].status == JobStatus.COMPLETED
        assert len(notified) == 1
```

- [ ] **Step 2: Run → FAIL** (asserts unmet once helpers exist). If it errors with `NameError`/`AttributeError`, the helpers/patch targets are wrong — fix those first.
- [ ] **Step 3: Implementation** — **none in product code**; this is pure test coverage of the existing `finally` chain.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit.**

### Task J2: failure path still fires the finally chain
- [ ] Same harness (the seeded fake redis MUST return a valid PENDING `JobInfo`, else the `job_celery.py:158` early-return skips the finally and `persisted[0]` raises `IndexError`, masking the real check). Patch `run_shyfem` with `AsyncMock(side_effect=RuntimeError("boom"))`; assert `persisted[0].status == JobStatus.FAILED` and `len(notified) == 1` (finally runs on exception). Commit.

### Task J3: `result.success == False` branch
- [ ] Patch `run_shyfem` with `AsyncMock(return_value=_fail_result())` (a result with `success=False`); assert terminal status `JobStatus.FAILED` and the chain fired. Commit.

**Phase J self-check:** three tests cover success / exception / soft-failure; all drive the real `execute_shyfem_job`, not the helpers in isolation.

---

## Phase K — Multi-process Celery worker bootstrapping

**Goal:** Fix the confirmed bug that `celery -A shyfem_ui.services.job_celery worker` (docker-compose.yml:46) cannot start: the module exposes no discoverable `app`, the task is never registered worker-side, and the notification/session globals are `None` in the worker process.

**Files:**
- Create: `shyfem_ui/services/celery_worker.py` (the `-A` entrypoint)
- Modify: `shyfem_ui/services/job_celery.py` (worker-side fallbacks + eager flag)
- Modify: `shyfem_ui/config.py` (add `celery_task_always_eager: bool = False`)
- Modify: `docker-compose.yml:46` (point `-A` at the new entrypoint)
- Modify: `tests/test_job_celery.py`

**Design (corrected — do NOT create the app in `job_celery.py`'s module body):** putting `app = get_celery_app(get_config())` at `job_celery.py` import time runs `get_config()` during pytest collection (before `_isolate_env` strips env), and the `_celery_app is None` singleton guard then makes the K3 eager-mode test un-injectable. Instead:
1. **Dedicated worker entrypoint** `shyfem_ui/services/celery_worker.py` whose module body builds the app + registers the task. `celery -A shyfem_ui.services.celery_worker worker` discovers `celery_worker.app`. The web app never imports this module, so its import side-effects don't touch the web/test paths:
```python
# shyfem_ui/services/celery_worker.py — Celery worker entrypoint ONLY.
from shyfem_ui.config import get_config
from shyfem_ui.services.job_celery import get_celery_app, _register_celery_task
app = get_celery_app(get_config().redis_url)
_register_celery_task(app)
```
2. **Worker-side helpers resolve deps at call time** (not from `__init__`-set globals). `_persist_job_to_db` already falls back to `db_session()`. Change `_send_completion_notification` (`job_celery.py:318-319`): if `_queue_notification_service` is None, **construct `NotificationService(get_config())`** (its `__init__` only stores config — no SMTP connection; `notify_*` no-ops gracefully when SMTP unconfigured) instead of returning early — so worker-side emails actually send. The notification test needs a `user_id` in `job_info.metadata` and a mocked `db_session` user lookup.
3. **Eager flag** in `get_celery_app` driven by `config.celery_task_always_eager`, enabling J-style tests through real dispatch.

### Task K1: discoverable worker entrypoint
- [ ] **Test A** (`tests/test_job_celery.py`): `import shyfem_ui.services.celery_worker as w; assert "shyfem_ui.execute_job" in w.app.tasks`. Run → FAIL (module doesn't exist). Create `celery_worker.py` as above. Run → PASS.
- [ ] **Test B (web-app import safety):** prove the web path doesn't pull in the worker entrypoint. Asserting `job_celery._celery_app is None` is **flaky** (a prior test may have populated the singleton via `CeleryJobQueue`). Instead assert isolation by module presence: `import importlib, sys; importlib.import_module("shyfem_ui.app"); assert "shyfem_ui.services.celery_worker" not in sys.modules`. (Optionally also spy: `monkeypatch.setattr(job_celery, "get_celery_app", Mock())` before a fresh import and assert the spy wasn't called — but the `sys.modules` check is the non-flaky core.) Commit.
- [ ] Update `docker-compose.yml:46`: `celery -A shyfem_ui.services.celery_worker worker --loglevel=info`.

### Task K2: worker-side notification fallback
- [ ] **Test:** with both globals None and a `user_id` in `job_info.metadata`, `_send_completion_notification(job)` constructs a `NotificationService` from config and calls `notify_job_success` (patch `NotificationService` to a spy AND `db_session` to return a fake user). Run → FAIL (current code returns early at `job_celery.py:319`). Implement the config fallback. Run → PASS. Commit.

### Task K3: eager-mode flag
- [ ] **Test:** with `config.celery_task_always_eager=True`, `get_celery_app(url).conf.task_always_eager is True`. Note the `_celery_app is None` singleton guard — the test must reset `_celery_app = None` (monkeypatch) before calling so a fresh app is built. Implement the conf branch. Commit.

**Phase K self-check:** `python -c "import shyfem_ui.services.celery_worker as w; print(list(w.app.tasks))"` lists `shyfem_ui.execute_job`; importing `shyfem_ui.app` does NOT build a Celery app; worker no longer silently drops notifications. Note in the tracker that K was reframed from "track the limitation" to a concrete fix (the `worker_init` signal the tracker suggested is replaced by the lazier call-time resolution + dedicated entrypoint). Update tracker item K to CLOSED.

---

## Phase I — Deepen "Validate Partitions"

**Goal:** Upgrade `_validate_partitions` (`partitioning.py:320-332`) from file-existence/size checks (`validate_partition_files`, `partitioning_logic.py:107-125`) to semantic checks against the source mesh.

**Files:**
- Modify: `shyfem_ui/services/partitioning_logic.py` (new pure functions + duplicate-tracking `analyze_partitions` variant)
- Modify: `shyfem_ui/pages/partitioning.py:320-332` (wire results, pass `current_grd.get()`)
- Modify/Create: `tests/test_partitioning_logic.py`

**Data available:** `analyze_partitions` returns `pmap = {element_id: partition_index}` and `stats["elements_per_partition"]`; the reference mesh is `current_grd.get()` (a `GrdFile` with `.elements`/`.nodes`, `parser_grd.py:100`).

### Task I1: duplicate-aware analysis
- [ ] **Test:** a new `analyze_partitions_detailed(output_dir, np_val)` returns `(pmap, duplicates)` where `duplicates` lists element IDs that appear in >1 `.par` file (today `pmap[elem]=i` silently overwrites — `partitioning_logic.py:41-68`). Build a fixture with two `.par` files sharing an element. Run → FAIL. Implement by accumulating a `defaultdict(list)` of partitions per element. Commit.

### Task I2: coverage validator
- [ ] **Test:** `validate_element_coverage(pmap_keys: set[int], mesh_elem_ids: set[int]) -> dict` returns `{missing: [...], phantom: [...], complete: bool}` (missing = mesh − pmap, phantom = pmap − mesh). Implement pure. Commit.

### Task I3: empty-partition + count checks
- [ ] **Test:** `find_empty_partitions(elements_per_partition: list[int]) -> list[int]` returns indices with 0 elements; `validate_partition_count(found: int, requested: int) -> bool`. Implement. Commit.

### Task I4: wire into the page
- [ ] In `partitioning.py:320-332`, after the existing size checks, if `current_grd.get()` is available, run the new validators and append human-readable lines to `log_content` (element-count match, missing/phantom/duplicate counts, empty partitions, imbalance pass/warn via existing `compute_load_balance`). Run the page's Playwright test to confirm no regression. Commit.

**Phase I self-check:** validators are pure + unit-tested; the page degrades gracefully (skips semantic checks) when no `.grd` is loaded.

---

## Phase F — Request-timing / metrics middleware

> **- [x] DECISION RECORDED — Phase F is DROPPED. Approver: arturas.razinkovas-baziukas@ku.lt (domain owner), 2026-05-27.**
> **Rationale:** No consumer — there is no Prometheus/Grafana scraper on laguna.ku.lt and nothing reads metrics. The genuinely useful half (request-IDs) is already shipped. A `/metrics` endpoint nobody scrapes is net-new public attack surface and (for prometheus) a new dependency — the exact preventive-maintenance gold-plating the 8-agent reviews killed twice on L/M.1. **Do not execute F1–F3.** Revisit only if a Prometheus scraper is deployed and confirmed reachable past nginx. Tracker item F → DROPPED. The backend-choice list and tasks below are reference-only.
>
> Request-IDs are **already implemented** (`middleware/request_id.py`, wired at `app.py:316`, log format at `app.py:960`) — so F reduces to *metrics + per-request timing*.
>
> ⚠️ **Strategic caveat (same profile that deferred L/M.1):** F is LOW priority, has **no current consumer** — there is no Prometheus/Grafana scraper in the laguna.ku.lt deployment — and a `/metrics` endpoint that "bypasses auth" is net-new public attack surface plus (for prometheus) a new dependency. Before doing F at all, answer: *is anything actually going to scrape this, and is `/metrics` reachable past nginx?* If no consumer and no exposure plan, **drop F** (same call the reviewers made on L/M.1).
>
> If F proceeds, choose the backend:
> - **(default — minimal) in-house counters** — a `MetricsRegistry` of plain tallies/timers, **no new dependency**, JSON at `/metrics`, can stay behind auth. Consistent with the project's YAGNI stance.
> - **`prometheus_client`** — only if a Prometheus server will actually scrape it; adds a `server`-extra dependency and a conventionally-unauthenticated `/metrics`. Requires an explicit "exposed past nginx?" answer.
> - **OpenTelemetry** — only for cross-service distributed tracing (not needed today).
>
> The tasks below are backend-agnostic; F2 implements whichever was chosen. **Remove any "assume X" default before handing to an executing agent** — the choice must be recorded here.

**Files:**
- Create: `shyfem_ui/middleware/metrics.py`
- Modify: `pyproject.toml` (`server` extra: `prometheus-client`) — **only if the prometheus backend was chosen; the in-house option adds no dependency**
- Modify: `shyfem_ui/app.py` (wire middleware + `/metrics`)
- Test: `tests/test_metrics_middleware.py`

### Task F1: timing middleware (records duration + status per path)
- [ ] **Test:** an ASGI test driving `MetricsMiddleware` over a dummy app records one observation with method+path+status and a positive duration. The middleware reuses `request_id_var` (`request_id.py:7`) so timing logs carry the request-id. Run → FAIL. Implement a small ASGI class mirroring `request_id.py`'s structure (wraps `self.app`, wraps `send` to capture status, times around the call). Commit.

### Task F2: `/metrics` exposure
- [ ] **Test:** `GET /metrics` returns Prometheus text exposition (or JSON for in-house) with the counters. Implement as a `/metrics` branch — either inside `MetricsMiddleware` or a tiny `MetricsEndpointMiddleware` wrapped **outermost** like `HealthCheckMiddleware` (`app.py:322`) so it bypasses auth. Commit.

### Task F3: wire into app.py
- [ ] **Insertion order matters (the obvious order is inverted).** ASGI wraps inside-out: the *last* wrapper added is the *outermost* and runs *first* on an inbound request. To have `request_id_var` already populated when `MetricsMiddleware` times/logs, `MetricsMiddleware` must be wrapped **before** (inside) `RequestIdMiddleware`:
```python
app = MetricsMiddleware(app)      # add FIRST → runs AFTER RequestId on inbound
app = RequestIdMiddleware(app)    # existing line ~316 → runs FIRST, sets request_id_var
```
So move the new `MetricsMiddleware(app)` line to immediately *before* the existing `app = RequestIdMiddleware(app)` (app.py:316), not after it. Mount the `/metrics` endpoint outermost (its own tiny middleware alongside `HealthCheckMiddleware` at app.py:322) so it bypasses auth only if the prometheus/public option was chosen; for the in-house/auth'd option, mount it inside the auth layer. Run full suite + a manual `curl /metrics`. Commit.

**Phase F self-check:** `/metrics` responds without auth; timing logs include `[request_id]`; no new dependency leaks into the base install (server-extra only).

---

## Phase G — Flux / frequency postprocess controls

> **- [x] DOMAIN DECISION RECORDED — Approver: arturas.razinkovas-baziukas@ku.lt (SHYFEM domain owner), 2026-05-27.**
> **Decision (split along the bug/feature line):**
> - **(a) Frequency — fix the bug now, defer the feature.** The "Frequency Analysis" op is broken, not merely under-built: it emits a bare `-freq` (defaults to `0`, a no-op) and is mislabeled as "spectral analysis," which shyelab cannot do. **NOW:** remove the `frequency` entry from `SHYELAB_OPERATIONS` (`postprocess.py`) so users can no longer run a meaningless, mislabeled operation. **DEFER:** the averaging-stride feature (Tasks G1/G2 — add `freq_n` to `build_shyelab_options` + a numeric UI control, emitting `-aver -freq n` etc.). It is correct and real but has no current consumer; pick it up when someone needs frequency-controlled averaging.
> - **(b) Flux — fix the bug now, defer the feature.** `-flux` is **not** a registered shyelab option, so the op silently does nothing. **NOW:** remove the `flux` entry from `SHYELAB_OPERATIONS`. **DEFER:** the real `.flx`-file workflow (Task G3 "in scope" branch — `.flx` discovery + `-node`/`-nodes` node-list input). That is a separate FLX pipeline, not a `.shy` shyelab op, and has no driver today.
> **Net effect:** G becomes two self-contained deletions in `postprocess.py` plus a followups note — no new feature code, no domain risk. Tasks G1/G2 and the G3 "in scope" branch are now reference-only (deferred); the G3 "out of scope" (remove flux) branch is the one being executed. Update tracker item G to note the two removals + the two deferred features.
>
> Research confirmed the current `-flux`/`-freq` flags are effectively no-ops/incorrect:
> - **`-freq` needs an integer `n`** (`elabutil.f90:624`, "frequency for aver/sum/min/max/std/rms"); the UI emits a bare `-freq` (defaults to 0). It only pairs meaningfully with an aggregation op.
> - **`-flux` is NOT a valid `.shy` shyelab option.** Flux/transport analysis runs on **`.flx` files** (FLX type, `shyelab.f90:82`), with sections defined in the STR `$flux` section; node selection uses `-node <n1,n2,...>` or `-nodes <file>` (`elabutil.f90:464-468`).
>
> **Decide and record here:** (a) what frequency control the UI should expose (`n` as a count, plus which aggregation it modifies); (b) whether flux support means discovering `.flx` files + a node-list input, or is out of scope. G1 (frequency `n`) is safe to implement once (a) is decided. **G3's "remove flux" branch is a user-visible change — do NOT remove the `flux` operation without the domain owner's recorded sign-off; if undecided, leave it untouched and note it open.**

**Files:**
- Modify: `shyfem_ui/services/postprocess_logic.py:170-215` (`build_shyelab_options` — add kwargs)
- Modify: `shyfem_ui/pages/postprocess.py` (conditional `@render.ui` controls; `_build_options` at 461-488 passes them)
- Modify: `tests/test_postprocess_logic.py` (extend `TestBuildShyelabOptions`)

### Task G1: frequency `n` argument (fully implementable once the decision is recorded)
- [ ] **Test** in `tests/test_postprocess_logic.py` (note: `freq_n` does not exist on `build_shyelab_options` yet, so Step 1 fails with `TypeError` — that IS the red state):
```python
def test_frequency_emits_n_immediately_after_flag(self):
    opts = build_shyelab_options(
        operation="frequency", op_flags=["-freq"], freq_n=12,
    )
    i = opts.index("-freq")
    assert opts[i + 1] == "12"   # value follows the flag

def test_frequency_without_n_has_no_trailing_value(self):
    opts = build_shyelab_options(operation="frequency", op_flags=["-freq"])
    i = opts.index("-freq")
    # -freq must be last OR followed by a non-numeric option, never a stray number.
    assert i == len(opts) - 1 or not opts[i + 1].lstrip("-").isdigit()
```
- [ ] Run → FAIL (`TypeError: unexpected keyword 'freq_n'`). Add `freq_n: int | None = None` kwarg; when set and `-freq` present, insert `str(freq_n)` immediately after the `-freq` token. Run → PASS. Commit.

### Task G2: frequency UI control
- [ ] Add a `@render.ui` numeric input shown only when `input.operation() == "frequency"` (mirror `custom_options_field` at `postprocess.py:354-362`); `_build_options` passes `freq_n=input.freq_n()`. Add a Playwright assertion that the field appears for the frequency op. Commit.

### Task G3: flux (gated on domain decision)
- [ ] **If in scope:** add `flux_nodes: str | None` kwarg emitting `-node <list>`; add `.flx` discovery to `discover_shy_files` (or a sibling `discover_flx_files`) and a node-list text input. **If out of scope:** remove `flux` from `SHYELAB_OPERATIONS` (postprocess.py:81-90) and note in the followups doc that flux belongs to a future FLX-file workflow. Commit the chosen path.

**Phase G self-check:** all new option-builder branches unit-tested; the UI control appears only for the relevant op; flux decision recorded in `docs/followups/`.

---

## Phase E — Service-layer naming consistency

**Goal:** Reduce suffix drift without high-blast-radius churn. **Scope deliberately narrow (YAGNI):** the `_logic`/`_loader`/`_builder`/`_utils`/`_wrapper`/`parser_*`/`project_*`/`job_*` families are internally consistent — leave them. Only the genuinely inconsistent **low-blast bare names** get renamed; high-blast modules (`parser_str` 22 sites, `access_control` 25, `project_context` 18, `shyfem_wrapper` 17) are **out of scope**.

**Files:** rename `services/workflow.py` → `services/workflow_service.py` (5 sites) and `services/report.py` → `services/report_service.py` (4 sites); document the accepted taxonomy in `services/__init__.py` docstring.

### Task E1: rename `workflow.py`
- [ ] `git mv shyfem_ui/services/workflow.py shyfem_ui/services/workflow_service.py`. Update all import sites — **including `services/__init__.py:23`** which re-exports `WorkflowEngine`/`WORKFLOW_TEMPLATES` from `services.workflow` (breaking the public `from shyfem_ui.services import WorkflowEngine` API otherwise). Grep `services.workflow` (not just the page imports) to catch `__init__.py`. Run full suite → PASS. Commit.

### Task E2: rename `report.py`
- [ ] `git mv shyfem_ui/services/report.py shyfem_ui/services/report_service.py`. Update all import sites — **including `services/__init__.py:21`** which re-exports from `services.report`. Run → PASS. Commit.

### Task E3: document the taxonomy
- [ ] Add a docstring block to `services/__init__.py` listing the accepted suffixes (`_service` = stateful service classes; `_logic` = page-extracted pure helpers; `_wrapper` = external-tool adapters; `parser_*` = file parsers; `job_*` = queue backends) so future modules are named consistently. Commit.

**Phase E self-check:** no remaining bare-name service modules except documented exceptions; full suite green (renames are behavior-preserving).

---

## Phase D — Split god modules

**Goal:** Split the five >1400-LOC modules into focused modules, preserving every public import path via re-export shims (existing tests import e.g. `compute_element_areas` from `services/mesh_builder.py`).

**Risk:** highest in the plan, and the tracker rates it LOW with explicit guidance to *"address incrementally as parts of these modules are touched for other reasons."* **Recommended scope: do D1 now (genuinely low-risk, already-pure, standalone value); treat D3–D5 as opt-in and gate each on an actual functional driver** (i.e. only split a page module when you're already in it for another change), per the tracker. Don't run D3–D5 as mandatory dedicated work with no driver — that's the gold-plating the strategic reviewers caution against. Do one module per task, move-then-shim-then-test, never touching behavior.

**Re-export shim rule (all D tasks):** use an **explicit** import list, never `import *` (star-import drops underscore-named functions that tests import directly).

**Prerequisite for D3:** `pages/visualize.py`'s `_plotly_netcdf`/`_build_vertical_profile`/`_build_transect` read `input.*` internally — refactor those to take plain args BEFORE splitting (a Phase-A-style extraction, Task D2), else the split can't be clean.

**Circular-import boundary (D5):** when creating `pages/mesh_builder_ui.py`, it must import only from `services/` and `components/` — **never back from `pages/mesh_builder.py`** (which becomes a consumer of the UI module). A back-import creates a cycle once `mesh_builder.py` imports the UI builders.

**Split map (from research):**

| Source | New modules | Seam lines |
|---|---|---|
| `services/mesh_builder.py` (1600) | `mesh_boundary.py`, `mesh_triangulate.py`, `mesh_bathymetry.py`, `mesh_quality.py` + re-export shim in `mesh_builder.py` | 64-353 / 354-643 / 644-1202 / 1203-1600 |
| `pages/physics.py` (2445) | `services/physics_logic.py` (PHYSICS_PANELS + coercion), `physics_panels_core.py`, `physics_panels_transport.py`, `physics_panels_io.py` | 26-277 / 581-1129 / 1130-2020 / 1620-2445 |
| `pages/visualize.py` (1648) | `services/visualize_logic.py` (metadata helpers 42-152), `visualize_plots_ts.py`, `visualize_plots_nc.py`, `visualize_compare.py` | see research |
| `pages/mesh_builder.py` (1474) | `mesh_builder_ui.py` (_STEPS + 5 panels), server split by wizard stage; move `_prepare_upload_files` → service | 42-288 / stages |
| `pages/run.py`, `pages/simulation.py` | already largely extracted (Phase A) — split only if still >1400 after A | — |

### Task D1: split `services/mesh_builder.py` (lowest risk — already pure, no Shiny)
- [ ] **Step 1:** Create `mesh_quality.py` and move the quality/validation/metrics group (lines 1203-1600: `export_grd`, `validate_boundary`, `compute_element_quality`, `compute_element_areas`, `compute_min_angles`, `compute_mesh_stats`, etc.) verbatim.
- [ ] **Step 2:** In `services/mesh_builder.py`, add an **explicit** re-export list (NOT `import *` — star-import skips leading-underscore names, and `tests/test_mesh_builder.py:15-38` imports private functions like `_check_boundary_gates`, `_remove_ring_loops`). Enumerate every function imported by tests/pages:
```python
from shyfem_ui.services.mesh_quality import (  # noqa: F401 — re-export for compat
    _check_boundary_gates, _get_triangle_vertices, export_grd, validate_boundary,
    compute_element_quality, compute_element_areas, compute_min_angles,
    compute_mesh_stats, check_bathy_extent, summarize_depth_stats,
    warn_if_degenerate_bathy, _boundary_to_polygon,
)
```
First grep `from shyfem_ui.services.mesh_builder import` across `shyfem_ui/` + `tests/` to build the complete list. So `grid_prep.py:28-33` and `tests/test_grid_inspect.py`/`test_mesh_builder.py` imports keep working.
- [ ] **Step 3:** Run `... pytest tests/test_grid_inspect.py tests/test_mesh*.py -v` → PASS (no behavior change).
- [ ] **Step 4:** Repeat for `mesh_bathymetry.py` (644-1202), `mesh_triangulate.py` (354-643), `mesh_boundary.py` (64-353), re-exporting each.
- [ ] **Step 5:** Commit per extracted module.

### Task D2: prerequisite refactor — make visualize plot builders pure
- [ ] Extract `input.*` reads out of `_plotly_netcdf`/`_build_vertical_profile`/`_build_transect`: change signatures to accept the values as plain args; the page reads `input.*()` and passes them. Add unit tests for the now-pure builders. Commit. (This unblocks D3.)

### Task D3: split `pages/visualize.py`
- [ ] Move metadata helpers (42-152) to `services/visualize_logic.py` (Phase-A style, unit-tested); move figure builders into `visualize_plots_ts.py`/`visualize_plots_nc.py`/`visualize_compare.py`; re-export from `visualize.py`. Run Playwright visualize tests → PASS. Commit per module.

### Task D4: split `pages/physics.py`
- [ ] Move `PHYSICS_PANELS` + `build_panel_params` + value coercion (`_read_input_and_set` core) to `services/physics_logic.py` (unit-test the coercion). Move panel render functions into the three `physics_panels_*` modules; the page imports + registers them. Run physics Playwright tests → PASS. Commit per module.

### Task D5: split `pages/mesh_builder.py`
- [ ] Move `_STEPS` + 5 `_step_*_panel` builders to `mesh_builder_ui.py`; move `_prepare_upload_files` (377-440) to `services/mesh_builder.py` (or `mesh_upload.py`) + unit-test it; split server handlers by wizard stage. Run mesh-builder Playwright tests → PASS. Commit per module.

**Phase D self-check:** after every move, `grep` confirms all prior import paths still resolve (shims in place); the full test suite + all Playwright suites pass unchanged. If any module is still >1400 LOC, note it but do not force a riskier split.

---

## Phase L — Output-directory picker  *(DEFERRED — reference only)*

> 🛑 **STOP. DO NOT EXECUTE.** This phase is documented for completeness. It was killed twice by 8-agent reviews ("no consumer waiting"). Before writing ANY code here, confirm (a) a trigger condition below has fired AND (b) the user explicitly approved pickup. Otherwise skip this phase entirely.

**Trigger conditions** (from `docs/followups/...:174-181`): a concrete user complaint about the copy-paste-absolute-path workflow on partitioning/grid_prep/postprocess; OR a non-trivial change to one of those pages' output flow; OR a second picker abstraction is picked up.

**Goal:** Build `components/directory_picker.py` (parallel to `file_picker.py`) with a `+ Create` modal, wired to the 3 pages with `output_dir` inputs. Spec: `docs/superpowers/specs/2026-05-08-section-l-directory-picker-design.md` (DEFERRED; 8-agent review found ~50 issues, 11 critical).

**Mandatory pre-pickup corrections (the spec is unsafe as-written — bake these into the tasks):**
1. Pass `active_project: reactive.Value[ProjectContext | None] | None` into `directory_picker_server`, NOT `project_id` — eliminates the per-refresh DB query AND the `load_project_context(pid)` access-control bypass (95%-confidence security gap).
2. Re-run the `resolve_picker_path` containment guard (`file_picker.py:167-176`, `is_relative_to(root)`) on the resolved path **before** `mkdir` in the `+ Create` flow (symlink-escape via pre-existing `wd/runs → /etc`).
3. Use `Path.walk(follow_symlinks=False)` (3.12+) / `os.walk(followlinks=False)` instead of `rglob("*")` (symlink data-leak + infinite-loop).
4. Add `import logging`; use the canonical modal `footer=` slot pattern (`admin.py:370-383`); `maxlength=255` on the name input; null-byte/backslash/length checks in `_validate_new_dir_name`; return a tagged status from `list_project_directories` (don't collapse 5 failure modes to `[]`); handle the project-switch race during Create submit.
5. Decide the `file_picker.py` → `picker_helpers.py` rename (the shared helpers now serve both pickers) and add `"output_dir"` to `PickerTargetId` (`file_picker.py:183-190`).
6. Reconsider whether `+ Create` belongs in the picker at all vs. a separate `directory_create_button` keeping the picker read-only.
7. **Re-read the full 2026-05-08 spec review (all 8 reviewer reports) as a gating step** before writing any spec. Beyond the items above, the review also flagged: the factually-wrong `# Refresh + select` comment (comment rot); the silent cap-truncation indicator (deemed unshippable by multiple reviewers — surface it, don't hide it); and **four specific missing tests** that any new spec must include — project-switch refresh during the modal, mkdir-failure branch, `on_selected` firing on mkdir, and symlink-loop handling. Test files named `test_<page>_directory_picker.py` (symmetry with Section M's `_file_picker.py`).

### Task L1: pure helpers + tests
- [ ] TDD `list_project_directories(work_dir, cap=100) -> tuple[list[str], str]` (tagged status, symlink-safe walk) and `_validate_new_dir_name(name) -> tuple[bool, str | None]` (null-byte/backslash/length/`..`/leading-`/` rejection; allows nested `runs/RUN_001`). Tests cover each rejection + the cap-truncation indicator.

### Task L2: containment-guarded mkdir
- [ ] TDD a `safe_mkdir(work_dir, rel_name) -> str | None` that resolves and re-checks `is_relative_to(root)` before `mkdir(parents=True, exist_ok=True)`; test the symlink-escape case returns None.

### Task L3: component + page wiring
- [ ] Build `directory_picker_ui`/`directory_picker_server(active_project=..., on_selected=...)`; wire into partitioning/grid_prep/postprocess via `on_selected=lambda rel: fill_picker_input("output_dir", active_project.get() ..., rel)`. Add per-page Playwright tests (dropdown render, create-flow, project-switch refresh, mkdir-failure, symlink-loop). Test files named `test_<page>_directory_picker.py`.

**Phase L self-check:** all 6 pre-pickup corrections present; no `load_project_context(pid)` in the new server; mkdir guarded; tests for every failure branch.

---

## Phase M.1 — run.py job-poller DI seam  *(DEFERRED — reference only)*

> 🛑 **STOP. DO NOT EXECUTE.** Documented for completeness; killed twice by 8-agent reviews ("no consumer waiting, stub is stable"). Before writing ANY code, confirm (a) a trigger condition below fired AND (b) the user approved pickup. The mandatory Phase 0 (M1.0) below is itself gated on that approval. Otherwise skip this phase.

**Trigger conditions** (from `docs/followups/...:338-348`): a non-trivial change to `run_server`'s reactive surface needs e2e coverage the stub can't provide; OR observable stub-drift bug; OR a refactor of the polling cadence. Spec: `docs/superpowers/specs/2026-05-06-section-m1-run-server-job-poller-di-design.md` (DEFERRED; 8-agent review, ~30 defects).

**Goal:** Replace `_stub_run_server` (`tests/_test_app.py:48-146`, mounted at line 275) with a DI seam so the *real* `run_server` mounts in tests with a no-op poller, eliminating stub-drift.

### Task M1.0: Phase 0 — confirm the deadlock-causer (REQUIRED FIRST, ~30 min, throwaway branch)
- [ ] In a throwaway branch, extend `_stub_run_server` to add ONE real effect at a time — event-gated handlers first (idle by construction), then `_on_tutorial_context`, then `_auto_refresh` LAST. If everything except `_auto_refresh` mounts cleanly, the hypothesis holds → proceed. **If something else also deadlocks, STOP — the M.1 design is materially wrong and needs re-architecture.** Do not write product code until this is confirmed.

**Pre-pickup action #2 (REQUIRED, from tracker — was missing): compare the two designs before committing.** The tracker mandates evaluating the factory-closure design AGAINST an independent reviewer's lighter alternative — `polling_enabled: reactive.value(True)` (single-boolean DI-lite: one closure capture, far less surface to test) — and choosing deliberately. Do NOT default to the 7-arg factory without this comparison. Record the choice + rationale before M1.1.

**Mandatory pre-pickup corrections (spec defects — bake in):**
- Factory (if the factory design is chosen) belongs in `services/run_logic.py`, NOT `pages/run.py`.
- `JobPollerFn = Callable[[], Awaitable[None]]` from `collections.abc`, not `typing`.
- Construction-order: `workflow_engine` (run.py:1140), `active_workflow_id` (1141), `_refresh_tick` (1142) are defined LATE — call the factory only AFTER line **1142**, else `UnboundLocalError`.
- Tests: `asyncio_mode="auto"` → use `async def` tests (not `asyncio.run`); `reactive.Value.get()` needs a reactive context → use `reactive.isolate()` or mock. `tests/test_run_helpers.py` already exists — extend it. Include the production-smoke test for the `job_queue.list_jobs(limit=50, ...)` call shape and multi-cycle / workflow-engine sub-branch / DI-seam tests.
- `lambda: None` is NOT a valid `JobPollerFn` (`await None` raises) — use a real `async def _noop_job_poller(): return`.
- Silent `try/except + logger.debug` in `_auto_refresh` → `warning` minimum. Clean up comment rot ("today's _auto_refresh body", "See Section M.1 design").

### Task M1.1: factory in run_logic
- [ ] TDD `_make_default_job_poller(...)` in `services/run_logic.py` returning an `async def _poll()` that ports the `_auto_refresh` body verbatim (`run.py:513-530`). Test with `reactive.isolate()`/mocks: multi-cycle, workflow-active sub-branch, exception path.

### Task M1.2: wire seam into run_server
- [ ] Add `job_poller: JobPollerFn | None = None` kwarg to `run_server` (`run.py:247-257`); after line 1141 default it to the factory; `@reactive.effect async def _auto_refresh(): await job_poller()`. Run full suite. Commit.

### Task M1.3: delete the stub
- [ ] Replace `_stub_run_server` mount (`_test_app.py:275`) with the real `run.run_server("run", config, job_queue, active_project=..., tutorial_context=..., user_role=None, job_poller=_noop_job_poller)`; add module-level `async def _noop_job_poller(): return`. Delete `_stub_run_server` (48-146). Run all Playwright suites → PASS (no stub-drift possible). Commit.

**Phase M.1 self-check:** Phase 0 confirmed before any product change; the real `run_server` mounts in tests; stub deleted; e2e run coverage exists.

---

## Phase P3 — IBM-LGR enhancements

From `docs/plans/2026-03-03-ibm-lgr-integration-design.md:195-200` (P3, out of scope at the time).

### Task P3.1: Ensemble results column/variable selector
- [ ] In `pages/ensemble.py` results view, add a column/variable selector (multi-select) driving which result columns render. TDD the pure column-filter helper in a `services/` module; add a Playwright assertion. Commit.

### Task P3.2: Compare page time-series file picker
- [ ] Wire `file_picker_server` + `fill_picker_input` into `pages/compare.py` for its time-series file inputs (same pattern as the 7 existing picker pages). Add a Playwright test. Commit.

### Task P3.3: Interactive map click-to-place release points
- [ ] In `pages/ibm.py`, capture map-click coordinates (deck.gl/ipyleaflet click event) and append release points to the IBM config. TDD the pure "append release point" reducer; manual UI verification for the click handler (per CLAUDE.md UI-testing rule). Commit.

**Phase P3 self-check:** each enhancement has a pure-helper unit test where logic exists; UI-only pieces are manually verified in a browser.

---

## Cross-cutting self-review (run after the full plan executes)

1. **Spec coverage:** every tracker item maps to a phase or a documented status — A,C,D,E,F,G,H,I,J,K + P3 are actionable phases; **B is already COMPLETE** (Section M rollout, not a phase); Section M / M.2 are COMPLETE/CLOSED; **L and M.1 are DEFERRED reference-only** (STOP-gated, not executed). ✔
2. **Decision gates honored:** Phase F is a BLOCKING decision (drop vs. in-house vs. prometheus) with the no-consumer caveat surfaced; Phase G is a BLOCKING domain decision (flux removal needs sign-off); Phases L & M.1 carry inline STOP gates and run only on a fired trigger + user approval. The deferred banner is hoisted to the header.
3. **Pattern fidelity:** every extraction lands in `services/*_logic.py` (or `*_service.py`), is re-exported from its page, and is unit-tested in `tests/test_*_logic.py` — matching the `2026-04-30` Section-A commits.
4. **Backward-compat:** every god-module split preserves prior import paths via shims; renames (Phase E) update all sites.
5. **Update the tracker:** as each phase closes, mark the corresponding item in `docs/followups/2026-04-29-ui-deep-review-deferred.md` CLOSED with the commit hash.
