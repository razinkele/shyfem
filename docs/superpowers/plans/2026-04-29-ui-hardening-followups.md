# UI Hardening Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 28+ findings from the 2026-04-29 deep review of the SHYFEM UI — security holes, auth bypasses, data-integrity gaps, observability blind spots, dead UI controls, and test-coverage gaps.

**Architecture:** 22 self-contained tasks grouped into 9 phases. Phases A (security) and B (data integrity) are highest-leverage and should land first. Each phase produces working, independently shippable software. Tasks within a phase are largely independent; cross-phase ordering is documented per-task where it matters.

**Tech Stack:** Python 3.13 + Shiny + SQLAlchemy + Alembic (UI); pytest + Playwright (tests). Test runner: `/opt/micromamba/envs/shiny/bin/python -m pytest` from `shyfem-ui/`.

---

## Findings Map

| # | Severity | Finding | Task |
|---|----------|---------|------|
| 1 | CRIT | CSRF cookie missing `HttpOnly` + `Secure` flags | 1 |
| 2 | CRIT | Zip-slip guard checks `".."` substring only | 2 |
| 3 | CRIT | `ProjectFile` missing `UNIQUE(project_id, rel_path)` | 5 |
| 4 | CRIT | `check_project_access` not enforced on 9 write-path pages | 8 |
| 5 | CRIT | `job_celery.py` reads `SHYFEM_UI_SHYFEM_DIR` directly, bypassing config | 4 |
| 6 | IMP | Celery vs local job-queue parity (no DB, no notifications) | 7 |
| 7 | IMP | `partitioning.py` UI controls (`partition_method`, `weighted`) are dead | 16 |
| 8 | IMP | `workflow.py` is in-memory only, lost on restart | 6 |
| 9 | IMP | 5 large pages have zero `logger.` calls | 9 |
| 10 | IMP | 5 large pages have zero unit tests | tracked (Task 22) |
| 11 | IMP | `components/str_editor.py` (823 LOC) has zero tests | 11 |
| 12 | IMP | `services/job_queue.py` abstract base has zero tests | 12 |
| 13 | IMP | Free-text file paths everywhere; `files.py` browser not wired as picker | tracked (Task 22) |
| 14 | IMP | Per-action access check missing on write paths | 8 |
| 15 | IMP | README env-var table 15+ entries out of date | 10 |
| 16 | SUG | argon2 `check_needs_rehash` not called on login | 3 |
| 17 | SUG | Reports use CDN Plotly — useless air-gapped | 21 |
| 18 | SUG | Pages do direct DB access | tracked (Task 22) |
| 19 | SUG | `services/mesh_builder.py:1298` deferred import from page | 20 |
| 20 | SUG | No "next step" navigation after job submit/postprocess | 19 |
| 21 | SUG | `tutorial_context` not passed to 5 pages | 18 |
| 22 | SUG | 14 source-string regression tests are brittle | 14 |
| 23 | SUG | Magic counts in `test_app_layout.py` | 15 |
| 24 | SUG | Flaky `test_job_local.py:176` xfail uses `asyncio.sleep` race | 15 |
| 25 | SUG | No metrics / request IDs / tracing | tracked (Task 22) |
| 26 | SUG | Service-layer naming inconsistency | tracked (Task 22) |
| 27 | SUG | God modules (>1400 LOC pages) | tracked (Task 22) |
| 28 | SUG | `postprocess.py` "frequency" / "flux" modes lack domain UI | tracked (Task 22) |
| U1 | UNIMPL | Partitioning "Manual assignment" method does same as METIS | 16 |
| U2 | UNIMPL | "Validate Partitions" only checks file size | tracked (Task 22) |
| U3 | UNIMPL | Ensemble result aggregation misses `.shy` binary output | 17 |
| U4 | UNIMPL | Compare time series uses free-text paths, no project picker | 17 |
| U5 | UNIMPL | `WorkflowStep.options` stores comments that are never executed | 6 (handled by deletion) |

**Recommended ordering:** Phase A (1–4) → Phase B (5–7) → Phase C (8) → Phase D (9–10) → Phase E (11–13) → Phase F (14–15) → Phase G (16–19) → Phase H (20–21) → Phase I (22).

**Out of scope (deferred via Task 22 follow-up tracking):** god-module splits, service-layer naming refactor, metrics/Prometheus integration, file-picker integration in every page, postprocess flux/frequency domain UI, batch-test-page coverage.

---

## Phase A — Critical Security Fixes (4 tasks, ~1 day)

### Task 1: CSRF cookie HttpOnly + Secure flags

**Files:**
- Modify: `shyfem-ui/shyfem_ui/middleware/session_auth.py:672`
- Modify: `shyfem-ui/tests/test_session_auth_middleware.py`

**Context:** The CSRF double-submit cookie omits `HttpOnly` (so XSS could steal it) and never gets `Secure` even when other cookies do. The double-submit pattern reads it server-side; no client JS needs access.

- [ ] **Step 1: Add failing test for CSRF cookie flags**

Append to `TestMiddlewareCsrf` (or create if missing):

```python
@pytest.mark.asyncio
async def test_csrf_cookie_has_httponly(self):
    auth_service = MagicMock()
    auth_service.authenticate.return_value = None
    mw = SessionAuthMiddleware(AsyncMock(), auth_service)
    scope = {"type": "http", "method": "GET", "path": "/login", "headers": []}
    sent = []
    async def send(msg):
        sent.append(msg)
    await mw._serve_login_page(send, error=None, root_path="")
    set_cookie_headers = [
        v.decode() for msg in sent if msg.get("type") == "http.response.start"
        for k, v in msg["headers"] if k == b"set-cookie"
    ]
    csrf_cookies = [h for h in set_cookie_headers if h.startswith("csrf_token=")]
    assert csrf_cookies, "Expected csrf_token Set-Cookie header"
    assert "HttpOnly" in csrf_cookies[0]

@pytest.mark.asyncio
async def test_csrf_cookie_secure_when_use_secure_cookies(self):
    auth_service = MagicMock()
    auth_service.authenticate.return_value = None
    mw = SessionAuthMiddleware(AsyncMock(), auth_service, use_secure_cookies=True)
    scope = {"type": "http", "method": "GET", "path": "/login", "headers": []}
    sent = []
    async def send(msg):
        sent.append(msg)
    await mw._serve_login_page(send, error=None, root_path="")
    set_cookie_headers = [
        v.decode() for msg in sent if msg.get("type") == "http.response.start"
        for k, v in msg["headers"] if k == b"set-cookie"
    ]
    csrf_cookies = [h for h in set_cookie_headers if h.startswith("csrf_token=")]
    assert csrf_cookies
    assert "Secure" in csrf_cookies[0]
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_auth_middleware.py::TestMiddlewareCsrf::test_csrf_cookie_has_httponly tests/test_session_auth_middleware.py::TestMiddlewareCsrf::test_csrf_cookie_secure_when_use_secure_cookies -v
```

- [ ] **Step 3: Fix the cookie**

In `shyfem-ui/shyfem_ui/middleware/session_auth.py:672`, find:

```python
csrf_cookie = f"csrf_token={csrf_token}; Path={cookie_path}; SameSite=Lax"
```

Replace with:

```python
csrf_cookie = f"csrf_token={csrf_token}; Path={cookie_path}; HttpOnly; SameSite=Lax"
if self.use_secure_cookies:
    csrf_cookie += "; Secure"
```

- [ ] **Step 4: Re-run tests — expect PASS, full middleware suite no regressions**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_auth_middleware.py -q
```

- [ ] **Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/middleware/session_auth.py shyfem-ui/tests/test_session_auth_middleware.py
git commit -m "fix(security): add HttpOnly+Secure flags to CSRF cookie"
```

---

### Task 2: Zip-slip resolved-path containment guard

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/project_export.py:90-92`
- Modify: `shyfem-ui/tests/test_project_export.py`

**Context:** Current guard at line 90 checks `".." in normalized.split("/")` — but a member like `subdir/../../../etc/passwd` has `..` components that may be absorbed by `Path` resolution; a member with absolute path `/etc/passwd` bypasses entirely; symlinks in the archive can also escape. Standard mitigation is to resolve the target and assert it stays inside the destination.

- [ ] **Step 1: Add failing tests for zip-slip variants**

Append to `tests/test_project_export.py`:

```python
class TestZipSlipDefenses:

    def _make_malicious_zip(self, tmp_path: Path, member_name: str) -> Path:
        import zipfile
        zip_path = tmp_path / "malicious.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(member_name, b"pwned")
        return zip_path

    def test_rejects_absolute_path_member(self, tmp_path):
        from shyfem_ui.services.project_export import import_project_zip
        zp = self._make_malicious_zip(tmp_path, "/etc/passwd")
        with pytest.raises(ValueError, match="path traversal"):
            import_project_zip(zp, tmp_path / "dest")

    def test_rejects_dotdot_member(self, tmp_path):
        from shyfem_ui.services.project_export import import_project_zip
        zp = self._make_malicious_zip(tmp_path, "../escape.txt")
        with pytest.raises(ValueError, match="path traversal"):
            import_project_zip(zp, tmp_path / "dest")

    def test_rejects_nested_dotdot_member(self, tmp_path):
        from shyfem_ui.services.project_export import import_project_zip
        zp = self._make_malicious_zip(tmp_path, "subdir/../../escape.txt")
        with pytest.raises(ValueError, match="path traversal"):
            import_project_zip(zp, tmp_path / "dest")

    def test_accepts_clean_relative_member(self, tmp_path):
        from shyfem_ui.services.project_export import import_project_zip
        zp = self._make_malicious_zip(tmp_path, "data/file.txt")
        # Clean member must not raise.
        import_project_zip(zp, tmp_path / "dest")
        assert (tmp_path / "dest" / "data" / "file.txt").exists()
```

- [ ] **Step 2: Run tests — expect FAIL on first 3, PASS on 4th**

- [ ] **Step 3: Replace the guard in `project_export.py`**

Find (lines 90–92):

```python
        normalized = Path(member).as_posix()
        if ".." in normalized.split("/"):
            raise ValueError(f"path traversal in archive: {member!r}")
```

Replace with:

```python
        if Path(member).is_absolute():
            raise ValueError(f"path traversal in archive (absolute): {member!r}")
        target = (project_dir / member).resolve()
        project_dir_resolved = project_dir.resolve()
        try:
            target.relative_to(project_dir_resolved)
        except ValueError:
            raise ValueError(
                f"path traversal in archive: {member!r} resolves outside {project_dir_resolved}"
            )
