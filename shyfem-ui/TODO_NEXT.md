# SHYFEM-UI — Next Phase Improvement Plan

**Created:** 2026-02-13
**Baseline:** Phases 1–8 complete (200 passing, 1 failing, 94 skipped tests)
**Scope:** Code health, hardening, Docker, performance, accessibility, CI/CD

---

## Phase 9: Fix Failing Test & Test Environment Isolation

> The test suite has **1 failure** caused by an environment variable leaking
> into the test process, and **94 skipped** Playwright tests that never run.

- [x] **9.1** Fix `test_config.py::test_default_deployment_mode` failure
  - Root cause: the host machine has `SHYFEM_UI_DEPLOYMENT_MODE=server` set
    in the shell environment. `Config()` (Pydantic) picks it up automatically.
  - Fix: in `tests/conftest.py` add a session-scoped autouse fixture that
    patches `os.environ` to remove all `SHYFEM_UI_` prefixed variables (or
    sets `SHYFEM_UI_DEPLOYMENT_MODE=local`) before any test runs.
  - Alternatively, update `test_config.py` tests to explicitly use
    `Config(_env_file=None, deployment_mode="local")` so they don't depend
    on the host environment.
  - File: `tests/test_config.py` (~line 17)

- [x] **9.2** Make Playwright E2E tests runnable in CI
  - 94 tests are currently skipped because `playwright` browsers aren't
    installed. Add a `conftest.py` marker/condition that auto-installs
    browsers in CI or clarifies the skip reason.
  - Add `playwright install chromium --with-deps` to the CI pipeline / a
    Makefile target.
  - Document: `README.md` should include a "Run E2E tests" section.

- [x] **9.3** Add `pytest-cov` coverage report to test run
  - Add `--cov=shyfem_ui --cov-report=term-missing` to `pytest.ini_options`.
  - Goal: establish baseline coverage percentage (currently estimated ~40%
    because pages/components have zero unit-test coverage).

---

## Phase 10: Lint & Code Hygiene Cleanup

> Ruff reports **77 issues** (28 unused imports, 7 unused variables, 35 long
> lines, 4 import-ordering, 2 empty f-strings, 1 ambiguous variable name).

- [x] **10.1** Remove 28 unused imports (auto-fixable: `ruff check --fix`)
  - Files affected: `app.py`, `boundary_editor.py`, `log_viewer.py`,
    `plot_widget.py`, `str_editor.py`, `timeseries.py`, `compare.py`,
    `ensemble.py`, `grid_prep.py`, `home.py`, `partitioning.py`,
    `postprocess.py`, `run.py`, `simulation.py`, `visualize.py`,
    `job_local.py`, `report.py`, `workflow.py`

- [x] **10.2** Fix 7 unused local variables
  - `components/grid_map.py:293` – `config` dict never used
  - `components/grid_map.py:106` – `bounds` assigned but never read
  - `pages/run.py:376` – `total` computed but never rendered
  - `pages/visualize.py:432` – `dims` assigned but not consumed
  - `services/job_celery.py:278` – `app` result not used
  - `services/shyfem_wrapper.py:228` – `stderr_lines` never read
  - `services/report.py:187` – `name` shadowed and unused

- [x] **10.3** Fix 2 f-strings with no placeholders (`F541`)
  - Inspect and convert to plain strings or add intended variables.

- [x] **10.4** Fix 4 module-level import ordering issues (`E402` in `app.py`)
  - Move logger assignment below all imports, or restructure the import block.

- [x] **10.5** Address `E741` ambiguous variable name (1 occurrence)
  - Rename single-letter variable (likely `l` → `layer` or similar).

- [x] **10.6** Migrate ruff config from deprecated top-level keys
  - `pyproject.toml`: move `select`, `ignore` under `[tool.ruff.lint]`.

---

## Phase 11: Dockerfile & Deployment Hardening

> The Dockerfile references a deleted `requirements.txt` and uses `pip`
> instead of the conda/micromamba environment. Docker-compose has issues too.

