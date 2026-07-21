# Batch 4: UI Security Hardening & CI Honesty — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Python with a test suite — TDD mandatory (RED+GREEN evidence per task). This batch is security-sensitive: several tasks must NOT break the documented laguna deployment — when a fix would, escalate with the real mechanism instead of shipping it.

**Goal:** Fix 17 Batch-4 items + the F17 carry-over from Batch 3. Security: N43 username-slug, N44/F15 tutorial-project confinement, N45 login timing oracle, F14 WS loopback fail-open, F16 symlink TOCTOU, F44 home_dir containment, F45 logout CSRF, F46 X-Forwarded-For trust, F47 feedback validation, F52 feedbacks pruning, plus F17 (home/compare/app job listing by user_id). Test integrity: N50 conftest PRAGMA scoping, N51/N52 resurrect dead tests. CI (user-approved): N49 MPI run-smoke, F26 drop E2E `--reruns 2`, F53 coverage gate.

**Tech stack:** Python 3.13 (`/opt/micromamba/envs/shiny/bin/python`), Shiny for Python, SQLAlchemy, ASGI middleware, pytest. Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`. Lint: `... -m ruff check shyfem_ui tests && ... -m black --check <touched files>`.

## Global Constraints

- TDD per task (RED pasted). Suite floor at Batch-4 start = record in Task 0 (Batch 3 ended at 2228 passed / 10 skipped; re-baseline on this branch).
- **Do not break laguna prod.** The documented deployment: nginx → Shiny Server (:3838) → Python app at `/shyfem-ui/`; `SHYFEM_UI_ROOT_PATH=/shyfem-ui`; WS identity uses server-minted `_wsauth` tokens (Phase 3B) delegating to session validation. Tasks touching WS auth (F14) and confinement (N44) MUST preserve: (a) the cookieless Shiny-Server internal WS handshake, (b) the bootstrapped Mar Menor tutorial project reachable by the tutorial user. If a fix can't satisfy both, escalate.
- Server-validated identity only (never client-pushed `input.*` role/user signals). conftest pins a temp DATABASE_URL — never touch the real `shyfem-ui/shyfem_ui.db`.
- Never touch/stage `src/tools/shynetcdf/` or `testcases/examples/mar_menor/mm_hyd_conz.*`.
- Branch `fix/b4-ui-security-ci` off `fix/b3-ui-jobs-data` (stacked #40←#41←#42←#43←this). One commit per task; ruff+black clean.
- Finding details: `docs/reviews/2026-07-18-full-codebase-deep-review.md` §2-3 — read the row before implementing.

---

### Task 0: Branch + baseline

- [ ] `cd /home/razinka/shyfem && git checkout -b fix/b4-ui-security-ci`
- [ ] Run full suite; record pass/skip counts + ruff/black state as this batch's floor.

### Task 1: N43 + F44 — username slug validation everywhere it's a path segment

**Files:** `shyfem_ui/services/auth_service.py` (`create_user`), `shyfem_ui/config.py` (`confine_path`), `shyfem_ui/models/user.py` (`home_dir`); tests: `tests/test_auth_service.py`, `tests/test_config.py`, `tests/test_user_model.py`

The bug: `confine_path` builds `home = (root / user["username"]).resolve()`; a username of `.` → `root/.` → `root`, and the `home != root` guard passes it (they're equal), collapsing confinement to the whole data root. `create_user` does no username validation at all; `home_dir` uses bare `startswith` (F44: `/data` matches `/data-evil`).

- [ ] **RED:** (a) `create_user(username=".")`, `".."`, `"a/b"`, `"a\x00b"`, `""`, `"foo bar"` each raise ValueError; a valid `"user_1.x-y"` succeeds. (b) `confine_path` with `user={"username":"."}` (or `".."`) raises (does not collapse to root). (c) `home_dir` rejects a username that is a `startswith`-but-not-`is_relative_to` sibling (`../data-evil` style) — assert containment via `Path.is_relative_to`.
- [ ] **GREEN:** add a module-level `USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")` and a `_MAX_USERNAME_LEN`; reject `.`/`..` explicitly (regex allows them). Validate in `create_user` (before any DB work) AND defensively in `confine_path` (raise if `user["username"]` fails the check). `home_dir`: replace `startswith` with `result.is_relative_to(root)` (still `resolve()` first). Keep messages user-safe.
- [ ] Suite + lint; commit `fix(ui): validate username slug at creation and in path confinement (N43, F44)`.