```

(Adjust variable names to match the surrounding function — the spec uses `project_dir` as the destination root; the function might call it `target_dir` or `dest`.)

- [ ] **Step 4: Re-run tests — expect all 4 PASS, full suite no regressions**

- [ ] **Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/project_export.py shyfem-ui/tests/test_project_export.py
git commit -m "fix(security): close zip-slip via resolved-path containment check"
```

---

### Task 3: Argon2 `check_needs_rehash` on login

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/auth_service.py:43-51` (`verify_password`) and the `authenticate` flow
- Modify: `shyfem-ui/tests/test_auth_service.py`

**Context:** `verify_password` uses `_ph.verify()` but never calls `_ph.check_needs_rehash()`. argon2-cffi's contract: when stored hashes use weaker parameters than current defaults, return True from `check_needs_rehash` so the caller can re-hash with current parameters and persist. Without this, hashes never upgrade.

- [ ] **Step 1: Add failing test**

```python
def test_authenticate_rehashes_when_needed(self, db_session):
    from argon2 import PasswordHasher
    from shyfem_ui.services.auth_service import AuthService
    from shyfem_ui.models.user import User

    # Create a hash with weaker-than-default parameters that needs_rehash
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    user = User(username="alice", email="a@x.com",
                password_hash=weak.hash("pw"), role="user")
    db_session.add(user); db_session.commit()
    old_hash = user.password_hash

    svc = AuthService(session_factory=lambda: db_session)
    result = svc.authenticate("alice", "pw")
    assert result is not None
    db_session.refresh(user)
    assert user.password_hash != old_hash, "expected hash to be rehashed with stronger params"
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Update `authenticate` to rehash when needed**

In `shyfem-ui/shyfem_ui/services/auth_service.py`, `_ph` is a **module-level** `PasswordHasher` instance (defined at line 20: `_ph = PasswordHasher()`), not `self._ph`. Reference it as `_ph` directly. Locate `authenticate`, and after `verify_password` succeeds and before returning, add:

**Imports.** `InvalidHashError` is already module-level in `auth_service.py:13–15` (with a compat shim for argon2 < 23 that aliases the older `InvalidHash` name). Reuse it — do **NOT** add a fresh `from argon2.exceptions import InvalidHashError` inside the function, which would bypass the shim and crash on older argon2. Add the two missing names to the existing top-of-file import block:

```python
# Add to existing imports near line 8 of auth_service.py:
from argon2.exceptions import HashingError  # already have InvalidHashError via shim above
from sqlalchemy.exc import SQLAlchemyError
```

Then in `authenticate`:

```python
        if _ph.check_needs_rehash(user.password_hash):
            try:
                user.password_hash = _ph.hash(password)
                session.commit()
                logger.info(
                    "Rehashed password for user %s with current argon2 params",
                    user.username,
                )
            except (HashingError, InvalidHashError, SQLAlchemyError):
                # Don't block login on rehash bookkeeping failure — user is
                # already authenticated. Narrow the catch to argon2 + DB
                # exceptions only; programming errors (NameError,
                # AttributeError, TypeError) will propagate and surface in
                # logs as bugs rather than being silently swallowed.
                logger.exception(
                    "Failed to persist rehashed password for user %s",
                    user.username,
                )
                try:
                    session.rollback()
                except SQLAlchemyError:
                    logger.exception("Rollback after rehash failure also raised")
```

The narrow exception scope (argon2 + SQLAlchemy errors only) was a deliberate change from the earlier broad `except Exception` — programming errors introduced by future refactors should crash the rehash block instead of silently logging "rehash failed."

- [ ] **Step 4: Re-run test — expect PASS, full auth suite no regressions**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_auth_service.py -q
```

- [ ] **Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/auth_service.py shyfem-ui/tests/test_auth_service.py
git commit -m "feat(auth): auto-rehash password on login when argon2 params change"
```

---

### Task 4: Celery worker reads config, not raw env var

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/job_celery.py:263`
- Modify: `shyfem-ui/tests/test_job_celery.py`

**Context:** `CeleryJobQueue.__init__` (at `services/job_celery.py:262–264`, NOT `execute_shyfem_job` itself) reads `os.environ.get("SHYFEM_UI_SHYFEM_DIR", "/usr/local/shyfem")` directly, bypassing `Config`. The constructor stores it on the queue instance, which is then passed to the Celery task body. The Celery worker and the app server can disagree on the SHYFEM path if env vars differ. Route through the same `get_config()` the rest of the codebase uses.

`get_config` is defined in `shyfem_ui/config.py`, not in `job_celery.py` — the agent must add the import.

- [ ] **Step 1: Inspect existing config loader**

Run:
```bash
grep -n 'def get_config\|^class Config\|shyfem_dir' shyfem-ui/shyfem_ui/config.py | head
```

Confirm `get_config()` exists and returns an instance with `.shyfem_dir` field.

- [ ] **Step 2: Add failing test**

The agent should read `job_celery.py:139` first to confirm the task's call signature and how it spawns the SHYFEM child process. Below is a working skeleton — using `MagicMock` for the config so we don't have to enumerate every `Config` field:

```python
from unittest.mock import MagicMock

def test_execute_shyfem_job_uses_config_shyfem_dir(monkeypatch, tmp_path):
    """Regression: the Celery task must resolve shyfem_dir via get_config(),
    not via os.environ.get directly. If env and config disagree, config wins."""
    # Env says one thing
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", "/wrong/path/from/env")

    # Config says another — stub get_config() to return a Mock so we don't
    # have to enumerate every Config field
    fake_config = MagicMock()
    fake_config.shyfem_dir = "/correct/from/config"
    fake_config.work_dir = str(tmp_path)
    monkeypatch.setattr(
        "shyfem_ui.services.job_celery.get_config", lambda: fake_config
    )

    # Stub the child-process spawn so we can capture which shyfem_dir
    # the task hands to the SHYFEM binary (adapt the patched name to
    # whichever spawn helper job_celery actually uses).
    captured: dict = {}
    async def fake_spawn(*args, **kwargs):
        captured["env"] = kwargs.get("env", {})
        captured["cwd"] = kwargs.get("cwd")
        captured["args"] = args
        proc = MagicMock()
        proc.communicate = MagicMock(return_value=(b"", b""))
        proc.returncode = 0
        return proc
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_spawn)

    # Invoke the task body. If decorated as a Celery task, the underlying
    # function is on `.run` (i.e. execute_shyfem_job.run).
    from shyfem_ui.services import job_celery
    fn = getattr(job_celery.execute_shyfem_job, "run", job_celery.execute_shyfem_job)
    import asyncio
    asyncio.run(fn(job_id="test-job", str_file="dummy.str"))

    # The path passed to the child process must come from config, not env.
    haystack = " ".join(str(v) for v in (
        captured.get("env", {}).get("SHYFEMDIR", ""),
        captured.get("cwd", ""),
        " ".join(str(a) for a in captured.get("args", ())),
    ))
    assert "/correct/from/config" in haystack
    assert "/wrong/path/from/env" not in haystack
```

If the task uses neither env nor cwd to convey `shyfem_dir` (e.g., bakes the path into the command-line), the `haystack` join above already covers `args`. If the production code uses a different async spawn helper (e.g., `asyncio.create_subprocess_shell`), patch that name instead.

- [ ] **Step 3: Run test — expect FAIL**

- [ ] **Step 4: Replace direct os.environ access**

In `shyfem-ui/shyfem_ui/services/job_celery.py:263`, replace:

```python
shyfem_dir = os.environ.get("SHYFEM_UI_SHYFEM_DIR", "/usr/local/shyfem")
```

with:

```python
from shyfem_ui.config import get_config
shyfem_dir = str(get_config().shyfem_dir)
```

(Move the import to the top of the file if it's not already there.)

- [ ] **Step 5: Re-run test — PASS, full Celery suite no regressions**

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/job_celery.py shyfem-ui/tests/test_job_celery.py
git commit -m "fix(celery): read shyfem_dir from config not env to match app server"
```

---

## Phase B — Data Integrity (3 tasks, ~2 days)

### Task 5: `ProjectFile` UNIQUE constraint + migration

**Files:**
- Modify: `shyfem-ui/shyfem_ui/models/project.py:50-60` (add `__table_args__` UniqueConstraint)
- Modify: `shyfem-ui/shyfem_ui/services/file_service.py:78-91` (upsert path)
- Create: `shyfem-ui/migrations/versions/<auto>_unique_project_file_path.py` via `alembic revision --autogenerate`
- Modify: `shyfem-ui/tests/test_file_service.py`

**Context:** Repeated uploads of the same `rel_path` create duplicate DB rows pointing to the same on-disk file. Quota counters inflate. Fix at two layers: schema-level UNIQUE constraint + service-level upsert (so the duplicate-write attempt becomes an idempotent update).

- [ ] **Step 1: Add failing test for upsert idempotency**

In `tests/test_file_service.py`:

```python
def test_upload_same_path_twice_is_idempotent(self, tmp_path, db_session, project):
    """Two uploads of the same rel_path must produce one row, latest content,
    and a quota that reflects ONLY the latest size — not the sum of both."""
    from shyfem_ui.services.file_service import FileService, _sum_project_bytes
    svc = FileService(session_factory=lambda: db_session, root=tmp_path)
    svc.upload_file(project_id=project.id, rel_path="data/foo.txt", content=b"v1")
    svc.upload_file(project_id=project.id, rel_path="data/foo.txt", content=b"v22")
    files = svc.list_files(project_id=project.id)
    paths = [f.rel_path for f in files]
    assert paths.count("data/foo.txt") == 1, f"Got {len(paths)} rows for same rel_path: {paths}"
    # Disk reflects the latest upload
    assert (tmp_path / "data" / "foo.txt").read_bytes() == b"v22"
    # CRITICAL regression assertion: quota must NOT double-count.
    # The original bug was "quota counters silently inflate" — two uploads
    # of the same path used to produce two rows summing to len(b"v1")+len(b"v22") = 5,
    # not the correct len(b"v22") = 3.
    assert _sum_project_bytes(db_session, project.id) == 3, (
        "Quota inflated: per-path row should be replaced, not duplicated"
    )
```

- [ ] **Step 2: Run test — expect FAIL with two rows, one path**

- [ ] **Step 3: Add UniqueConstraint to ProjectFile model**

In `shyfem-ui/shyfem_ui/models/project.py`, add:

```python
from sqlalchemy import UniqueConstraint, Index

class ProjectFile(Base):
    __tablename__ = "project_files"
    __table_args__ = (
        UniqueConstraint("project_id", "rel_path", name="uq_project_file_path"),
        Index("ix_project_files_project_id", "project_id"),
        Index("ix_project_files_file_type", "file_type"),
    )
    # ... existing columns
```