- [ ] **11.1** Fix Dockerfile — references non-existent `requirements.txt`
  - Stage 1 runs `COPY requirements.txt .` and `pip install -r requirements.txt`.
    This file was deleted per Phase 2 recommendations.
  - Options: (a) use `pip install .` with `pyproject.toml`, or (b) use
    `mambaorg/micromamba` base image and `COPY environment.yml`.
  - Recommended: option (b) to align with the micromamba deployment strategy
    documented in `CODEBASE_ANALYSIS.md`.

- [ ] **11.2** Pin Python version consistently
  - `environment.yml` specifies `python=3.13`, `Dockerfile` uses
    `python:3.11-slim`, `pyproject.toml` classifiers list 3.10–3.12.
  - Standardize on **Python 3.12** across all three artifacts.

- [ ] **11.3** Docker Compose: fix unconditional `depends_on: redis`
  - The `shyfem-ui` service always depends on `redis`, but redis uses
    `profiles: [server]` meaning it won't start in default mode.
  - Fix: either remove the dependency or make `shyfem-ui` also conditional.

- [ ] **11.4** Add `.dockerignore` file
  - Exclude: `__pycache__/`, `.git/`, `*.egg-info/`, `tests/`, `.env`,
    `*.pyc`, `.ruff_cache/`, `.mypy_cache/`.

- [ ] **11.5** Add non-root user to Dockerfile
  - Currently runs as root. Add `RUN useradd -m appuser` and
    `USER appuser` for security hardening.

- [ ] **11.6** Add `SHYFEM_UI_AUTH_ENABLED=true` and a placeholder password
  to Docker Compose environment block with a warning comment.

---

## Phase 12: Unit Tests for UI Components & Pages

> Currently **zero unit tests** for any file under `pages/` or `components/`.
> Only service-layer code is tested. Pages contain significant business logic
> (parsing, file I/O, data transformation) that can be tested without a live
> Shiny server.

- [ ] **12.1** Test helper functions extracted from `pages/run.py`
  - `_format_eta()`, progress calculation logic, `_build_job_timeline()`
    Plotly figure builder — extract into testable pure functions if needed.

- [ ] **12.2** Test helper functions in `pages/postprocess.py`
  - `_parse_shyelab_info()` — provide sample Fortran output and assert
    parsed structure.

- [ ] **12.3** Test helper functions in `pages/visualize.py`
  - `_build_vertical_profile()`, `_build_transect()`, `_compare_netcdf()`
    — these return Plotly figures; test they produce valid `go.Figure`
    objects with expected trace counts.

- [ ] **12.4** Test `components/grid_map.py` → `build_mesh_figure()`
  - Provide a small synthetic `GrdFile`, assert figure has correct trace
    count (mesh, boundary, labels), axes labels, etc.

- [ ] **12.5** Test `components/timeseries.py` → `compute_statistics()`
  - Pure function — test with known DataFrame, assert min/max/mean/std/
    percentile values.

- [ ] **12.6** Test `components/boundary_editor.py` CSV parsing logic
  - Test the CSV import code that splits rows into node list, type, file,
    scale factor, interpolation.

- [ ] **12.7** Test `services/job_celery.py` health_check/worker_info
  - Mock Redis connection and Celery `app.control` to test without infra.

---

## Phase 13: Database & Model Improvements

- [ ] **13.1** Add Alembic migrations
  - Currently `Base.metadata.create_all()` creates tables on startup.
    This works for development but breaks on schema changes in production
    (columns added → old SQLite DB is incompatible).
  - Init Alembic: `alembic init migrations`, generate initial revision.
  - Update `init_db()` to run `alembic upgrade head` instead of
    `create_all()`.

- [ ] **13.2** Add `Job.output_files` JSON column
  - Currently `output_files` lives only in the in-memory `JobInfo` dataclass.
    Persisting it to the DB allows post-restart output file browsing.

- [ ] **13.3** Add cascading session cleanup
  - When a user session disconnects, mark orphaned RUNNING jobs as
    CANCELLED. Currently jobs run indefinitely if the browser closes.
  - Implement via `session.on_ended` callback in `_build_server`.

---

## Phase 14: Performance & Scalability

- [ ] **14.1** Add reactive caching for parsed grid files
  - `GrdParser.parse()` re-reads from disk on every reactive invalidation.
  - Wrap with `@reactive.calc` memoization keyed on file path + mtime.