### Task 2: N45 — constant-time login (no user-existence timing oracle)

**Files:** `shyfem_ui/services/auth_service.py` (`authenticate`); tests: `tests/test_auth_service.py`

`authenticate` returns None immediately when the user is missing or inactive, skipping the password hash verification → a timing side-channel reveals valid/active usernames.

- [ ] **RED:** a test that `authenticate` performs a hash verification even when the user is missing/inactive — assert `verify_password` (or the argon2 verifier) is invoked against a dummy hash in all three branches (missing, inactive, wrong-password). (Mock the verifier; assert call happened; do not assert wall-clock timing — flaky.)
- [ ] **GREEN:** compute a module-level dummy hash once (`_DUMMY_HASH = _ph.hash("x")`); when user is None or inactive, still call the verifier against `_DUMMY_HASH` (ignore result) before returning None. Keep the real path unchanged.
- [ ] Suite + lint; commit `fix(ui): constant-time authenticate closes username-enumeration timing oracle (N45)`.

### Task 3: F14 — WS loopback fail-open (INVESTIGATE FIRST; escalate if prod-breaking)

**Files:** `shyfem_ui/middleware/session_auth.py` (WS branch ~615-640); tests: `tests/test_session_auth*.py`

Current: an unauthenticated WS is admitted when `self.root_path and is_local` (127.0.0.1/::1). The concern: any process on the box (or an attacker pivoting through the proxy) could open an unauthenticated WS.

- [ ] **STEP 0 — trace the real WS identity flow before changing anything.** Read how `_wsauth` tokens (Phase 3B) reach the server and how `resolve_ws_user`/`validate_ws_token` interact with THIS middleware branch. Determine: does the Shiny-Server internal WS carry a `_wsauth` token (query string) that this branch could validate, or does it genuinely arrive with no credential? Write the finding into the report BEFORE coding.
- [ ] **DECISION:**
  - If the internal WS can present a valid `_wsauth`/session token: tighten the branch to admit loopback ONLY when that token validates (remove the credential-free fail-open); keep the `code:4001` close otherwise. RED test: loopback WS with no/invalid token is closed; loopback WS with a valid token passes.
  - If closing it would break the documented cookieless internal WS (no credential path exists): DO NOT ship a prod-breaking change. Escalate (report NEEDS_CONTEXT) with the exact handshake evidence, and propose the minimal safe hardening (e.g. also require a shared internal secret / restrict to the exact proxy client, documented) for controller decision.
- [ ] Suite + lint; commit `fix(ui): WS loopback admits only credential-validated sessions (F14)` (or escalate).

### Task 4: N44 + F15 — tutorial / shared-project confinement

**Files:** `shyfem_ui/config.py` (`confine_path` allowed_roots), possibly `shyfem_ui/services/access_control.py`; the relocation script for F15; tests: `tests/test_config.py`, sharing/access tests

Per the roadmap: PR#29 confine_path excludes the shared `work_dir` where the bootstrapped tutorial project (owned by admin, shared to the tutorial user) lives, so the tutorial user's postprocess/visualize/simulation get "outside your home" errors. The relocation migration alone can't fix it (it moves projects to the OWNER's home = admin, still outside the tutorial user's allowlist).