- [ ] **Step 4: Generate migration**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/alembic revision --autogenerate -m "unique project_file rel_path"
# Inspect the generated migration file in migrations/versions/. Edit if it tries to drop the wrong index.
```

- [ ] **Step 5: Update `FileService.upload_file` to upsert**

In `shyfem-ui/shyfem_ui/services/file_service.py`, change the relevant block (around lines 78–91) from:

```python
target.write_bytes(content)
pf = ProjectFile(project_id=project_id, rel_path=rel_path, ...)
db.add(pf)
db.commit()
```

to:

```python
target.write_bytes(content)
existing = db.query(ProjectFile).filter_by(
    project_id=project_id, rel_path=rel_path
).one_or_none()
try:
    if existing is None:
        pf = ProjectFile(project_id=project_id, rel_path=rel_path, ...)
        db.add(pf)
    else:
        existing.size_bytes = len(content)
        existing.uploaded_at = datetime.utcnow()  # NOT updated_at — that column doesn't exist on ProjectFile
    db.commit()
except IntegrityError:
    # Concurrent upload of the same path lost the read-then-insert race
    # against the new UNIQUE constraint. Retry as a pure update — but
    # use one_or_none() because the concurrent winner may also have
    # rolled back, leaving no row.
    db.rollback()
    existing = db.query(ProjectFile).filter_by(
        project_id=project_id, rel_path=rel_path
    ).one_or_none()
    if existing is None:
        # Both writers failed — log and surface a clear error to the user
        # rather than crash with NoResultFound. The disk write succeeded,
        # so the file is on disk but unindexed; this matches the legacy
        # "orphaned file" failure mode the upsert was meant to fix and
        # should be exceedingly rare in practice.
        logger.error(
            "Both concurrent uploads of %s failed; disk file may be orphaned",
            rel_path,
        )
        raise RuntimeError(
            f"Upload of {rel_path} failed due to concurrent write conflict; "
            "please retry"
        )
    existing.size_bytes = len(content)
    existing.uploaded_at = datetime.utcnow()
    db.commit()
```

The actual `ProjectFile` schema is in `models/project.py:60-66`: it has `rel_path`, `size_bytes`, `uploaded_at`, plus `project_id`, `file_type`, etc. There is **no** `updated_at` column — setting one would silently write a transient instance attribute that never persists. The `IntegrityError` retry block is needed because the new `UNIQUE(project_id, rel_path)` constraint added in Step 3 turns the existing read-then-insert race into a hard failure on concurrent writes.

- [ ] **Step 6: Run migration on test DB, re-run test — PASS, full suite no regressions**

- [ ] **Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/models/project.py shyfem-ui/shyfem_ui/services/file_service.py shyfem-ui/migrations/versions/*_unique_project_file_path.py shyfem-ui/tests/test_file_service.py
git commit -m "fix(db): UNIQUE(project_id, rel_path) on project_files + upsert in FileService"
```

---

### Task 6: Workflow persistence (DB-backed `Workflow` table)

**Files:**
- Create: model in `shyfem-ui/shyfem_ui/models/workflow.py`
- Modify: `shyfem-ui/shyfem_ui/services/workflow.py:185+` (load from DB on init, persist on transition)
- Create: migration via `alembic revision --autogenerate`
- Modify: `shyfem-ui/tests/test_workflow.py`

**Context:** `WorkflowEngine._workflows` is a plain in-memory dict. Restarts lose all history. Also delete the unused `WorkflowStep.options` field that stores comments never executed.

- [ ] **Step 1: Define the model**

Create `shyfem-ui/shyfem_ui/models/workflow.py`:

```python
"""SQLAlchemy model for persisted workflow instances."""
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, Enum, Integer, JSON, String

from shyfem_ui.db.base import Base


class WorkflowStatus(PyEnum):
    """Workflow execution status. Defined here (not in services) to avoid
    a service→model circular import — the service module imports this
    model class, so the enum must live on the model side. Update
    `shyfem_ui/services/workflow.py` to import `WorkflowStatus` from
    `shyfem_ui.models.workflow` instead of defining its own copy."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    template = Column(String, nullable=False)  # see follow-up: known templates as enum
    # Reuse WorkflowStatus enum — DB column rejects unknown statuses, callers
    # get static type-checking on read paths.
    status = Column(
        Enum(WorkflowStatus, name="workflow_status"),
        nullable=False,
        default=WorkflowStatus.PENDING,
    )
    # JSON column stores list[dict] — see WorkflowEngine for the serialized
    # WorkflowStep schema. JSON contents are not enforced at the DB layer;
    # service-layer (de)serialization owns the shape.
    steps = Column(JSON, nullable=False, default=list)
    project_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
```

Also add `Workflow` to `models/__init__.py` so it's discoverable through the canonical import path (mirroring how the other models are exported there).

- [ ] **Step 2: Generate migration**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/alembic revision --autogenerate -m "workflow persistence"
```

- [ ] **Step 3: Add failing tests**

```python
class TestWorkflowPersistence:

    def test_engine_loads_workflows_from_db_on_init(self, db_session):
        from shyfem_ui.models.workflow import Workflow
        from shyfem_ui.services.workflow import WorkflowEngine

        wf = Workflow(name="hydro", template="hydro_setup", status="running",
                      steps=[{"id": "step1", "status": "done"}])
        db_session.add(wf); db_session.commit()
        engine = WorkflowEngine(session_factory=lambda: db_session)
        loaded = engine.list_workflows()
        assert len(loaded) == 1
        assert loaded[0].name == "hydro"

    def test_step_completion_persists(self, db_session):
        from shyfem_ui.services.workflow import WorkflowEngine
        engine = WorkflowEngine(session_factory=lambda: db_session)
        wf = engine.create_workflow(name="test", template="hydro_setup")
        engine.complete_step(wf.id, "step1")
        # New engine instance reads from DB
        engine2 = WorkflowEngine(session_factory=lambda: db_session)
        loaded = engine2.get_workflow(wf.id)
        assert loaded.steps[0]["status"] == "done"
```

- [ ] **Step 4: Update `WorkflowEngine` to use DB**

In `shyfem-ui/shyfem_ui/services/workflow.py`:

1. Add `session_factory` parameter to `__init__` and store it on `self`. **Do NOT load an in-memory cache** — Shiny constructs the engine per session, and a cache populated at `__init__` would diverge across concurrent sessions writing through their own engine instances.
2. On every read method (`list_workflows`, `get_workflow`, `get_status`): query the DB inside a fresh `with session_factory() as session:` block, deserialize the JSON `steps` column, return.
3. On every mutation (`create_workflow`, `complete_step`, `cancel`): open a session, read-modify-write the row, commit. Use `session.commit()` then return the refreshed object — never cache the returned ORM instance beyond the call.
4. Delete the existing `_workflows: dict[str, WorkflowInstance] = {}` class-level dict at line 185.
5. **Delete `WorkflowStep.options`** entirely — it stores comments like `# Set idtoff > 0 in STR` that were never executed (finding U5). Update any template definition that populates it.

The trade-off is one DB query per workflow operation; for the workflow-completion frequency (handful per session) this is negligible and avoids the entire class of cross-session staleness bugs.