- [ ] **14.2** Lazy-load page modules
  - Importing all 9 page modules at startup increases cold-start time.
  - Use `importlib.import_module()` inside `_build_ui` / `_build_server` to
    defer loading until the tab is visited.

- [ ] **14.3** Add WebSocket keepalive / reconnection handling
  - Long-running simulations (hours) may outlive WebSocket timeout.
  - Add `reconnect: true` option to the Shiny client or implement a
    heartbeat in `_WsDebugMiddleware`.

- [ ] **14.4** Rate-limit implementation
  - `Config.rate_limit_rpm` is defined (120 req/min) but never enforced.
  - Add ASGI middleware that tracks requests per session and returns 429.

---

## Phase 15: UX Polish & Accessibility

- [ ] **15.1** Add keyboard navigation to tab bar
  - `ui.navset_tab` should support arrow-key navigation between tabs.
  - Test with Playwright that Tab/ArrowRight cycles through pages.

- [ ] **15.2** Add loading spinners for long operations
  - Grid parsing, file loading, job submission currently show no feedback.
  - Use `ui.busy_indicators.use()` or add explicit `ui.output_ui` spinners.

- [ ] **15.3** Add user-facing error boundaries
  - Unhandled exceptions in reactive functions crash the session silently.
  - Wrap key server blocks with try/except → `ui.notification_show(type="error")`.

- [ ] **15.4** Add favicon and meta tags
  - No `<link rel="icon">` or `<meta name="description">` in the HTML head.
  - Use `ui.head_content(ui.tags.link(rel="icon", href="..."))`.

- [ ] **15.5** Add dark mode toggle
  - `shinyswatch` supports dark themes (e.g., `darkly`). Add a toggle in
    the navbar that switches `config.theme` and re-renders.

---

## Phase 16: CI/CD Pipeline

- [ ] **16.1** Create GitHub Actions workflow: `.github/workflows/ci.yml`
  - Steps: checkout → setup micromamba → install environment → lint →
    unit tests → coverage report.
  - Use `mamba-org/setup-micromamba@v2` action.

- [ ] **16.2** Add E2E test job to CI
  - Install Playwright browsers, start app, run Playwright tests.
  - Runs only on PRs touching `shyfem_ui/` or `tests/`.

- [ ] **16.3** Add Docker build check to CI
  - `docker build --target builder .` to catch Dockerfile regressions.

- [ ] **16.4** Add pre-commit hooks
  - Create `.pre-commit-config.yaml` with ruff, black, trailing whitespace.

---

## Phase 17: Documentation & Developer Experience

- [ ] **17.1** Add `CONTRIBUTING.md`
  - Dev setup instructions, code style guide, PR checklist.

- [ ] **17.2** Add `Makefile` with common targets
  - `make install`, `make test`, `make lint`, `make format`, `make e2e`,
    `make docker-build`, `make docker-run`.

- [ ] **17.3** Add inline architecture diagram to README
  - Mermaid diagram showing: App → Pages → Components → Services → DB.

- [ ] **17.4** Add API docstrings to all `__init__.py` public exports
  - Currently exports are listed but not documented.

---

## Implementation Priority

```
Phase 9  (Test fixes)         ~0.5 day   — Immediate (broken test)
Phase 10 (Lint cleanup)       ~0.5 day   — Quick wins, auto-fixable
Phase 11 (Docker)             ~1 day     — Blocks deployment
Phase 12 (Component tests)    ~2 days    — Quality gate
Phase 13 (DB migrations)      ~1 day     — Prevents data loss
Phase 14 (Performance)        ~1 day     — Scalability
Phase 15 (UX)                 ~1 day     — User-facing polish
Phase 16 (CI/CD)              ~1 day     — Automation
Phase 17 (Docs)               ~0.5 day   — Developer onboarding
```

## Verification Checklist (per phase)

1. `python3 -m pytest tests/ -v` — **0 failures, 0 unexpected skips**
2. `ruff check shyfem_ui/` — **0 errors**
3. `python3 -m shyfem_ui.app` — app launches without warnings
4. `docker build -t shyfem-ui .` — builds successfully
5. Navigate all 9 tabs in browser — no console errors