- [ ] **RED:** the tutorial user (holding an accepted ProjectPermission on the admin-owned tutorial project) can `confine_path`-read a file under that project's work_dir; a user with NO permission on it is still denied; write access for a tutorial/viewer role stays denied (read-only).
- [ ] **GREEN:** make confinement shared-project-aware — extend `allowed_roots` (read paths) to include the `work_dir` of any project the acting user holds an accepted ProjectPermission on, read-only for tutorial/viewer roles. Derive the permission set server-side from the user identity (never a client signal). Keep the per-user home as the only WRITE root. F15 companion: wire/run the relocation migration for legacy owner access (separate, doesn't fix the tutorial-share case — note that explicitly).
- [ ] Suite + lint; commit `fix(ui): confinement allows read of shared projects the user has permission on (N44, F15)`.

### Task 5: F16 — validate_path symlink TOCTOU

**Files:** `shyfem_ui/config.py` (`validate_path`, `validate_save_path`); tests: `tests/test_config.py`

They call `resolve(strict=True)` only when the target already exists, skipping symlink resolution for nonexistent targets — a symlink whose parent escapes confinement can be created/targeted between check and use.

- [ ] **RED:** a path whose nonexistent leaf sits under a symlinked parent that points outside the allowed root is currently accepted; assert it's rejected (resolve the nearest EXISTING ancestor strictly, then verify containment).
- [ ] **GREEN:** resolve the nearest existing ancestor (`resolve(strict=True)` on the deepest existing parent) and re-check containment against it; never skip symlink resolution just because the leaf doesn't exist yet. Apply to both functions.
- [ ] Suite + lint; commit `fix(ui): validate_path resolves the nearest existing ancestor to close symlink TOCTOU (F16)`.

### Task 6: F45 + F46 — logout CSRF + X-Forwarded-For trust

**Files:** `shyfem_ui/middleware/session_auth.py` (logout route, `_client_ip`), `shyfem_ui/config.py` (trusted-proxy config field); tests: `tests/test_session_auth*.py`

- [ ] **RED:** (a) `GET /logout` no longer destroys the session by itself (returns a confirm page / method-not-allowed for the mutation); `POST /logout` with the session performs logout. (b) `_client_ip` returns the socket peer, NOT the X-Forwarded-For value, when the peer is not in a configured trusted-proxy list; honors XFF only from a trusted peer.
- [ ] **GREEN:** (a) make logout a CSRF-safe POST — `GET /logout` renders a small confirm page whose form POSTs; `_handle_logout` runs only on POST. (Keep root_path-aware redirects.) (b) add `trusted_proxies` config (default the loopback/nginx addr used on laguna); `_client_ip` honors XFF only when `scope["client"][0]` ∈ trusted_proxies, else returns the peer.
- [ ] Suite + lint; commit `fix(ui): CSRF-safe POST logout; trust X-Forwarded-For only from configured proxies (F45, F46)`.

### Task 7: F47 + F52 — feedback validation + retention

**Files:** `shyfem_ui/services/feedback_service.py`, `shyfem_ui/services/maintenance.py`, `shyfem_ui/config.py` (retention field if needed); tests: `tests/test_feedback_service.py`, `tests/test_maintenance.py`

- [ ] **RED:** (a) `create` rejects a malformed `contact_email` (basic RFC-ish check) and strips/escapes control chars in title/description beyond length clipping (assert a clearly-invalid email raises or is normalized to empty; assert control bytes removed). (b) maintenance prunes `feedbacks` older than a retention window (add a `FeedbackService.cleanup_old(days)` and wire it into `run_maintenance` alongside jobs/sessions/audit, offloaded via `asyncio.to_thread`).
- [ ] **GREEN:** implement the email-format check (reuse any existing validator; else a conservative regex) and content sanitation; add `cleanup_old` + the maintenance wiring + a `feedback_retention_days` config default.
- [ ] Suite + lint; commit `fix(ui): validate feedback email/content; prune old feedbacks in maintenance (F47, F52)`.

### Task 8: N50 + N51 + N52 — test-suite integrity

**Files:** `tests/conftest.py`, `tests/test_mesh_builder.py`; possibly a new small test

- [ ] **N50:** the session-wide `@event.listens_for(Engine, "connect")` PRAGMA listener means EVERY engine (incl. any the suite builds to mimic production) enforces FKs — so `test_db_fk.py`'s pin on *production's* connect-listener can't actually fail if production regressed. Scope the PRAGMA to test-built engines only (e.g. register on the specific test engines/fixtures, not the global `Engine` class), and add a test asserting the PRODUCTION engine factory (`base.get_engine`) registers the FK listener itself (so the guarantee comes from prod code, not the test harness). RED: a test that would pass even with prod's listener removed currently; after the fix, removing prod's listener makes a test fail.
- [ ] **N51:** `test_contour_crs_parse_failure_is_error` (added in HEAD 73e03b2) lives inside `TestCuronianIntegration`, which is `skipif(not _HAS_CURONIAN)` — but the test uses only tmp_path+monkeypatch and needs no Curonian data. Move it OUT into an always-run class so the CRS-failure regression actually runs. RED: assert (via collection or a marker check) the test is not skipped in the default suite.
- [ ] **N52:** `_CURONIAN_DIR` points at `testcases/examples/curoninan` (typo for `curonian`). Fix the typo; if the real dir/data isn't in the repo, keep the `skipif` but make the skip HONEST — and add a CI-independent test asserting the path is spelled correctly (so a future data drop actually enables the block instead of silently staying skipped on a typo).
- [ ] Suite + lint; commit `fix(ui): scope test FK PRAGMA to test engines; resurrect CRS + Curonian tests (N50, N51, N52)`.

### Task 9: F17 (Batch-3 carry-over) — user_id job scoping in home/compare/notifications

**Files:** `shyfem_ui/pages/home.py` (~370), `shyfem_ui/pages/compare.py` (~135), `shyfem_ui/app.py` (~1011); tests: page/notification tests

Batch 3 fixed run.py to scope job listings by server-validated `user_id`; these three still scope by `str(id(session))` (post-N13 a user's jobs drop off after reconnect, and `id()` reuse can surface a prior user's job metadata).

- [ ] **RED:** in server mode, each of the three listings returns only the requesting (server-validated) user's jobs; a second user's jobs never appear; unresolved identity → empty (fail-closed). Reuse run.py's `_list_scoped_jobs`/`compute_*` pattern (extract to a shared helper if it isn't already importable).
- [ ] **GREEN:** migrate the three call sites from `session_id=str(id(session))` to `user_id=<validated user id>` (admin all-jobs preserved where those pages already offer it). Local mode unchanged.
- [ ] Suite + lint; commit `fix(ui): scope Dashboard/Compare/notification job listings by user_id (F17 completion)`.