- [ ] **Step 5: Run tests, full suite no regressions**

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/models/workflow.py shyfem-ui/shyfem_ui/services/workflow.py shyfem-ui/migrations/versions/*workflow*.py shyfem-ui/tests/test_workflow.py
git commit -m "feat(workflow): DB-backed persistence; survive server restart"
```

---

### Task 7: Celery/local job-queue parity (DB persistence + notifications)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/job_celery.py:139-231,391-418`
- Modify: `shyfem-ui/shyfem_ui/services/job_queue.py:192-194` (`JobQueueFactory.create`)
- Modify: `shyfem-ui/tests/test_job_celery.py`

**Context:** `LocalJobQueue` persists every job-state transition to the `jobs` table and sends completion notifications. `CeleryJobQueue` does neither — switching backends loses history; users miss email notifications.

- [ ] **Step 1: Add failing tests**

```python
class TestCeleryParity:

    def test_celery_persists_job_state_to_db(self, db_session, mock_celery):
        from shyfem_ui.services.job_celery import CeleryJobQueue
        from shyfem_ui.models.job import Job
        q = CeleryJobQueue(session_factory=lambda: db_session, ...)
        job_id = q.submit(spec=...)
        # Trigger the on-success Celery callback
        ...
        rows = db_session.query(Job).filter_by(id=job_id).all()
        assert len(rows) == 1
        assert rows[0].status == "completed"

    def test_celery_sends_notification_on_completion(self, db_session, mock_celery):
        from shyfem_ui.services.job_celery import CeleryJobQueue
        notif = MagicMock()
        q = CeleryJobQueue(session_factory=lambda: db_session,
                          notification_service=notif)
        job_id = q.submit(spec=...)
        # Trigger the on-success Celery callback
        ...
        notif.notify_job_success.assert_called_once()

    def test_factory_passes_notification_to_celery(self, mock_config):
        from shyfem_ui.services.job_queue import JobQueueFactory
        notif = MagicMock()
        q = JobQueueFactory.create(mode="celery", notification_service=notif, ...)
        # The Celery queue's notification_service must be the one we passed
        assert q.notification_service is notif
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add `notification_service` parameter to `CeleryJobQueue.__init__`** and a `session_factory`. Wire them into the Celery task callbacks (`on_success`, `on_failure`).

- [ ] **Step 4: Mirror `LocalJobQueue._persist_job` in Celery callback paths**

The Celery task at `services/job_celery.py:139` has `on_success` / `on_failure` hooks. From within those, open a session, upsert the corresponding `Job` row.

- [ ] **Step 5: Update `JobQueueFactory.create`**

In `shyfem-ui/shyfem_ui/services/job_queue.py:192-194`, ensure both `mode="local"` and `mode="celery"` accept and pass through `notification_service` and `session_factory`.

- [ ] **Step 6: Run tests, full suite no regressions**

- [ ] **Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/job_celery.py shyfem-ui/shyfem_ui/services/job_queue.py shyfem-ui/tests/test_job_celery.py
git commit -m "feat(jobs): Celery queue parity with local — DB persistence + notifications"
```

---

## Phase C — Authorization Enforcement (1 task, big)

### Task 8: Propagate `check_project_access` to write-path pages

**Files:**
- Modify: 9 page files: `simulation.py`, `physics.py`, `grid_prep.py`, `postprocess.py`, `visualize.py`, `compare.py`, `ensemble.py`, `partitioning.py`, `ibm.py`
- Modify: tests for each (most don't have unit tests — see Task 22 followup)
- Add: `tests/test_pages_access_control.py` with table-driven tests

**Context:** Today only `home.py`, `run.py`, `files.py`, `admin.py` enforce per-action access. The other 9 read `active_project` from the session-scoped reactive value and write/submit without checking the user's role on the project. Pattern is established in `run.py:623`. In local mode `get_current_user()` returns the synthetic admin so the check is a no-op — safe to apply universally.

- [ ] **Step 1: Inspect the established pattern**

```bash
grep -nA 6 'check_project_access\|require_role' shyfem-ui/shyfem_ui/pages/run.py | head -25
grep -nA 6 'get_current_user' shyfem-ui/shyfem_ui/pages/run.py | head -15
```

Confirm the canonical pattern (likely):

```python
user = get_current_user(session)
proj = active_project.get()
if proj is None:
    ui.notification_show("No active project.", type="warning")
    return
if not check_project_access(proj["id"], user, min_role="editor"):
    ui.notification_show("You don't have permission to edit this project.", type="error")
    return
```

- [ ] **Step 2: Identify each write handler in each page**

**The handler names below are guesses — every name MUST be verified by reading each page before writing the test, because page handlers were renamed and split across recent commits.** Only two have been verified by the plan author:

| Page | Verified | Handler (read this name from source) |
|---|---|---|
| `simulation.py` | ✅ | `_confirm_save` (line ~305, triggered by `input.confirm_save_btn`) |
| `partitioning.py` | ✅ | `_run_shyparts` (line ~174) |
| `compare.py` | ✅ | `_generate_comparison_report` (line ~455) |
| `physics.py` | ❓ | The 20+ `@reactive.effect` panel handlers — likely a single inner save dispatcher rather than per-panel; grep `@reactive.effect.*save` |
| `grid_prep.py` | ❓ | Look for handlers that call `wrapper.run_shypre` / `wrapper.run_shybas` / write to disk |
| `postprocess.py` | ❓ | Look for handlers that call `wrapper.run_shyelab` |
| `visualize.py` | ❓ | Look for handlers that write screenshots / PNGs |
| `ensemble.py` | ❓ | Look for handlers that call `job_queue.submit` |
| `ibm.py` | ❓ | Look for handlers that run the Lagrangian simulator |

The agent's first step in Task 8 must be: open each page, find every `@reactive.effect` whose body mutates filesystem / DB / job queue, and produce the actual handler-name table before writing tests. Use the canonical pattern:

```bash
grep -nB1 '^    async def \|^    def ' shyfem-ui/shyfem_ui/pages/<page>.py | head -40
```

Then look at the bodies of each candidate to classify "write" vs "read".

- [ ] **Step 3: Add table-driven tests in `tests/test_pages_access_control.py`**

Use **AST inspection** (not regex) so the check is reliable across formatting variations. AST also lets us verify the call shape (name + at least one arg) rather than substring presence.

```python
"""Verify that every write-path page calls check_project_access in
its handler body (static AST analysis, not source-string regex)."""
import ast
import importlib.util
import pathlib

import pytest

# (page_module_name, write_handler_name, expected_min_role)
# Three names are verified against the current source (2026-04-29);
# the other six MUST be replaced with the names the agent identifies in Step 2.
# DO NOT run this test until the table is filled with names that exist.
WRITE_HANDLERS = [
    ("simulation", "_confirm_save", "editor"),                   # verified
    ("partitioning", "_run_shyparts", "editor"),                  # verified
    ("compare", "_generate_comparison_report", "viewer"),         # verified
    ("physics", "<TODO_FILL_IN_FROM_STEP_2>", "editor"),
    ("grid_prep", "<TODO_FILL_IN_FROM_STEP_2>", "editor"),
    ("postprocess", "<TODO_FILL_IN_FROM_STEP_2>", "editor"),
    ("visualize", "<TODO_FILL_IN_FROM_STEP_2>", "viewer"),
    ("ensemble", "<TODO_FILL_IN_FROM_STEP_2>", "editor"),
    ("ibm", "<TODO_FILL_IN_FROM_STEP_2>", "editor"),
]


def _find_function_def(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Walk the AST looking for any (possibly nested) function with this name."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


class _DirectCallCollector(ast.NodeVisitor):
    """Collect Call nodes from a function body without descending into
    nested function/lambda definitions. Avoids false-positives where the
    guard sits in an unreachable inner helper."""

    def __init__(self):
        self.calls: list[ast.Call] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Don't recurse — stop at nested function definitions.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)  # still walk arg expressions for nested calls


def _calls_check_project_access(func_def: ast.AST) -> bool:
    """Return True if func_def's direct body (excluding nested closures)
    contains a Call whose callable is named ``check_project_access``."""
    visitor = _DirectCallCollector()
    # Visit each statement in the body, NOT the function definition itself
    # (visit_FunctionDef short-circuits). This walks the body without
    # descending into inner def/async def/lambda.
    for stmt in func_def.body:
        visitor.visit(stmt)
    for node in visitor.calls:
        callee = node.func
        if isinstance(callee, ast.Name) and callee.id == "check_project_access":
            return True
        if isinstance(callee, ast.Attribute) and callee.attr == "check_project_access":
            return True
    return False


_PLACEHOLDER_PREFIX = "<TODO"  # rows still needing Step 2 handler-name discovery


@pytest.mark.parametrize("page,handler,role", WRITE_HANDLERS)
def test_handler_calls_check_project_access(page, handler, role):
    """Static AST check: the named handler must contain a call to
    check_project_access. Catches missing guards reliably regardless of
    indentation / closure nesting / inline-helper extraction."""
    if handler.startswith(_PLACEHOLDER_PREFIX):
        pytest.skip(
            f"Handler name for {page} is still a Step-2 placeholder — "
            f"fill in the real handler name in WRITE_HANDLERS, then re-run."
        )
    path = pathlib.Path(f"shyfem-ui/shyfem_ui/pages/{page}.py")
    tree = ast.parse(path.read_text())
    fn = _find_function_def(tree, handler)
    assert fn is not None, f"Handler {handler} not found in {path}"
    assert _calls_check_project_access(fn), (
        f"{path}::{handler} (line {fn.lineno}) does not call "
        f"check_project_access — add the guard before the mutation"
    )


def test_step2_handler_table_is_complete():
    """Sentinel test: fail loudly if Step 2 was skipped. Prevents the
    parametrized tests above from silently skipping all 9 rows."""
    placeholders = [
        page for page, h, _ in WRITE_HANDLERS if h.startswith(_PLACEHOLDER_PREFIX)
    ]
    assert not placeholders, (
        f"WRITE_HANDLERS still has {len(placeholders)} placeholder rows: "
        f"{placeholders}. Fill in the real handler names from Step 2 "
        "before declaring Task 8 complete."
    )
```

The `_PLACEHOLDER_PREFIX` skip avoids the noisy "Handler `<TODO_FILL_IN_FROM_STEP_2>` not found" failures while Step 2 is in progress, but the sentinel test ensures the task can never be marked done with placeholders still in place.

(The AST approach is still a static check, not behavioral — so we still won't catch a guard placed *after* the mutation, only an entirely missing guard. To complement it, Task 22's follow-up doc tracks "Behavioral access-control coverage via Playwright" as a deferred item.)

- [ ] **Step 4: Run the table — expect failures across all 9 pages**

- [ ] **Step 5: Apply the access-check pattern to each page's write handlers**

For each handler in the inventory, add the canonical 5-line guard at the top of the handler body, before any mutation. Use `min_role="editor"` for state-mutating handlers, `"viewer"` for read-only export/screenshot handlers.

- [ ] **Step 6: Re-run the table-driven tests — expect all PASS, full suite no regressions**

- [ ] **Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/{simulation,physics,grid_prep,postprocess,visualize,compare,ensemble,partitioning,ibm}.py shyfem-ui/tests/test_pages_access_control.py
git commit -m "feat(auth): enforce check_project_access on 9 write-path pages"
```

---

## Phase D — Observability & Documentation (2 tasks)

### Task 9: Add logging to 4 silent page modules

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/{home,simulation,grid_prep,partitioning}.py`
- Modify (or create): tests verifying logging behavior at error sites

**Context:** Four large pages (combined ~4,000 LOC) have zero `logger.` calls. (`physics.py` was originally on this list but already imports `logging` at line 8 and defines `logger = logging.getLogger(__name__)` at line 17, so it is **excluded** here.) Errors in their reactive handlers are silent to server logs — operators cannot diagnose user-reported issues. Add a module-level logger and `logger.warning` / `logger.exception` at every `except` block plus `logger.info` at major user-action handlers (project create/delete, simulation save, grid build, partition run).

- [ ] **Step 1: Add module-level logger to each of the 5 pages**

In each file, near the top imports:

```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Inventory `except` blocks in the 5 pages**

```bash
for f in shyfem-ui/shyfem_ui/pages/{home,simulation,grid_prep,partitioning}.py; do
  echo "=== $f ==="
  grep -n 'except.*:' "$f"
done
```

- [ ] **Step 3: Add `logger.exception(msg)` immediately inside each `except` block**

For each `except SomeError as e:` (or `except Exception as e:`), log before the user-facing notification:

```python
except Exception as exc:
    logger.exception("Failed to save STR for project %s", proj_id)
    ui.notification_show(f"Save failed: {exc}", type="error", duration=5)
```

- [ ] **Step 4: Add `logger.info` at key user-action entry points**

In `home.py` `_create_project` body: `logger.info("User %s creating project %r", user_id, name)`.
In `simulation.py` `_save_str` body: `logger.info("Saving STR for project %s", proj_id)`.
Etc — one info-level call per major mutation handler.

- [ ] **Step 5: Add a smoke test that the logger is wired**

```python
class TestPageLoggingWired:
    @pytest.mark.parametrize("page", ["home", "simulation", "grid_prep",
                                       "partitioning"])
    def test_page_has_logger(self, page):
        mod = importlib.import_module(f"shyfem_ui.pages.{page}")
        assert hasattr(mod, "logger"), f"{page}.py must define module logger"
        assert mod.logger.name == f"shyfem_ui.pages.{page}"
```

- [ ] **Step 6: Run, no regressions, commit**

```bash
git add shyfem-ui/shyfem_ui/pages/{home,simulation,grid_prep,partitioning}.py shyfem-ui/tests/test_page_logging.py
git commit -m "chore(observability): add structured logging to 5 silent page modules"
```

---

### Task 10: Update README env-var table

**Files:**
- Modify: `shyfem-ui/README.md` (env-var table around line 94–117)

**Context:** ~15+ env vars are present in code but missing from README: `DEFAULT_ADMIN_PASSWORD`, `DEFAULT_ADMIN_USERNAME`, `DEFAULT_USER_PASSWORD`, `DEFAULT_USER_USERNAME`, `USER_DATA_ROOT`, all six `SMTP_*` vars, `TRUSTED_PROXIES`, `ROOT_PATH`, `STATIC_CACHE_MAX_AGE`, `DB_POOL_*`, `SOLVER_NODE_THRESHOLD`. New operators set up incorrectly without these.

- [ ] **Step 1: Inventory all env vars actually read by the codebase**

```bash
grep -rn 'SHYFEM_UI_\|os.environ\|Field(.*env=' shyfem-ui/shyfem_ui/ --include='*.py' | sort -u | head -50
```

Cross-reference with the existing README table.

- [ ] **Step 2: Update the README table**

Add rows for each missing var: name, default, description, when-required (server-mode-only vs always).

- [ ] **Step 3: Add a generated-from-config script as a regression aid**

Create `shyfem-ui/scripts/generate_env_table.py`:

```python
"""Print the env-var table by introspecting Config — keep README in sync."""
from shyfem_ui.config import Config

for name, field in Config.model_fields.items():
    env_name = f"SHYFEM_UI_{name.upper()}"
    default = field.default if field.default is not None else "(required)"
    desc = field.description or ""
    print(f"| `{env_name}` | `{default}` | {desc} |")
```

- [ ] **Step 4: Commit**

```bash
git add shyfem-ui/README.md shyfem-ui/scripts/generate_env_table.py
git commit -m "docs: complete README env-var table; add introspection script"
```

---

## Phase E — Test Coverage (3 tasks)

### Task 11: `TestStrEditorLogic` for `components/str_editor.py`

**Files:**
- Create: `shyfem-ui/tests/test_str_editor_logic.py`

**Context:** `components/str_editor.py` is 823 LOC, recently modified, with zero tests. Cover the three pure helper functions: `filter_sections` (lines 575–623), `validate_str_content` (624–746), `generate_section_template` (772+). Don't try to test the Shiny server — only the pure helpers.

- [ ] **Step 1: Add tests**

```python
"""Pure-helper tests for components.str_editor."""
import pytest

from shyfem_ui.components.str_editor import (
    filter_sections,
    validate_str_content,
    generate_section_template,
)


class TestFilterSections:
    def test_returns_all_when_query_empty(self):
        all_secs = ["title", "para", "bound"]
        assert filter_sections(all_secs, query="") == all_secs

    def test_substring_match_case_insensitive(self):
        all_secs = ["title", "Para", "bound"]
        assert filter_sections(all_secs, query="par") == ["Para"]

    def test_returns_empty_on_no_match(self):
        assert filter_sections(["a", "b"], query="z") == []


class TestValidateStrContent:
    def test_accepts_minimal_valid_str(self):
        content = "$title\nMar Menor\n$end\n$para\nidt = 60\n$end\n"
        errors = validate_str_content(content)
        assert errors == []

    def test_flags_missing_required_section(self):
        # $para is required for any non-empty STR
        content = "$title\nMar Menor\n$end\n"
        errors = validate_str_content(content)
        assert any("para" in e.lower() for e in errors)

    def test_flags_unclosed_section(self):
        content = "$title\nMar Menor\n"  # no $end
        errors = validate_str_content(content)
        assert any("$end" in e or "unclosed" in e.lower() for e in errors)

    def test_flags_out_of_range_param(self):
        # Assuming idt range is e.g. [1, 86400]
        content = "$para\nidt = -1\n$end\n"
        errors = validate_str_content(content)
        assert any("idt" in e for e in errors)


class TestGenerateSectionTemplate:
    def test_known_section_returns_template_with_end(self):
        out = generate_section_template("para")
        assert "$para" in out
        assert "$end" in out

    def test_unknown_section_returns_empty_or_minimal(self):
        out = generate_section_template("unknown_section_xyz")
        # Should not raise; should return something sensible.
        assert out is not None
```

(Adapt the test bodies to match actual function signatures — the agent should read `str_editor.py:575-746,772+` first to confirm parameter names and return shapes.)

- [ ] **Step 2: Run, fix any signature mismatches, full suite green, commit**

```bash
git add shyfem-ui/tests/test_str_editor_logic.py
git commit -m "test(str_editor): cover filter_sections, validate, generate_template"
```

---

### Task 12: `TestJobQueueBase` for the abstract base + factory

**Files:**
- Create: `shyfem-ui/tests/test_job_queue_base.py`

**Context:** `services/job_queue.py` (196 LOC) has zero tests. Cover `JobInfo.is_active`, `JobInfo.duration`, `JobQueue.add_progress_callback`/`remove_progress_callback`/`_notify_progress`, `generate_job_id`, `JobQueueFactory.create` for both `"local"` and `"celery"` (with mocked config).

- [ ] **Step 1: Add tests**

The real signatures (verified at `services/job_queue.py`):
- `JobInfo(id, name, tool_name, args, working_dir, status, ...)` — `status` is the `JobStatus` enum, NOT a string. `JobInfo` has `created_at`, `queued_at`, `started_at`, `completed_at` — there is no `submitted_at`.
- `add_progress_callback(self, callback_id: str, callback: Callable[[str, float, str], None])` — takes a callback ID + the callable, NOT just the callable.
- `remove_progress_callback(self, callback_id: str)` — takes the ID.
- `generate_job_id` is a `@staticmethod` on `JobQueue` (accessed as `JobQueue.generate_job_id()`), not a module-level function.
- `JobQueue.submit` returns a `str` (job ID); the abstract subclass stub must return a string for chained tests to type-check.

```python
"""Tests for the JobQueue abstract base class and factory."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shyfem_ui.services.job_queue import (
    JobInfo, JobQueue, JobQueueFactory, JobSpec, JobStatus,
)


def _make_job_info(**overrides) -> JobInfo:
    """Build a valid JobInfo for tests; defaults are minimal but legal."""
    base = dict(
        id="x",
        name="t",
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=JobStatus.PENDING,
    )
    base.update(overrides)
    return JobInfo(**base)


class TestJobInfo:

    def test_is_active_pending(self):
        assert _make_job_info(status=JobStatus.PENDING).is_active

    def test_is_active_queued(self):
        assert _make_job_info(status=JobStatus.QUEUED).is_active

    def test_is_active_running(self):
        assert _make_job_info(status=JobStatus.RUNNING).is_active

    def test_is_active_completed_false(self):
        assert not _make_job_info(status=JobStatus.COMPLETED).is_active

    def test_is_active_failed_false(self):
        assert not _make_job_info(status=JobStatus.FAILED).is_active

    def test_duration_completed(self):
        start = datetime.now() - timedelta(seconds=10)
        end = datetime.now()
        info = _make_job_info(
            status=JobStatus.COMPLETED, started_at=start, completed_at=end,
        )
        # JobInfo.duration returns float (seconds) per source line 70.
        assert info.duration is not None
        assert abs(info.duration - 10.0) < 0.5

    def test_duration_no_start_returns_none(self):
        # Pending job that never started has no duration.
        info = _make_job_info(status=JobStatus.PENDING)
        assert info.duration is None


class _StubQueue(JobQueue):
    """Minimal concrete JobQueue subclass for testing the base-class methods.

    The real `JobQueue` ABC declares SEVEN abstract methods (verified at
    `services/job_queue.py:80-153`): ``submit``, ``cancel``, ``get_status``,
    ``list_jobs``, ``get_output``, ``set_progress_callback``,
    ``cleanup_old_jobs``. ALL must be implemented or instantiation raises
    ``TypeError: Can't instantiate abstract class _StubQueue with abstract
    methods ...``.
    """

    async def submit(self, spec: JobSpec) -> str:
        return "stub-job-id"

    async def cancel(self, job_id: str) -> bool:
        return True

    async def get_status(self, job_id: str) -> JobInfo | None:
        return None

    async def list_jobs(self, **kw) -> list[JobInfo]:
        return []

    async def get_output(
        self, job_id: str, stream: str = "stdout", tail: int = 100
    ) -> str:
        return ""

    def set_progress_callback(self, callback) -> None:
        # The base class also offers `add_progress_callback`/`remove_progress_callback`
        # for multi-session use; this single-callback hook is the abstract one.
        self._single_callback = callback

    async def cleanup_old_jobs(self, days: int = 7) -> int:
        # MUST be async — the ABC at services/job_queue.py:153 declares
        # `async def cleanup_old_jobs(...)`. A sync override does not
        # cause a TypeError at instantiation but any caller doing
        # `await queue.cleanup_old_jobs(...)` would TypeError at runtime
        # ("int can't be used in 'await' expression").
        return 0


class TestProgressCallbacks:

    def test_add_and_notify(self):
        q = _StubQueue()
        cb = MagicMock()
        q.add_progress_callback("session-1", cb)
        q._notify_progress("job1", 50.0, "halfway")
        cb.assert_called_once_with("job1", 50.0, "halfway")

    def test_remove_callback(self):
        q = _StubQueue()
        cb = MagicMock()
        q.add_progress_callback("session-1", cb)
        q.remove_progress_callback("session-1")
        q._notify_progress("job1", 50.0, "halfway")
        cb.assert_not_called()

    def test_remove_unknown_id_is_noop(self):
        q = _StubQueue()
        # Must not raise even if no callback was ever registered.
        q.remove_progress_callback("never-added")

    def test_multiple_callbacks_routed_to_all(self):
        q = _StubQueue()
        cb_a = MagicMock()
        cb_b = MagicMock()
        q.add_progress_callback("a", cb_a)
        q.add_progress_callback("b", cb_b)
        q._notify_progress("job1", 25.0, "quarter")
        cb_a.assert_called_once()
        cb_b.assert_called_once()


class TestGenerateJobId:

    def test_unique_per_call(self):
        ids = {JobQueue.generate_job_id() for _ in range(50)}
        assert len(ids) == 50

    def test_format(self):
        jid = JobQueue.generate_job_id()
        # uuid4 string is 36 chars (with dashes)
        assert isinstance(jid, str) and len(jid) >= 8


class TestJobQueueFactory:

    def test_create_local(self, tmp_path):
        cfg = MagicMock(work_dir=str(tmp_path), shyfem_dir="/usr/local/shyfem")
        q = JobQueueFactory.create(mode="local", config=cfg)
        from shyfem_ui.services.job_local import LocalJobQueue
        assert isinstance(q, LocalJobQueue)

    def test_create_celery(self, tmp_path):
        cfg = MagicMock(
            work_dir=str(tmp_path),
            shyfem_dir="/usr/local/shyfem",
            redis_url="redis://localhost:6379/0",
        )
        with patch("shyfem_ui.services.job_celery.celery_app"):
            q = JobQueueFactory.create(mode="celery", config=cfg)
        from shyfem_ui.services.job_celery import CeleryJobQueue
        assert isinstance(q, CeleryJobQueue)

    def test_create_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="mode"):
            JobQueueFactory.create(mode="quantum-tunnel", config=MagicMock())
```

The `test_callback_exception_does_not_propagate` test from the prior version was deleted because the actual `_notify_progress` implementation does not currently swallow callback exceptions — testing that behavior would lock in a non-existent contract. If callback exception isolation becomes a requirement, add it as part of a new task.

- [ ] **Step 2: Run, adapt to actual signatures, commit**

```bash
git add shyfem-ui/tests/test_job_queue_base.py
git commit -m "test(jobs): cover JobQueue abstract base + factory"
```

---

### Task 13: Extended `sharing_service` tests

**Files:**
- Modify: `shyfem-ui/tests/test_sharing_service.py`

**Context:** `list_shareable_users` (sharing_service.py:121) has zero tests today. Add cases.

- [ ] **Step 1: Add tests**

```python
class TestListShareableUsers:

    def test_excludes_owner(self, db_session, owner, project):
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=lambda: db_session)
        candidates = svc.list_shareable_users(project_id=project.id)
        assert owner.id not in [u.id for u in candidates]

    def test_excludes_already_shared(self, db_session, owner, project, other_user):
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=lambda: db_session)
        svc.share_project(project_id=project.id, user_id=other_user.id, role="viewer")
        candidates = svc.list_shareable_users(project_id=project.id)
        assert other_user.id not in [u.id for u in candidates]

    def test_returns_remaining_users(self, db_session, owner, project, other_user, third_user):
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=lambda: db_session)
        svc.share_project(project_id=project.id, user_id=other_user.id, role="viewer")
        candidates = svc.list_shareable_users(project_id=project.id)
        ids = [u.id for u in candidates]
        assert third_user.id in ids
        assert owner.id not in ids
        assert other_user.id not in ids

    def test_empty_when_all_users_have_access(self, db_session, owner, project, other_user):
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=lambda: db_session)
        svc.share_project(project_id=project.id, user_id=other_user.id, role="viewer")
        candidates = svc.list_shareable_users(project_id=project.id)
        assert candidates == []
```

- [ ] **Step 2: Run, commit**

```bash
git add shyfem-ui/tests/test_sharing_service.py
git commit -m "test(sharing): cover list_shareable_users edge cases"
```

---

## Phase F — Test Hygiene (2 tasks)

### Task 14: Convert source-string regression tests to behavioral tests

**Files:**
- Modify: `tests/test_ibm.py` (6 tests), `tests/test_ibm_trips.py` (1 test), `tests/test_app_wiring.py`, `tests/test_ensemble.py`, `tests/test_visualize.py`, `tests/test_tutorial_access.py` (2 tests), `tests/test_admin_user_management.py` (2 tests). **14 tests total — verify with `grep -rn 'inspect.getsource\|open(.*__file__\|open(.*pages.*\.py\|read_text.*pages' tests/ --include='*.py' | wc -l` before claiming the conversion is complete.**

**Context:** 14 tests use `inspect.getsource` / `open(__file__).read()` to assert strings present/absent. Brittle to refactors. Convert to behavioral tests where the production code path is exercised. For tests that genuinely have no behavior to assert (e.g., "_DEMO_PARTICLES no longer exists in module"), delete them — the `import` of the module is sufficient regression coverage.

- [ ] **Step 1: Inventory**

```bash
grep -rn 'inspect.getsource\|open(.*__file__\|open(.*pages.*\.py' tests/ --include='*.py'
```

For each test, decide:
- **Convert:** Find the production function it's actually trying to verify. Call it, assert on return value or side effect.
- **Delete:** If the test is "string X no longer exists in source," delete it. The file's `import` (which already happens at test collection) is the regression guard.

- [ ] **Step 2: Convert / delete each test individually, with a commit per file**

For `tests/test_ibm.py` 6 tests checking `_DEMO_PARTICLES` absence: delete; replace with one test:

```python
def test_module_imports_without_demo_data(self):
    import shyfem_ui.pages.ibm  # noqa: F401
    # The mere import is the regression guard — if a `_DEMO_PARTICLES` global
    # were re-introduced and broke import, this would fail.
```

For `tests/test_app_wiring.py` checking `"AuditService(" in src`: convert by importing `app.py` and asserting that `audit_service` is wired (e.g., `assert hasattr(app_module, 'audit_service')` or run a smoke check on `SessionAuthMiddleware.__init__` accepting the param).

- [ ] **Step 3: Run full suite after each conversion, commit per file**

```bash
git commit -m "test(ibm): convert source-string assertions to behavioral imports"
# ... one per file ...
```

---

### Task 15: Fix flaky `test_job_local.py` xfail + magic counts in `test_app_layout`

**Files:**
- Modify: `shyfem-ui/tests/test_job_local.py:176-200`
- Modify: `shyfem-ui/tests/test_app_layout.py:12,18`

**Context:** Two test-quality issues bundled into one task because both are <30 LOC fixes.

- [ ] **Step 1: Replace `asyncio.sleep` race with explicit signal in cancel test**

In `tests/test_job_local.py:176`, the current xfail uses `asyncio.sleep(0.2)` to give the subprocess time to start before cancelling. Replace with a stub command that signals start via a file or a `threading.Event`:

```python
# Old (flaky):
async def test_cancel_running_job():
    job_id = await q.submit(spec=JobSpec(command=["sleep", "10"], ...))
    await asyncio.sleep(0.2)  # Race: process may not have started yet
    await q.cancel(job_id)
    ...

# New (deterministic):
async def test_cancel_running_job(tmp_path):
    started_marker = tmp_path / "started"
    # Use a shell command that touches the marker, then waits.
    cmd = ["bash", "-c", f"touch {started_marker}; sleep 30"]
    job_id = await q.submit(spec=JobSpec(command=cmd, ...))
    # Wait deterministically for the marker to appear, then cancel.
    for _ in range(50):  # 5s max
        if started_marker.exists():
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("Subprocess did not start within 5s")
    await q.cancel(job_id)
    info = await q.get_status(job_id)
    # JobStatus is an Enum (not a str). Comparing an Enum value against
    # the raw string "cancelled" returns False — assert on the enum member.
    from shyfem_ui.services.job_queue import JobStatus
    assert info.status == JobStatus.CANCELLED
```

Remove the `@pytest.mark.xfail(...)` decorator.

- [ ] **Step 2: Replace magic counts in `test_app_layout.py`**

Find lines 12 and 18:

```python
assert len(SIDEBAR_GROUPS) == 5
assert len(all_pages) == 15
```

Replace with assertions that won't break on every page addition:

```python
EXPECTED_GROUPS = {"Project", "Build", "Run", "Analyze", "Admin"}
assert EXPECTED_GROUPS.issubset({g.label for g in SIDEBAR_GROUPS}), (
    f"Missing required sidebar groups: {EXPECTED_GROUPS - {g.label for g in SIDEBAR_GROUPS}}"
)

REQUIRED_PAGES = {"home", "mesh", "simulation", "run", "visualize", "admin"}
assert REQUIRED_PAGES.issubset({p.id for p in all_pages}), (
    f"Missing required pages: {REQUIRED_PAGES - {p.id for p in all_pages}}"
)
```

- [ ] **Step 3: Run, commit**

```bash
git add shyfem-ui/tests/test_job_local.py shyfem-ui/tests/test_app_layout.py
git commit -m "test: deterministic job-cancel test; replace magic counts with set assertions"
```

---

## Phase G — UX Dead-ends (4 tasks)

### Task 16: Wire or remove partitioning method/weighted controls

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py:54-65,172-227`
- Modify: `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:279-301`
- Add: `shyfem-ui/tests/test_partitioning.py`

**Context:** Two UI controls (`partition_method` select with `metis`/`manual` options, `weighted` checkbox) are rendered but never read by `_run_shyparts`. Either wire them or delete them. We wire `weighted` (real shyparts flag) and remove `manual` (no implementation path).

- [ ] **Step 1: Add tests**

The real `run_shyparts` signature in `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:279` is:

```python
async def run_shyparts(
    self,
    bas_file: Path | str,
    working_dir: Path | str,
    np: int = 4,
    options: list[str] | None = None,
    ...
)
```

The page passes the `weighted` flag via `options=["-weighted"]` (per Step 3). Test that path:

```python
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

def test_run_shyparts_passes_weighted_flag(monkeypatch, tmp_path):
    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
    wrapper = ShyfemWrapper()
    captured = {}
    async def fake_run_command(self, exe, args, *a, **kw):
        captured["exe"] = exe
        captured["args"] = list(args)
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(ShyfemWrapper, "run_command", fake_run_command)

    asyncio.run(wrapper.run_shyparts(
        bas_file=tmp_path / "foo.bas",
        working_dir=tmp_path,
        np=4,
        options=["-weighted"],
    ))
    # Real run_shyparts prepends options into the args list passed to run_command,
    # then appends ["-np", "4", "<bas>"]. So "-weighted" must appear before "-np".
    assert captured["exe"] == "shyparts"
    assert "-weighted" in captured["args"]
    assert captured["args"].index("-weighted") < captured["args"].index("-np")

def test_partitioning_handler_passes_weighted_when_checked(monkeypatch):
    """End-to-end style: when input.weighted() returns True, _run_shyparts
    must include '-weighted' in the options list passed to the wrapper."""
    # The agent should construct this against the actual handler.
    # This is a placeholder reminder that the page-level wiring also
    # needs verification, not just the wrapper.
    pass
```

(The earlier static-source check `assert '"manual"' not in src.lower()` was an anti-pattern duplicating Task 14's rule. If you want to verify "manual" was removed from the dropdown, do it via UI inspection — `assert "manual" not in mesh_method_controls()` after constructing a fake input — not by reading source text.)

- [ ] **Step 2: Update `partitioning.py:54-65`**

Replace the partition_method select with a static label "METIS partitioning" (or remove entirely if METIS is the only mode). Keep the `weighted` checkbox.

- [ ] **Step 3: Update `_run_shyparts` to pass `weighted` to the wrapper**

The real `run_shyparts` signature uses `bas_file` (not `grd_file`), `np` (not `n_parts`), and requires `working_dir`. Inside `_run_shyparts` in `pages/partitioning.py`, find the existing `wrapper.run_shyparts(...)` call and adjust to add the `options` kwarg:

```python
# in _run_shyparts (page handler):
weighted = input.weighted()
options = ["-weighted"] if weighted else []
result = await wrapper.run_shyparts(
    bas_file=bas_path,           # the .bas file path the existing handler computes
    working_dir=work_dir,        # already in scope from project_context
    np=n_parts,                  # the existing variable holding partition count
    options=options,
)
```

(The agent should confirm the variable names — `bas_path`, `work_dir`, `n_parts` — match what the handler already uses. They will likely need to grep `pages/partitioning.py` first.)

- [ ] **Step 4: Confirm `ShyfemWrapper.run_shyparts` already accepts `options`**

Already does — `services/shyfem_wrapper.py:283` declares `options: list[str] | None = None`. No wrapper-side change needed.

- [ ] **Step 5: Run, commit**

```bash
git add shyfem-ui/shyfem_ui/pages/partitioning.py shyfem-ui/shyfem_ui/services/shyfem_wrapper.py shyfem-ui/tests/test_partitioning.py
git commit -m "fix(partitioning): wire 'weighted' option, remove non-functional 'manual' method"
```

---

### Task 17: Project-aware time-series picker in `compare.py` + `.shy` recognition in ensemble

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/compare.py:52-66,485-512,555-559`
- Modify: `shyfem-ui/shyfem_ui/pages/ensemble.py:820`

**Context:** Two related UX dead-ends bundled. Compare TS section uses free-text paths; the STR section already has a project-aware picker (lines 485–512). Apply the same pattern to TS files. Also: ensemble result aggregation matches `.ts/.ext/.csv` only — SHYFEM's default `.shy` binary output produces an empty plot. Recognize `.shy` and surface a clear "binary output, no time-series chart available" message.

- [ ] **Step 1: Add `_extract_ts_choices` helper to `compare.py`**

Mirror `_extract_str_choices` (already in the file). Walk the project work dir, return all `.ts` and `.ext` text files.

```python
def _extract_ts_choices(active_project, file_service) -> dict[str, str]:
    if active_project is None:
        return {}
    work_dir = Path(active_project["work_dir"])
    choices = {}
    for ext in (".ts", ".ext"):
        for p in work_dir.rglob(f"*{ext}"):
            rel = p.relative_to(work_dir).as_posix()
            choices[str(p)] = f"{active_project['name']} / {rel}"
    return choices
```

- [ ] **Step 2: Replace free-text inputs at `compare.py:52-66` with a select**

When `active_project()` is non-None, render `ui.input_select("ts_a_path", ...)` populated from `_extract_ts_choices(active_project)`. Fall back to free-text input if no project is active.

- [ ] **Step 3: Surface format hint**

Below the picker:

```python
ui.p(
    "Accepted formats: .ts (column-text time series) and .ext (BFM extension). "
    "Binary .shy outputs are not supported here — use Visualize to inspect them.",
    class_="text-muted small"
)
```

- [ ] **Step 4: In `ensemble.py:820`, recognize `.shy`**

The existing loop iterates `for j in completed_jobs:` and computes `ts_files = [f for f in j.output_files if f.endswith((".ts", ".ext", ".csv"))]`. **Note: `j.output_files` is a list of *strings*, not `Path` objects** — use `.endswith(...)`, not `.suffix`.

After the existing loop (after `if not run_data:` and before/after the `_build_duration_chart` fallback), add a per-job count of `.shy`-only jobs and surface a warning toast:

```python
# Count jobs whose only outputs are binary .shy (no time-series chart possible)
shy_only_jobs = sum(
    1 for j in completed_jobs
    if not any(f.endswith((".ts", ".ext", ".csv")) for f in j.output_files)
    and any(f.endswith(".shy") for f in j.output_files)
)
# Always warn when any run is shy-only — even when other runs DO have .ts data
# the user must know that some runs are silently absent from the chart.
if shy_only_jobs > 0:
    total = len(completed_jobs)
    detail = (
        "no time-series chart can be drawn"
        if not run_data
        else f"{shy_only_jobs}/{total} runs are missing from the chart"
    )
    ui.notification_show(
        f"{shy_only_jobs} run(s) produced .shy binary output only — "
        f"{detail}. Use the Visualize page to inspect binary output.",
        type="warning", duration=10,
    )
```

Place this block before the existing `if not run_data: return _build_duration_chart(completed_jobs)` so the warning fires regardless of whether the chart falls back to durations or shows partial TS data. Decoupling the condition (`shy_only_jobs > 0` rather than `shy_only_jobs and not run_data`) catches the mixed-results case where some runs would otherwise be invisibly dropped.

- [ ] **Step 5: Add tests for `_extract_ts_choices`**

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/compare.py shyfem-ui/shyfem_ui/pages/ensemble.py shyfem-ui/tests/test_compare.py
git commit -m "feat(compare): project-aware TS picker; warn on .shy-only ensemble outputs"
```

---

### Task 18: Pass `tutorial_context` to 5 missing pages

**Files:**
- Modify: `shyfem-ui/shyfem_ui/app.py:778,787,794-796`
- Modify (each accepts a new optional `tutorial_context=None` parameter): `shyfem-ui/shyfem_ui/pages/{compare,ensemble,partitioning,ibm,files}.py` server functions

**Context:** Tutorial nav buttons silently skip context injection for these 5 pages because they're constructed without `tutorial_context`. Wire the parameter through.

- [ ] **Step 1: In `app.py:778,787,794-796`, add `tutorial_context=tutorial_context` to each of the 5 page server constructor calls**

- [ ] **Step 2: In each page's server function, accept the new parameter** (defaults to None) and use it to pre-populate inputs when nav fires.

- [ ] **Step 3: Add a smoke test**

```python
@pytest.mark.parametrize("page", ["compare", "ensemble", "partitioning", "ibm", "files"])
def test_page_server_accepts_tutorial_context(page):
    import inspect
    mod = importlib.import_module(f"shyfem_ui.pages.{page}")
    server_fn_name = f"{page}_server"
    server_fn = getattr(mod, server_fn_name, None)
    assert server_fn is not None
    params = inspect.signature(server_fn).parameters
    assert "tutorial_context" in params
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(tutorial): propagate tutorial_context to compare/ensemble/partitioning/ibm/files"
```

---

### Task 19: "Next step" navigation cards after job submit / postprocess

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:711` (after `notification_show`)
- Modify: `shyfem-ui/shyfem_ui/pages/postprocess.py:611` (after batch completion)
- Add: `shyfem-ui/shyfem_ui/components/next_step_card.py` (small shared component)

**Context:** Workflow pages dead-end at completion notifications. Add a small inline card with "View in Visualize" / "Post-process" links so the user has somewhere to go.

- [ ] **Step 1: Create the shared component**

```python
"""Inline 'next step' card to wire into completion handlers."""
from dataclasses import dataclass

from shiny import ui


@dataclass(frozen=True)
class NextStepLink:
    """Self-documenting record for next_step_card links.

    `nav_target` MUST match the `data-nav` value of an existing sidebar
    nav item (the visible label such as "Run", "Post-Process",
    "Visualize") so `shyfemNavTo()` can find and click it.

    Why `@dataclass(frozen=True)` rather than `NamedTuple`: the codebase
    uses `@dataclass` consistently (see JobSpec, JobInfo, WorkflowStep) and
    no `NamedTuple` types in production. `frozen=True` makes the record
    hashable + immutable; the dataclass form blocks positional construction
    via subscript (link[0]), which keeps named-field access as the only path.
    """
    label: str
    nav_target: str
    description: str


def next_step_card(*, title: str, links: list[NextStepLink]) -> ui.Tag:
    """Render a small card with a heading and clickable next-step links.

    Args:
        title: Card heading (e.g. 'Job submitted')
        links: List of NextStepLink entries
    """
    import json as _json
    items = []
    for link in links:
        # nav_target is asserted to be a plain identifier so the onclick is
        # injection-safe even if a future caller passes a label with quotes.
        # The runtime asserts AND we use json.dumps to produce a quoted
        # JS string literal that's always safe inside an HTML attribute
        # (json always uses double quotes, so we wrap onclick in single
        # quotes to avoid clashing).
        # nav_target must match a `data-nav` value from app.py:SIDEBAR_GROUPS
        # (e.g. "Run", "Post-Process", "Visualize"). Allowed chars: alnum,
        # hyphen, underscore. Reject anything else as a defense-in-depth
        # check against accidental injection — Shiny will HTML-escape the
        # rendered attribute too, but this surfaces typos early.
        if not all(c.isalnum() or c in "-_" for c in link.nav_target) or not link.nav_target:
            raise ValueError(
                f"NextStepLink.nav_target must be alphanumeric / hyphen / "
                f"underscore (got {link.nav_target!r}); shyfemNavTo arg "
                "must match a data-nav identifier from app.py:SIDEBAR_GROUPS."
            )
        nav_js = _json.dumps(link.nav_target)  # always double-quoted JSON
        # NOTE: hash-anchor hrefs (`href="#run"`) do NOT switch Shiny pages.
        # The app uses a custom `shyfemNavTo(name)` JS helper (defined in
        # app.py:497) that finds the sidebar nav item with the matching
        # data-nav attribute and triggers a click. We use the same.
        items.append(
            ui.tags.li(
                ui.tags.a(
                    link.label,
                    href="#",
                    onclick=(
                        f"if(typeof shyfemNavTo==='function')"
                        f"{{shyfemNavTo({nav_js});}}return false;"
                    ),
                    class_="text-decoration-none",
                ),
                ui.tags.small(
                    f" — {link.description}",
                    class_="text-muted ms-2",
                ),
            )
        )
    return ui.div(
        ui.tags.h6(title, class_="mb-2"),
        ui.tags.ul(*items, class_="list-unstyled mb-0 small"),
        class_="alert alert-info py-2 px-3 mt-2",
    )
```

- [ ] **Step 2: Wire into `run.py:711`**

After `ui.notification_show(...)`, add:

```python
next_step_html.set(
    next_step_card(
        title="Job submitted — what next?",
        links=[
            NextStepLink("Watch progress", "Run", "Live log + progress on this page"),
            NextStepLink("Post-process results", "Post-Process", "Run shyelab on outputs once finished"),
            NextStepLink("Visualize results", "Visualize", "Inspect grid + bathymetry + time series"),
        ],
    )
)
```

(Add a corresponding `next_step_html = reactive.value(None)` at the top of `run_server` and an `@render.ui` that returns it.)

- [ ] **Step 3: Same pattern in `postprocess.py:611`** with appropriate links (Visualize, Compare).

- [ ] **Step 4: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/next_step_card.py shyfem-ui/shyfem_ui/pages/{run,postprocess}.py
git commit -m "feat(ux): contextual 'next step' cards after job submit and postprocess"
```

---

## Phase H — Architecture Cleanup (2 tasks)

### Task 20: Move grid-prep helpers into mesh_builder service (break circular import)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/mesh_builder.py` (move helpers in)
- Modify: `shyfem-ui/shyfem_ui/pages/grid_prep.py` (re-export for compatibility OR refactor to import from service)
- Modify: `shyfem-ui/tests/test_grid_map.py` if it imports the helpers

**Context:** `services/mesh_builder.py:1298` does a deferred `from shyfem_ui.pages.grid_prep import compute_element_areas, compute_element_quality, compute_min_angles` inside a function body to break a circular import. The 3 helpers are pure (don't reference Shiny) — they belong in the service. Move them, drop the deferred import.

- [ ] **Step 1: Locate the helpers in `pages/grid_prep.py`**

```bash
grep -n 'def compute_element_areas\|def compute_element_quality\|def compute_min_angles' shyfem-ui/shyfem_ui/pages/grid_prep.py
```

- [ ] **Step 2: Read each helper. Verify it's pure (no `input.`, no `ui.`, no reactive calls).**

- [ ] **Step 3: Move them to `services/mesh_builder.py` (near `compute_mesh_stats`).**

- [ ] **Step 4: Replace the deferred import at `services/mesh_builder.py:1298` with a normal call.**

- [ ] **Step 5: In `pages/grid_prep.py`, replace the function definitions with re-exports for backward compatibility:**

```python
from shyfem_ui.services.mesh_builder import (
    compute_element_areas,
    compute_element_quality,
    compute_min_angles,
)
```

- [ ] **Step 6: Run tests, full suite no regressions**

- [ ] **Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/mesh_builder.py shyfem-ui/shyfem_ui/pages/grid_prep.py
git commit -m "refactor(mesh): move pure quality helpers into service; drop deferred import"
```

---

### Task 21: Plotly inline option for offline reports

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/report.py:502` and `add_plotly_figure`
- Modify: `shyfem-ui/shyfem_ui/config.py` (add `report_plotly_mode` field)
- Modify: `shyfem-ui/tests/test_report.py`

**Context:** Reports inline a CDN-hosted Plotly script. Air-gapped deployments (HPC, field) get blank charts. Make it configurable: `cdn` (default, smaller files) vs `inline` (offline-capable, larger).

- [ ] **Step 1: Add config field**

In `shyfem-ui/shyfem_ui/config.py`:

```python
report_plotly_mode: Literal["cdn", "inline"] = Field(
    default="cdn",
    description="How to embed Plotly JS in generated HTML reports. "
                "'cdn' — link to plot.ly CDN (small files, requires net). "
                "'inline' — bundle Plotly JS in each report (~3MB per file, offline-capable).",
)
```

- [ ] **Step 2: Add failing test**

```python
def test_report_plotly_mode_inline_bundles_js(tmp_path):
    from shyfem_ui.services.report import ReportBuilder
    cfg = MagicMock(report_plotly_mode="inline")
    rb = ReportBuilder(config=cfg)
    rb.add_plotly_figure(go.Figure())
    html = rb.build_html()
    # Inline mode must NOT include the CDN script; must include `Plotly` JS body
    assert "cdn.plot.ly" not in html
    assert "Plotly = " in html or "var Plotly" in html

def test_report_plotly_mode_cdn_uses_cdn(tmp_path):
    from shyfem_ui.services.report import ReportBuilder
    cfg = MagicMock(report_plotly_mode="cdn")
    rb = ReportBuilder(config=cfg)
    rb.add_plotly_figure(go.Figure())
    html = rb.build_html()
    assert "cdn.plot.ly" in html
```

- [ ] **Step 3: Update the template + `render()` to honor config**

The actual codebase uses a different pattern than `fig.to_html()`. `add_plotly_figure` (line 232) emits `Plotly.newPlot(...)` calls that depend on `Plotly` being already loaded; the loader itself is the **`<script src=…>` line hardcoded in `_REPORT_TEMPLATE` at line 502** (not generated per-figure).

Make two changes:

1. **Add a placeholder to `_REPORT_TEMPLATE`.** Find:

   ```python
   <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
   ```

   Replace with:

   ```python
   {plotly_loader}
   ```

2. **Compute the loader in `render()` based on config.** In `ReportBuilder.render()` (around line 320), build the `plotly_loader` string before calling `_REPORT_TEMPLATE.format(...)`:

   ```python
   if self.config.report_plotly_mode == "inline":
       # Inline the full Plotly JS bundle. plotly's offline helper exposes
       # the bundled JS as a string via its private `_plotlyjs` module —
       # this is the same path plotly.io.to_html(include_plotlyjs=True) uses.
       from plotly.offline.offline import get_plotlyjs
       plotly_loader = f"<script>{get_plotlyjs()}</script>"
   else:
       plotly_loader = (
           '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'
       )

   return _REPORT_TEMPLATE.format(
       title=_esc(self.title),
       created_at=self._created_at.strftime("%Y-%m-%d %H:%M:%S"),
       toc=toc_items,
       sections="\n".join(sections_html),
       plotly_loader=plotly_loader,
   )
   ```

3. **Adjust the test in Step 2** so it actually exercises the new path:

   ```python
   def test_report_plotly_mode_inline_bundles_js(tmp_path):
       from shyfem_ui.services.report import ReportBuilder
       cfg = MagicMock(report_plotly_mode="inline")
       rb = ReportBuilder(title="t", config=cfg)
       rb.add_plotly_figure(go.Figure())
       html = rb.render()
       assert "cdn.plot.ly" not in html
       # The inline bundle starts with `/**` (Plotly license header) and
       # contains a top-level `Plotly` global definition.
       assert "Plotly" in html
       assert len(html) > 500_000  # inline bundle is ~3MB; CDN reference is ~80 chars

   def test_report_plotly_mode_cdn_uses_cdn(tmp_path):
       from shyfem_ui.services.report import ReportBuilder
       cfg = MagicMock(report_plotly_mode="cdn")
       rb = ReportBuilder(title="t", config=cfg)
       rb.add_plotly_figure(go.Figure())
       html = rb.render()
       assert 'cdn.plot.ly/plotly-2.35.2.min.js' in html
   ```

(`plotly.offline.offline.get_plotlyjs` is the public-but-undocumented helper plotly uses internally for `include_plotlyjs=True`. If that import path moves in a future plotly release, the test will fail loudly with an ImportError — easy to spot, easy to update.)

- [ ] **Step 4: Run, commit**

```bash
git add shyfem-ui/shyfem_ui/services/report.py shyfem-ui/shyfem_ui/config.py shyfem-ui/tests/test_report.py
git commit -m "feat(report): inline-Plotly mode for air-gapped deployments"
```

---

## Phase I — Tracked Follow-ups

### Task 22: Open follow-up doc for deferred items

**Files:**
- Create: `docs/followups/2026-04-29-ui-deep-review-deferred.md`

**Context:** Several deep-review findings are out of scope for this plan (architectural refactors, missing test coverage on large pages, postprocess UI redesign). Track them explicitly so they don't get lost.

- [ ] **Step 1: Create the followup doc**

Create `docs/followups/2026-04-29-ui-deep-review-deferred.md`:

```markdown
# Follow-up: Deferred UI Deep-Review Findings

**Origin:** 2026-04-29 deep review of `shyfem-ui/`. The 22-task hardening plan
(`docs/superpowers/plans/2026-04-29-ui-hardening-followups.md`) closes
the highest-leverage gaps. This doc tracks items that need their own plan or
an explicit "do not fix" decision.

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
for file paths. The `files.py` browser exists but is never wired as a picker.

**Pages affected:** `partitioning.py:28-35`, `grid_prep.py:265`,
`postprocess.py:128`, `physics.py:228`, `simulation.py:29`, `run.py:173`,
`ibm.py:162`.

**Why deferred:** Requires a shared "file picker modal" component (`components/file_picker.py`
exists but is not used by any page). The redesign affects 7+ pages and needs
a UX pass. Scope as its own plan.

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
`mesh_builder.py` service (1421) + page (1442), `simulation.py` (1389),
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
fix in Task 16 lands.
```

- [ ] **Step 2: Commit**

```bash
git add docs/followups/2026-04-29-ui-deep-review-deferred.md
git commit -m "docs(followup): track 8 deferred UI deep-review items"
```

---

## Verification Checklist

After all 22 tasks:

1. **Security gates closed:**
   - `grep -c 'HttpOnly' shyfem-ui/shyfem_ui/middleware/session_auth.py` ≥ 2 (session + CSRF)
   - `grep -c 'resolve()' shyfem-ui/shyfem_ui/services/project_export.py` ≥ 1
   - `grep -c 'check_needs_rehash' shyfem-ui/shyfem_ui/services/auth_service.py` ≥ 1
   - `grep 'os.environ.get.*SHYFEM_UI_SHYFEM_DIR' shyfem-ui/shyfem_ui/services/job_celery.py` returns no hits
2. **Data integrity:**
   - `grep 'UniqueConstraint' shyfem-ui/shyfem_ui/models/project.py` returns a hit
   - `ls shyfem-ui/shyfem_ui/models/workflow.py` exists
   - `grep -c 'notification_service' shyfem-ui/shyfem_ui/services/job_celery.py` ≥ 3
3. **Auth enforced on 9 pages:**
   ```bash
   for p in simulation physics grid_prep postprocess visualize compare ensemble partitioning ibm; do
     grep -c check_project_access shyfem-ui/shyfem_ui/pages/$p.py | xargs -I{} test {} -ge 1 || echo "FAIL $p"
   done
   ```
4. **Logging in 4 pages:** `for p in home simulation grid_prep partitioning; do grep -c 'logger\.' shyfem-ui/shyfem_ui/pages/$p.py | xargs -I{} test {} -ge 5 || echo "FAIL $p"; done` (physics.py already has its own logger and is excluded.)
5. **Test counts:** Full `pytest -q` should add at least the new tests from Tasks 11/12/13 (≥ 30 new) plus Task 1 (2), Task 2 (4), Task 3 (1), Task 4 (1), Task 5 (1), Task 6 (2), Task 7 (3), Task 8 (9), Task 9 (5), Task 14 (deletes some, adds smoke), Task 16 (2). Old + ~60.
6. **No regressions:** Full suite green.
7. **README env-var coverage:** `python shyfem-ui/scripts/generate_env_table.py` output matches the README table.
8. **Followup doc filed:** `ls docs/followups/2026-04-29-ui-deep-review-deferred.md` exists.

---

## Coverage After Plan

| Severity | Count | Closed | Tracked |
|---|---|---|---|
| Critical | 5 | 5 (Tasks 1, 2, 4, 5, 8) | 0 |
| Important | 10 | 7 (Tasks 6, 7, 9, 10, 11, 12, 16) | 3 (deferred test coverage, file-picker, direct-DB) |
| Suggested | 13 | 8 (Tasks 3, 14, 15, 17, 18, 19, 20, 21) | 5 (god modules, naming, metrics, flux UI, etc.) |
| Unimplemented | 5 | 4 (Tasks 6, 16, 17) | 1 (validate-partitions depth) |
| **Total** | **33** | **24** | **9** |