### Task 10: N49 + F26 + F53 — CI honesty (user-approved workflow edits)

**Files:** `.github/workflows/fortran-ci.yml` (N49), `.github/workflows/ui-ci.yml` (F26, F53)

- [ ] **N49:** after the mpi-build job compiles, add a smoke step that actually RUNS it: `PATH=/usr/bin:$PATH` OpenMPI pin, `cd testcases/examples/mar_menor && make init && mpirun --oversubscribe -np 2 shyfem mm_hyd_00.str`, asserting clean completion (this repo's own "build compiles ≠ build runs" trap). Keep it a distinct step so a run failure is attributable.
- [ ] **F26:** remove `--reruns 2 --reruns-delay 3` from the E2E pytest invocation — OR, if flakiness is real, keep reruns but add `--reruns-report`-style capture and fail when a test only passes on retry. Prefer removal; if that reddens known-flaky E2E, document which and keep a MINIMAL rerun with a recorded justification.
- [ ] **F53:** add `--cov-fail-under=<current baseline>` to the coverage invocation — measure the current coverage first, pin the gate one point below it (avoid immediate red), so future drops fail. State the number in the report.
- [ ] Validate YAML locally (`python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"`); commit `ci: run the MPI binary in fortran-ci; drop masking E2E reruns; enforce coverage floor (N49, F26, F53)`.

### Task 11: Verify + roadmap tick + final reviews + PR

- [ ] Full suite (paste count vs Task 0 floor), ruff+black clean.
- [ ] Tick Batch 4 in the roadmap checklist (` — DONE (commits <range>)`); commit.
- [ ] (Controller) final whole-branch review (most capable model) + a dedicated **ui-security-reviewer** pass — both are exit criteria; one fix subagent for combined Critical/Important.
- [ ] (Controller) push + `gh pr create --base fix/b3-ui-jobs-data` with summary/test plan; note any escalated item (F14) status.

## Self-review notes

- Coverage: N43+F44→T1, N45→T2, F14→T3, N44+F15→T4, F16→T5, F45+F46→T6, F47+F52→T7, N50+N51+N52→T8, F17→T9, N49+F26+F53→T10. 18 items.
- Highest-risk tasks: T3 (WS — may escalate rather than ship), T4 (tutorial confinement — must keep tutorial reachable). Both carry explicit "don't break laguna / escalate" instructions.
- CI edits (T10) are user-approved (this session). Exit criteria require the ui-security-reviewer to pass clean.
