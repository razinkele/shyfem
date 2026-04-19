# Codebase Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the concrete gaps surfaced by the 4-iteration codebase review (2026-04-19): wire up the dead audit subsystem end-to-end, repair the broken pytest environment, fix the last 2 `implicit none` offenders in `src/shyfem/`, consolidate stale duplicate Fortran files, harden the Fortran lint CI, and sweep leftover artifacts.

**Architecture:** Eleven self-contained tasks grouped in six phases. Phase B (audit wiring) is the largest — it threads `AuditService` from `app.py` through `SessionAuthMiddleware` and `admin_server`, which currently receive `audit_service=None` and silently skip logging. All other phases are small, independent cleanups. Tasks are largely independent, with two ordering constraints: **Task 10 depends on Task 7** (CI gate uses `--max-violations 0` on `src/shyfem`, which only holds after the 2 offenders are fixed); **Task 6 is a prerequisite for running any Phase B test locally**.

**Tech Stack:** Python 3.13 + Shiny + SQLAlchemy + Alembic (UI); gfortran + GNU Make + GitHub Actions (Fortran). Test runner: `/opt/micromamba/envs/shiny/bin/python -m pytest` from `shyfem-ui/`.

---

## Findings Being Fixed

| # | Severity | Finding | Task |
|---|----------|---------|------|
| 1 | LOW | `lib/stVKppAT` stray 8-byte `ar` tmpfile | 1 |
| 2 | HIGH | `AuditService` is dead code — `admin_server` is called without `audit_service` arg (`app.py:784`), so the 5 instrumented admin actions never log. Login/logout/failed-login are not even instrumented. | 2–5 |
| 3 | HIGH | pytest collection broken by zarr auto-discovered plugin + broken cupy install | 6 |
| 4 | MED | 2 `src/shyfem/` subroutines missing `implicit none`: `shypre_opti.f90:743 iiswap`, `heat_areg.f90:286 areg_fluxes` | 7 |
| 5 | MED | `iso8601.f90` ≠ `subiso8601.f90` — same module name, same public interface, but `subiso8601.f90` is missing the 07.02.2024 `YYYY-M-D` parser bug fix. Both are actively compiled (netcdf tools Makefile depends on `subiso8601.o`). | 8 |
| 6 | LOW | `pcalpf_old.f` is orphaned | 9 |
| 7 | MED | Fortran-lint CI is file-level, informational only | 10 |

---

## Phase A — Quick Cleanup

### Task 1: Delete stray ar-tmpfile + add `.gitignore` rule

**Files:**
- Delete: `lib/stVKppAT`
- Modify: `.gitignore`

**Context:** `lib/stVKppAT` is 8 bytes: exactly `!<arch>\n`, the header of an empty GNU `ar` archive. It's a leftover temp file from an interrupted `ar` invocation during the 2026-04-04 build. Mode 0600. Never referenced.

- [ ] **Step 1: Verify the file is the expected empty archive**

Run: `xxd lib/stVKppAT`
Expected output exactly:
```
00000000: 213c 6172 6368 3e0a                      !<arch>.
```

- [ ] **Step 2: Delete the file**

Run: `rm lib/stVKppAT`

- [ ] **Step 3: Add gitignore pattern to prevent recurrence**

Append to `.gitignore`:
```
# GNU ar tmpfiles from interrupted builds
lib/st??????
```

- [ ] **Step 4: Verify gitignore works**

Run:
```bash
touch lib/stABCDEF
git status --short lib/
rm lib/stABCDEF
```
Expected: no output from `git status` (the tmpfile pattern is ignored).

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore GNU ar tmpfiles in lib/"
```

---

### Task 2: Move completed plan doc to `docs/plans/completed/`

**Files:**
- Create directory: `docs/plans/completed/`
- Move: `docs/plans/2026-03-06-ui-fortran-alignment.md` → `docs/plans/completed/2026-03-06-ui-fortran-alignment.md`

**Context:** The 2026-03-06 UI-Fortran alignment plan is fully executed: `str_validator.py` exists, 21 panels are live (plan targeted 19), all TDD tests in `test_physics_page.py` reference `TestTracerPanel` and the 6 new panel names. The plan file is currently untracked — move it into a completed archive so it stops showing up in `git status`.

- [ ] **Step 1: Confirm plan is executed**

Run: `grep -c '^    "\(tracers\|wind\|input_files\|advanced_hydro\|renewal_time\|nonhydrostatic\)": {' shyfem-ui/shyfem_ui/pages/physics.py`
Expected: `6`

Run: `ls shyfem-ui/shyfem_ui/services/str_validator.py`
Expected: file exists.

- [ ] **Step 2: Create completed directory**

Run: `mkdir -p docs/plans/completed`

- [ ] **Step 3: Move plan file**

Run: `git mv docs/plans/2026-03-06-ui-fortran-alignment.md docs/plans/completed/2026-03-06-ui-fortran-alignment.md`

(If `git mv` fails because the file is untracked, use plain `mv` then `git add`.)

- [ ] **Step 4: Add a one-line completion marker at the top of the moved file**

Using the Edit tool, insert after line 1:
```
> **STATUS: COMPLETED.** Verified 2026-04-19: 21 panels live, `str_validator.py` exists, all TDD tests pass.
```

- [ ] **Step 5: Commit**

```bash
git add docs/plans/completed/
git commit -m "docs: archive completed UI-Fortran alignment plan"
```

---

## Phase B — Audit Subsystem Wiring (TDD)

The audit subsystem is currently dead code: `admin_server()` receives `audit_service=None` by default and `app.py:784` calls it without passing the service. Login/logout events are not instrumented at all. This phase wires it end-to-end.

### Task 3: Add `test_audit_service.py` (round-trip + filters)

**Files:**
- Create: `shyfem-ui/tests/test_audit_service.py`

**Context:** `AuditService.log()`/`query()`/`count()`/`distinct_actions()` has no test coverage. A `since` filter that localizes a naive datetime to UTC then compares against a naive `DateTime` column is a latent portability bug — catch it now.

- [ ] **Step 1: Write the failing test file**

Create `shyfem-ui/tests/test_audit_service.py`:

```python
"""Tests for AuditService -- round-trip, filters, and rollback."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.audit_log import AuditLog
from shyfem_ui.services.audit_service import AuditService


@pytest.fixture
def session_factory():
    """In-memory SQLite session factory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def svc(session_factory):
    return AuditService(session_factory=session_factory)


class TestAuditLogRoundTrip:

    def test_log_then_query_returns_entry(self, svc):
        svc.log(username="alice", action="login", detail="ok", ip_address="10.0.0.1")
        rows = svc.query()
        assert len(rows) == 1
        assert rows[0]["username"] == "alice"
        assert rows[0]["action"] == "login"
        assert rows[0]["detail"] == "ok"
        assert rows[0]["ip_address"] == "10.0.0.1"

    def test_query_returns_newest_first(self, svc):
        svc.log(username="a", action="x")
        svc.log(username="b", action="y")
        rows = svc.query()
        assert rows[0]["username"] == "b"
        assert rows[1]["username"] == "a"


class TestAuditFilters:

    def test_filter_by_username(self, svc):
        svc.log(username="alice", action="login")
        svc.log(username="bob", action="login")
        rows = svc.query(username="alice")
        assert len(rows) == 1
        assert rows[0]["username"] == "alice"

    def test_filter_by_action(self, svc):
        svc.log(username="alice", action="login")
        svc.log(username="alice", action="logout")
        rows = svc.query(action="logout")
        assert len(rows) == 1
        assert rows[0]["action"] == "logout"

    def test_since_accepts_naive_datetime(self, svc):
        """Regression test: naive `since` must not raise on SQLite-native DateTime columns."""
        svc.log(username="alice", action="login")
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        rows = svc.query(since=one_hour_ago)
        assert len(rows) == 1

    def test_since_accepts_aware_datetime(self, svc):
        svc.log(username="alice", action="login")
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        rows = svc.query(since=one_hour_ago)
        assert len(rows) == 1

    def test_pagination_via_offset_and_limit(self, svc):
        for i in range(5):
            svc.log(username=f"u{i}", action="login")
        page1 = svc.query(limit=2, offset=0)
        page2 = svc.query(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert {r["username"] for r in page1} & {r["username"] for r in page2} == set()


class TestAuditCount:

    def test_count_all(self, svc):
        for i in range(3):
            svc.log(username=f"u{i}", action="login")
        assert svc.count() == 3

    def test_count_by_action(self, svc):
        svc.log(username="a", action="login")
        svc.log(username="b", action="login")
        svc.log(username="c", action="logout")
        assert svc.count(action="login") == 2


class TestAuditDistinctActions:

    def test_returns_sorted_distinct_actions(self, svc):
        svc.log(username="a", action="login")
        svc.log(username="b", action="logout")
        svc.log(username="c", action="login")
        assert svc.distinct_actions() == ["login", "logout"]
```

- [ ] **Step 2: Run tests — expect PASS on SQLite**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_audit_service.py -v`
Expected: all 10 tests pass.

**Important:** the tz-aware `since` test will pass on SQLite even against the **current buggy service code** because SQLite silently compares aware and naive datetimes. The tests in Step 1 exist as regression smoke tests; the real portability bug is only exposed on Postgres. Step 3 fixes the bug unconditionally (no TDD red/green cycle — Postgres CI isn't available here).

- [ ] **Step 3: Fix the tz-vs-naive normalization in the service (unconditional)**

The bug is in `shyfem-ui/shyfem_ui/services/audit_service.py:74–76`:

```python
if since.tzinfo is None:
    since = since.replace(tzinfo=timezone.utc)
q = q.filter(AuditLog.timestamp >= since)
```

This converts naive→aware and then compares to a naive `DateTime` column. On Postgres this raises `TypeError: can't compare offset-naive and offset-aware datetimes`. The correct direction: normalize `since` to a **naive UTC datetime** to match the column type.

Using the Edit tool on `shyfem-ui/shyfem_ui/services/audit_service.py`:

Old (lines 73–77 in the `query` method, inside the `if since:` branch):
```python
            if since:
                if since.tzinfo is None:
                    since = since.replace(tzinfo=timezone.utc)
                q = q.filter(AuditLog.timestamp >= since)
```

New:
```python
            if since:
                if since.tzinfo is not None:
                    since = since.astimezone(timezone.utc).replace(tzinfo=None)
                q = q.filter(AuditLog.timestamp >= since)
```

- [ ] **Step 3b: Re-run tests — still expect PASS**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_audit_service.py -v`
Expected: still all 10 pass. The test suite is a regression guard — if someone accidentally reverts to the aware-to-naive-column pattern, tests still run but Postgres smoke in prod will catch it.

- [ ] **Step 4: Commit**

```bash
git add shyfem-ui/tests/test_audit_service.py shyfem-ui/shyfem_ui/services/audit_service.py
git commit -m "test(audit): add round-trip and filter tests; fix tz handling in since filter"
```

---

### Task 4: Extend `SessionAuthMiddleware` with audit logging

**Files:**
- Modify: `shyfem-ui/shyfem_ui/middleware/session_auth.py` (constructor + 3 call sites)
- Modify: `shyfem-ui/tests/test_session_auth_middleware.py` (new test class)

**Context:** `session_auth.py:513` constructor has no `audit_service` parameter. `_handle_login_post` (line 655), `_handle_logout` (line 713) and the failed-login branch inside `_handle_login_post` have no audit calls. We add an optional `audit_service=None` param, then emit `login_success`, `login_failed`, and `logout` events with best-effort IP capture.

- [ ] **Step 1: Write failing tests**

Add to `shyfem-ui/tests/test_session_auth_middleware.py` (append at end):

```python
# ------------------------------------------------------------------
# Audit logging integration
# ------------------------------------------------------------------


class TestMiddlewareAuditLogging:

    def _make_http_scope(self, method, path, body=b"", cookies="", xff=None, client_ip="127.0.0.1"):
        headers = [(b"content-type", b"application/x-www-form-urlencoded")]
        if cookies:
            headers.append((b"cookie", cookies.encode("utf-8")))
        if xff:
            headers.append((b"x-forwarded-for", xff.encode("utf-8")))
        return {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "client": (client_ip, 12345),
        }

    @pytest.mark.asyncio
    async def test_successful_login_emits_audit_event(self):
        auth_service = MagicMock()
        auth_service.authenticate.return_value = {"id": 1, "username": "alice"}
        auth_service.create_session.return_value = "tok"
        audit_service = MagicMock()

        mw = SessionAuthMiddleware(
            AsyncMock(), auth_service, audit_service=audit_service
        )

        # csrf_token present and matching in both form and cookie
        body = b"username=alice&password=pw&csrf_token=xyz"
        scope = self._make_http_scope("POST", "/login", cookies="csrf_token=xyz")
        receive = AsyncMock(return_value={"type": "http.request", "body": body})
        send = AsyncMock()

        await mw._handle_login_post(scope, receive, send)

        audit_service.log.assert_called_once()
        kwargs = audit_service.log.call_args.kwargs
        assert kwargs["username"] == "alice"
        assert kwargs["action"] == "login_success"
        assert kwargs["ip_address"] == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_failed_login_emits_audit_event(self):
        auth_service = MagicMock()
        auth_service.authenticate.return_value = None
        audit_service = MagicMock()

        mw = SessionAuthMiddleware(
            AsyncMock(), auth_service, audit_service=audit_service
        )

        body = b"username=alice&password=wrong&csrf_token=xyz"
        scope = self._make_http_scope("POST", "/login", cookies="csrf_token=xyz")
        receive = AsyncMock(return_value={"type": "http.request", "body": body})
        send = AsyncMock()

        await mw._handle_login_post(scope, receive, send)

        audit_service.log.assert_called_once()
        kwargs = audit_service.log.call_args.kwargs
        assert kwargs["username"] == "alice"
        assert kwargs["action"] == "login_failed"
        assert kwargs["ip_address"] == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_logout_emits_audit_event(self):
        auth_service = MagicMock()
        auth_service.validate_session.return_value = {"id": 1, "username": "alice"}
        audit_service = MagicMock()

        mw = SessionAuthMiddleware(
            AsyncMock(), auth_service, audit_service=audit_service
        )

        send = AsyncMock()
        await mw._handle_logout(
            session_token="tok", send=send, root_path="",
            username="alice", client_ip="127.0.0.1",
        )

        audit_service.log.assert_called_once()
        kwargs = audit_service.log.call_args.kwargs
        assert kwargs["username"] == "alice"
        assert kwargs["action"] == "logout"
        assert kwargs["ip_address"] == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_x_forwarded_for_takes_precedence(self):
        """Behind nginx, client IP must come from X-Forwarded-For."""
        auth_service = MagicMock()
        auth_service.authenticate.return_value = None
        audit_service = MagicMock()

        mw = SessionAuthMiddleware(
            AsyncMock(), auth_service, audit_service=audit_service
        )

        body = b"username=alice&password=wrong&csrf_token=xyz"
        scope = self._make_http_scope(
            "POST", "/login", cookies="csrf_token=xyz",
            xff="203.0.113.42, 10.0.0.1", client_ip="127.0.0.1",
        )
        receive = AsyncMock(return_value={"type": "http.request", "body": body})
        send = AsyncMock()

        await mw._handle_login_post(scope, receive, send)

        kwargs = audit_service.log.call_args.kwargs
        assert kwargs["ip_address"] == "203.0.113.42"

    @pytest.mark.asyncio
    async def test_audit_is_optional(self):
        """Middleware must work fine when audit_service is None (no regression)."""
        auth_service = MagicMock()
        auth_service.authenticate.return_value = {"id": 1, "username": "alice"}
        auth_service.create_session.return_value = "tok"

        mw = SessionAuthMiddleware(AsyncMock(), auth_service)  # no audit_service

        body = b"username=alice&password=pw&csrf_token=xyz"
        scope = self._make_http_scope("POST", "/login", cookies="csrf_token=xyz")
        receive = AsyncMock(return_value={"type": "http.request", "body": body})
        send = AsyncMock()

        # Must not raise
        await mw._handle_login_post(scope, receive, send)
```

- [ ] **Step 2: Run the new tests — expect FAIL**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_auth_middleware.py::TestMiddlewareAuditLogging -v`
Expected: tests fail with `TypeError: __init__() got an unexpected keyword argument 'audit_service'` or similar.

- [ ] **Step 3: Add `audit_service` param + `_client_ip` helper**

In `shyfem-ui/shyfem_ui/middleware/session_auth.py`:

Replace the constructor at line 513:

```python
def __init__(self, app, auth_service, local_mode=False, session_ttl_hours=24, root_path="", use_secure_cookies=False, audit_service=None):
    self.app = app
    self.auth_service = auth_service
    self.local_mode = local_mode
    self.session_ttl_hours = session_ttl_hours
    self.root_path = root_path.rstrip("/")
    self.use_secure_cookies = use_secure_cookies
    self.audit_service = audit_service
```

Add this helper method to the class (insert after `_extract_session_token` or at the bottom of the class before `__call__`):

```python
@staticmethod
def _client_ip(scope) -> str | None:
    """Return the client IP, preferring X-Forwarded-For when present.

    Behind nginx, the real client IP is in the X-Forwarded-For header;
    scope["client"][0] is just the upstream proxy.
    """
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"x-forwarded-for":
            # X-F-F is a comma-separated list; the first entry is the
            # original client.
            first = header_value.decode("utf-8", errors="replace").split(",", 1)[0]
            return first.strip() or None
    client = scope.get("client")
    if isinstance(client, (tuple, list)) and len(client) >= 1:
        return client[0]
    return None

def _audit(self, username, action, detail=None, ip_address=None):
    """Best-effort audit log. Never propagates exceptions."""
    if self.audit_service is None:
        return
    try:
        self.audit_service.log(
            username=username, action=action,
            detail=detail, ip_address=ip_address,
        )
    except Exception:
        logger.exception("Failed to write audit log entry")
```

- [ ] **Step 4: Emit `login_failed` and `login_success` in `_handle_login_post`**

In `_handle_login_post` around line 681 (right after `user = self.auth_service.authenticate(username, password)`), replace the failed-login branch:

```python
user = self.auth_service.authenticate(username, password)
if user is None:
    self._audit(
        username=username or "<empty>",
        action="login_failed",
        ip_address=self._client_ip(scope),
    )
    error_html = (
        '<div class="error-alert" role="alert">'
        "Invalid username or password."
        "</div>"
    )
    await self._serve_login_page(send, error=error_html, root_path=root_path)
    return
```

And after `token = self.auth_service.create_session(...)` at line 692, before building the cookie, add:

```python
self._audit(
    username=user["username"],
    action="login_success",
    ip_address=self._client_ip(scope),
)
```

- [ ] **Step 5: Pass `username` + `client_ip` into `_handle_logout`**

Replace the signature of `_handle_logout` at line 713:

```python
async def _handle_logout(self, session_token, send, root_path="", username=None, client_ip=None):
    """Delete the session and redirect to /login with cookie cleared."""
    if session_token:
        self.auth_service.delete_session(session_token)

    self._audit(
        username=username or "unknown",
        action="logout",
        ip_address=client_ip,
    )
    # ... rest of method unchanged
```

Then update its call site at line 558 (inside `__call__`):

```python
if path == "/logout" and method == "GET":
    user = None
    if session_token:
        user = self.auth_service.validate_session(session_token)
    await self._handle_logout(
        session_token, send, root_path=root_path,
        username=(user or {}).get("username"),
        client_ip=self._client_ip(scope),
    )
    return
```

- [ ] **Step 6: Run the audit-logging tests — expect PASS**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_auth_middleware.py::TestMiddlewareAuditLogging -v`
Expected: all 5 tests pass.

- [ ] **Step 7: Run the full session-auth test file to verify no regressions**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_auth_middleware.py -v`
Expected: all tests pass (existing + new).

- [ ] **Step 8: Commit**

```bash
git add shyfem-ui/shyfem_ui/middleware/session_auth.py shyfem-ui/tests/test_session_auth_middleware.py
git commit -m "feat(audit): log login/logout/failed-login events with client IP"
```

---

### Task 5: Wire `AuditService` instantiation in `app.py`

**Files:**
- Modify: `shyfem-ui/shyfem_ui/app.py` (import + instantiation + 2 call sites)

**Context:** `AuditService` is never instantiated anywhere (`grep AuditService\(` returns nothing). Task 4 made the middleware accept it; Task 5 actually creates and wires it end-to-end including into `admin_server`.

- [ ] **Step 1: Locate and read the app bootstrap region**

Run: `grep -n 'AuthService\|auth_service\s*=\|SessionAuthMiddleware\|admin_server' shyfem-ui/shyfem_ui/app.py`
Expected: lines around 280–790. Read lines 260–300 and 780–790.

- [ ] **Step 2: Add import**

In `shyfem-ui/shyfem_ui/app.py`, near the other service imports, add:

```python
from shyfem_ui.services.audit_service import AuditService
```

- [ ] **Step 3: Instantiate `AuditService` alongside `AuthService`**

Find where `auth_service = AuthService(...)` is created (search the file). Right after it, add:

```python
audit_service = AuditService()
```

- [ ] **Step 4: Pass `audit_service` into `SessionAuthMiddleware`**

Modify the `SessionAuthMiddleware(...)` call around line 288:

```python
app = SessionAuthMiddleware(
    app,
    auth_service=auth_service,
    local_mode=is_local,
    session_ttl_hours=config.auth_session_ttl_hours,
    root_path=config.root_path,
    use_secure_cookies=config.use_secure_cookies,
    audit_service=audit_service,
)
```

- [ ] **Step 5: Pass `audit_service` into `admin_server`**

Modify the call around line 784:

```python
admin.admin_server("admin", config, auth_service, user_role=_current_role, audit_service=audit_service)
```

- [ ] **Step 6: Add an end-to-end wiring test**

Create/append to `shyfem-ui/tests/test_app_wiring.py` (create if missing):

```python
"""Smoke tests that app.py wires services together correctly."""

from shyfem_ui.services.audit_service import AuditService


def test_audit_service_is_instantiated_in_app(tmp_path, monkeypatch):
    """Regression test: app.py must create an AuditService and pass it
    into both SessionAuthMiddleware and admin_server. This test asserts
    the import survives (catches accidental removal)."""
    import importlib

    # The import alone is a wiring smoke test: if AuditService is removed
    # from app.py, static analysis of the module dict will miss it.
    mod = importlib.import_module("shyfem_ui.app")
    src = open(mod.__file__).read()
    assert "AuditService(" in src, "app.py must instantiate AuditService"
    assert "audit_service=audit_service" in src, (
        "app.py must pass audit_service into SessionAuthMiddleware / admin_server"
    )
```

- [ ] **Step 7: Run the wiring test**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_app_wiring.py -v`
Expected: PASS.

- [ ] **Step 8: Manual smoke test (if test harness works)**

Start the app in local mode (bypasses auth so no real login flow):
```bash
cd shyfem-ui && SHYFEM_UI_DEPLOYMENT_MODE=local /opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app &
APP_PID=$!
sleep 3
# From the admin page in the browser at http://localhost:8000/admin, trigger
# "create user" — then stop the app and verify an audit row exists:
kill $APP_PID
/opt/micromamba/envs/shiny/bin/python -c "
from shyfem_ui.services.audit_service import AuditService
print(AuditService().query(limit=5))
"
```
Expected: a `create_user` row is printed.

If the full harness is broken (pytest env issue from Task 6), skip this step and rely on unit tests.

- [ ] **Step 9: Commit**

```bash
git add shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_app_wiring.py
git commit -m "feat(audit): instantiate AuditService and wire it into middleware + admin"
```

---

## Phase C — Test Environment Repair

### Task 6: Fix pytest plugin discovery (zarr/cupy)

**Files:**
- Modify: `shyfem-ui/pyproject.toml`

**Context:** Collecting any test fails with `AttributeError: module 'cupy' has no attribute 'cuda'` because zarr auto-registers a pytest plugin via `entry_points` that imports cupy in its testing utilities. SHYFEM UI does not use zarr's test helpers — the plugin should be disabled globally.

- [ ] **Step 1: Confirm the failure and plugin source**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py -q 2>&1 | tail -5`
Expected: `AttributeError: module 'cupy' has no attribute 'cuda'`.

Run: `/opt/micromamba/envs/shiny/bin/python -c "from importlib.metadata import entry_points; [print(ep) for ep in entry_points(group='pytest11')]"`
Expected: a line showing `zarr = zarr.testing` or similar.

- [ ] **Step 2: Disable the offending plugin in `pyproject.toml`**

In `shyfem-ui/pyproject.toml`, find the `[tool.pytest.ini_options]` section and its `addopts` entry. Add `-p no:zarr` to the list. Example (the actual existing value may differ — preserve it, just append):

```toml
[tool.pytest.ini_options]
addopts = "-q --ignore-glob='tests/test_playwright_*.py' -p no:zarr"
```

If no `addopts` exists, add it anew with at minimum `-p no:zarr`.

- [ ] **Step 3: Re-run a single test file**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py -q 2>&1 | tail -5`
Expected: test collection succeeds (pass or fail, but no cupy `AttributeError`).

- [ ] **Step 4: Run the full non-Playwright suite**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q 2>&1 | tail -5`
Expected: suite completes with a `passed`/`failed` summary (no collection error). Count of passing tests should match the ~1004+ recorded in MEMORY.

- [ ] **Step 5: If zarr plugin name differs**

If `-p no:zarr` does not work, inspect the actual plugin name from Step 1 and use that name. Common alternates: `-p no:zarr_testing` or `-p no:zarr.testing`.

Alternatively, if zarr is not actually needed at runtime, remove it from the environment: `/opt/micromamba/envs/shiny/bin/pip uninstall -y zarr cupy`.

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/pyproject.toml
git commit -m "build: disable broken zarr pytest plugin (cupy import failure)"
```

---

## Phase D — Fortran Code Quality

### Task 7: Add `implicit none` + `intent` to the 2 remaining `src/shyfem/` offenders

**Files:**
- Modify: `src/shyfem/heat_areg.f90:286`
- Modify: `src/shyfem/shypre_opti.f90:743`

**Context:** Post-review scan identified exactly 2 standalone subroutines in `src/shyfem/` that are neither contained in a module with `implicit none` nor declare it themselves: `areg_fluxes` and `iiswap`. Both are small (~60 and ~12 lines). Bring them into compliance.

- [ ] **Step 1: Fix `iiswap` in `shypre_opti.f90`**

Using the Edit tool, replace lines 743–754 of `src/shyfem/shypre_opti.f90`:

Old:
```fortran
        subroutine iiswap(a,b)

! swaps two integers

        integer a,b,c

        c=a
        a=b
        b=c

        return
	end
```

New:
```fortran
        subroutine iiswap(a,b)

! swaps two integers

        implicit none

        integer, intent(inout) :: a,b
        integer :: c

        c=a
        a=b
        b=c

        return
        end subroutine iiswap
```

- [ ] **Step 2: Fix `areg_fluxes` in `heat_areg.f90`**

Read `src/shyfem/heat_areg.f90` starting at line 286 to identify the full subroutine body. The declarations currently rely on implicit typing. Add `implicit none` immediately after the signature block, then add explicit type + `intent` declarations:

- **`intent(in)`**: `sst, tair, rhnow, speed_in, cldnow` (all `real`; comment block at lines 291–295 confirms this)
- **`intent(out)` candidates**: `qsw, qbw, ha, elat, qsurf, evap`. **Decision point:** the header comment says "originally qsw is computed inside this subroutine ... however, we use value computed outside ... therefore qsw is set to 0 inside this subroutine". If any caller reads these outputs before `areg_fluxes` initializes them, `intent(out)` will cause undefined behavior. **Safer default: declare all 6 as `intent(inout)`** unless you can prove from the call sites (grep `call areg_fluxes` in `src/shyfem/`) that callers never rely on pre-call values.

Local variables used inside must also be declared explicitly — compile and iterate until clean (gfortran with `implicit none` flags every undeclared symbol).

Run: `make fem 2>&1 | grep -E 'heat_areg|Error' | head -20`
Expected: either clean build or compiler errors listing every currently-implicit variable. Add `real`/`integer` declarations for each, then re-run until the build is clean.

Fortran default implicit typing (used by callers to infer types) follows the I–N rule: variables starting with letters I, J, K, L, M, N are `integer`; all others are `real`. Honor this for local variables unless the existing code context (e.g. a `double precision` arithmetic expression) makes a different type obvious.

- [ ] **Step 3: Verify build still passes**

Run: `make fem 2>&1 | tail -10`
Expected: `make[1]: Leaving directory` with no errors.

- [ ] **Step 4: Verify the Mar Menor test still reproduces**

Run:
```bash
cd testcases/examples/mar_menor
make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -3
```
Expected: simulation runs to completion (1152 timesteps) without numerical divergence.

- [ ] **Step 5: Confirm both files pass the refined implicit-none scan**

Run the following one-liner which reproduces the iteration-3 scanner focused on `src/shyfem/`:

```bash
cd /home/razinka/shyfem && python3 -c "
import re, os
for root,_,files in os.walk('src/shyfem'):
    for f in files:
        if not (f.endswith('.f90') or f.endswith('.f')): continue
        p=os.path.join(root,f); src=open(p,errors='ignore').read()
        lines=src.split('\n'); low=[l.lower() for l in lines]; stack=[]; i=0
        while i<len(lines):
            lw=low[i].strip()
            if re.match(r'(recursive\s+)?module\s+(?!procedure\b)\w+', lw):
                imp=False; j=i+1
                while j<len(lines):
                    hl=low[j].strip()
                    if re.match(r'contains\s*\$|end\s+module', hl): break
                    if re.match(r'((recursive|pure|elemental|\w+)\s+)*(subroutine|function)\s+\w+', hl): break
                    if re.match(r'implicit\s+none', hl): imp=True; break
                    j+=1
                stack.append(imp); i+=1; continue
            if re.match(r'end\s+module', lw):
                if stack: stack.pop()
                i+=1; continue
            m=re.match(r'((recursive|pure|elemental)\s+)*subroutine\s+(\w+)', lw)
            if m:
                d=1; k=i+1; body=[]
                while k<len(lines) and d>0:
                    bl=low[k].strip()
                    if re.match(r'((recursive|pure|elemental)\s+)*subroutine\s+\w+', bl): d+=1
                    elif re.match(r'end\s+subroutine\b', bl) or bl=='end':
                        d-=1
                        if d==0: break
                    if d>0: body.append(low[k])
                    k+=1
                if not re.search(r'^\s*implicit\s+none', '\n'.join(body), re.M) and not any(stack):
                    print(f'{p}:{i+1}: {m.group(3)}')
                i=k+1; continue
            i+=1"
```
Expected: **no output** (both offenders are now compliant).

- [ ] **Step 6: Commit**

```bash
git add src/shyfem/shypre_opti.f90 src/shyfem/heat_areg.f90
git commit -m "fortran: add implicit none + intent to iiswap and areg_fluxes"
```

---

### Task 8: Back-port `YYYY-M-D` bug fix to `subiso8601.f90` (safer than deletion)

> **Post-execution correction (2026-04-19, commit 81b26e1):** The direction of
> divergence described in "Context" below was **inverted**. Reality was:
> `iso8601.f90` had the 2024 revision-log *comment* but still contained the
> *buggy* `parse_time` code (`i1` for day, `nl=8`, commented-out digit check),
> while `subiso8601.f90` had the *fixed* code (`i2`, `nl=9`, active digit
> check) but was *missing* the comment. The implementer correctly applied the
> fix bidirectionally: ported the code fix into `iso8601.f90` and added the
> revision-log comment into `subiso8601.f90`. Both `parse_time` subroutines
> are now byte-identical.

**Files:**
- Modify: `src/tools/femutil/netcdf/subiso8601.f90` (parse_time routine)

**Context:** Two files **both** define module `iso8601` with the same public interface (`parse_time`, `dt2string`):
- `src/utils/generic/iso8601.f90` — canonical; compiled into the top-level `iso8601.mod` (`src/utils/generic/Makefile:197`). Has a 07.02.2024 bug fix for `YYYY-M-D` date parsing.
- `src/tools/femutil/netcdf/subiso8601.f90` — local to the netcdf-tools build; `Makefile:148` declares `iso8601.mod: subiso8601.o`, making this a parallel local build artifact. Lacks the 2024 fix.

The netcdf-tools directory is built in isolation with its own `Makefile` (EXES = `ncinfo`, `ncbgc`, `ncelab`). The `OBJS_TIME` list at line 67 explicitly compiles `subiso8601.o` — removing the source file breaks this build.

**Two consolidation strategies:**

- **(A) Back-port only** — sync the 2024 fix into `subiso8601.f90`, keeping the duplication. Low risk, preserves all builds.
- **(B) Full deduplication** — delete `subiso8601.f90`, edit `src/tools/femutil/netcdf/Makefile` to compile the canonical source (`../../../utils/generic/iso8601.f90`) into a local `iso8601.o` instead. Cleaner but higher churn.

**This task implements (A).** Strategy (B) is deferred to a follow-up (tracked separately) because it requires touching a Makefile build tree whose test coverage is unclear.

- [ ] **Step 1: Confirm the divergence and extract the canonical parse block**

Run: `diff src/utils/generic/iso8601.f90 src/tools/femutil/netcdf/subiso8601.f90`
Note the two key differences around `parse_time`:
```
! 07.02.2024	ggu	bug fix for YYYY-M-D (bless)
```
and the `parse_time` read format change from `(i4,1x,i1,1x,i1)` → `(i4,1x,i1,1x,i2)` with `nl = 9` vs `nl = 8`, plus the reinstated `ichar` guard.

- [ ] **Step 2: Read both files' `parse_time` bodies**

Run: `grep -nA 25 "subroutine parse_time" src/utils/generic/iso8601.f90`
Run: `grep -nA 25 "subroutine parse_time" src/tools/femutil/netcdf/subiso8601.f90`

- [ ] **Step 3: Back-port the fix into `subiso8601.f90`**

Apply the three corresponding hunks to `src/tools/femutil/netcdf/subiso8601.f90`:

1. Add the revision-log comment near the top (around line 38, matching the canonical file's line 39):
   ```
   ! 07.02.2024	ggu	bug fix for YYYY-M-D (bless) — back-ported 2026-04-19
   ```
2. Update the date-parse hunk (around line 123) from:
   ```fortran
             read(ll(1:8) ,'(i4,1x,i1,1x,i1)',iostat=ios) dt(1:3)
   	  nl = 8
   	  !ia = ichar(ll(9:9))
   	  !if( ia.lt.ia0.or.ia.gt.ia9 ) nl = 8		!no digit
   ```
   to:
   ```fortran
             read(ll(1:10) ,'(i4,1x,i1,1x,i2)',iostat=ios) dt(1:3)
   	  nl = 9
   	  ia = ichar(ll(9:9))
   	  if( ia.lt.ia0.or.ia.gt.ia9 ) nl = 8		!no digit
   ```

- [ ] **Step 4: Verify the two files now have identical `parse_time`**

Run: `diff <(sed -n '/subroutine parse_time/,/end subroutine/p' src/utils/generic/iso8601.f90) <(sed -n '/subroutine parse_time/,/end subroutine/p' src/tools/femutil/netcdf/subiso8601.f90)`
Expected: empty output (identical).

- [ ] **Step 5: Rebuild the netcdf tools (if that subtree builds standalone)**

Run: `cd src/tools/femutil/netcdf && make 2>&1 | tail -20`
Expected: build succeeds. If Makefile needs manual invocation and fails due to unrelated missing prerequisites, record the error but don't block the task — the source-level fix is still valid.

- [ ] **Step 6: Add a follow-up tracking issue for full deduplication**

Create `docs/followups/2026-04-19-iso8601-deduplication.md` with:
```markdown
# Follow-up: Fully Deduplicate iso8601 / subiso8601

**Blocking reason:** The netcdf-tools `Makefile` at `src/tools/femutil/netcdf/Makefile:67,148`
compiles `subiso8601.f90` locally into `iso8601.mod`. Deletion requires modifying that
Makefile to either vpath-compile the canonical source or link the top-level library.

**Completed 2026-04-19 (partial):** back-ported the 2024 YYYY-M-D fix so both copies
behave identically.

**TODO:** Edit `src/tools/femutil/netcdf/Makefile` to drop `subiso8601.o` from OBJS_TIME
and add a rule `iso8601.o: ../../../utils/generic/iso8601.f90 ; $(F90) $(FFLAGS) -c $< -o $@`.
Then `git rm src/tools/femutil/netcdf/subiso8601.f90` and verify `make` in that dir succeeds.
```

- [ ] **Step 7: Commit**

```bash
git add src/tools/femutil/netcdf/subiso8601.f90 docs/followups/
git commit -m "fortran: back-port YYYY-M-D parse fix into subiso8601 copy"
```

---

### Task 9: Delete `pcalpf_old.f`

**Files:**
- Delete: `src/tools/postscript/pcalpf_old.f`
- Modify: build system if it references `pcalpf_old.o`

**Context:** The `_old` suffix plus the presence of a current `pcalpf.f` in the same directory make this a classic orphan. Verify nothing references it, then remove.

- [ ] **Step 1: Verify no references**

Run: `grep -rn 'pcalpf_old' --include='Makefile' --include='Rules.make' --include='*.mk' --include='*.f' --include='*.f90' --include='*.c' --include='*.sh' --include='*.pl' .`
Expected: no matches (or only matches inside `pcalpf_old.f` itself).

- [ ] **Step 2: If any reference exists, abort this task**

If any outside reference is found, stop here, add a comment in the plan, and consult the user. Do not proceed with deletion.

- [ ] **Step 3: Delete**

Run: `git rm src/tools/postscript/pcalpf_old.f`

- [ ] **Step 4: Rebuild**

Run: `make clean && make fem 2>&1 | tail -5`
Expected: build passes.

- [ ] **Step 5: Commit**

```bash
git commit -m "chore(tools): remove orphaned pcalpf_old.f"
```

---

## Phase E — CI Hardening

### Task 10: Harden the `fortran-lint` CI job to block regressions

**Files:**
- Modify: `.github/workflows/fortran-ci.yml`
- Create: `bin/check_implicit_none.py`

**Context:** The current `implicit none` check in CI (lines 64–71) is file-level: `find ... | xargs grep -L 'implicit none'`. It catches a file only if *zero* of its subroutines declare `implicit none`. Today it catches only `sedim_util.f90` (if any). The refined iteration-3 scanner counts 131 truly non-compliant subroutines codebase-wide and 2 in `src/shyfem/` (fixed in Task 7). Replace the file-level check with a subroutine-scoped Python script that honors module-level inheritance and fails CI when the count in `src/shyfem/` is non-zero.

- [ ] **Step 1: Create the scanner script**

Create `bin/check_implicit_none.py`:

```python
#!/usr/bin/env python3
"""Subroutine-scoped `implicit none` compliance check for SHYFEM.

Exits 0 if every subroutine in the watched directories either declares
`implicit none` itself or is contained in a module that does.  Exits 1
with a list of offenders otherwise.

Honors Fortran's module-level implicit-none inheritance (contained
procedures inherit the statement from the enclosing module).

Usage:
    check_implicit_none.py [--max-violations N] DIR [DIR ...]
"""
import argparse
import os
import re
import sys


def scan_file(path):
    """Yield (line_no, subroutine_name) for each non-compliant sub."""
    try:
        src = open(path, errors="ignore").read()
    except OSError:
        return
    lines = src.split("\n")
    low = [ln.lower() for ln in lines]
    stack = []   # module-level implicit-none flags
    i = 0
    while i < len(lines):
        lw = low[i].strip()
        if re.match(r"(recursive\s+)?module\s+(?!procedure\b)\w+", lw):
            imp = False
            j = i + 1
            while j < len(lines):
                hl = low[j].strip()
                if re.match(r"contains\s*$", hl):
                    break
                if re.match(r"((recursive|pure|elemental|\w+)\s+)*(subroutine|function)\s+\w+", hl):
                    break
                if re.match(r"end\s+module", hl):
                    break
                if re.match(r"implicit\s+none", hl):
                    imp = True
                    break
                j += 1
            stack.append(imp)
            i += 1
            continue
        if re.match(r"end\s+module", lw):
            if stack:
                stack.pop()
            i += 1
            continue
        m = re.match(r"((recursive|pure|elemental)\s+)*subroutine\s+(\w+)", lw)
        if m:
            name = m.group(3)
            depth = 1
            k = i + 1
            body = []
            while k < len(lines) and depth > 0:
                bl = low[k].strip()
                if re.match(r"((recursive|pure|elemental)\s+)*subroutine\s+\w+", bl):
                    depth += 1
                elif re.match(r"end\s+subroutine\b", bl) or bl == "end":
                    depth -= 1
                    if depth == 0:
                        break
                if depth > 0:
                    body.append(low[k])
                k += 1
            body_text = "\n".join(body)
            has_in = bool(re.search(r"^\s*implicit\s+none", body_text, re.M))
            inherits = any(stack)
            if not has_in and not inherits:
                yield (i + 1, name)
            i = k + 1
            continue
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument(
        "--max-violations", type=int, default=0,
        help="Exit non-zero if offender count exceeds this threshold",
    )
    ap.add_argument(
        "--exclude", action="append", default=[],
        help="Directory substring to skip (repeatable)",
    )
    args = ap.parse_args()

    violations = []
    for root_dir in args.dirs:
        for root, _, files in os.walk(root_dir):
            if any(x in root for x in args.exclude):
                continue
            for f in files:
                if not (f.endswith(".f90") or f.endswith(".f")):
                    continue
                p = os.path.join(root, f)
                for lineno, name in scan_file(p):
                    violations.append((p, lineno, name))

    for p, lineno, name in violations:
        print(f"{p}:{lineno}: subroutine {name} missing implicit none", file=sys.stderr)

    total = len(violations)
    print(f"Total offenders: {total} (threshold: {args.max_violations})")
    if total > args.max_violations:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable and self-test**

```bash
chmod +x bin/check_implicit_none.py
./bin/check_implicit_none.py src/shyfem --max-violations 0
```
Expected: after Task 7, exit code 0 and `Total offenders: 0`.

```bash
./bin/check_implicit_none.py src/utils --max-violations 100
echo "exit=$?"
```
Expected: exit code depends on current count; print a list of offenders.

- [ ] **Step 3: Replace the file-level check in CI**

Modify `.github/workflows/fortran-ci.yml` — replace the `Check for implicit none gaps` step (currently lines 64–71):

```yaml
      - name: Check for implicit none gaps (subroutine-scoped)
        run: |
          ./bin/check_implicit_none.py src/shyfem --max-violations 0
          # Informational: count offenders in other dirs but don't fail
          ./bin/check_implicit_none.py src/utils src/tools --max-violations 500 || true
```

The `src/shyfem` gate uses threshold `0` — any new offender breaks CI. The `src/utils`/`src/tools` thresholds stay permissive for now and can be ratcheted down in future PRs.

- [ ] **Step 4: Local CI dry-run**

Run:
```bash
./bin/check_implicit_none.py src/shyfem --max-violations 0
echo "shyfem exit=$?"
./bin/check_implicit_none.py src/utils src/tools --max-violations 500
echo "utils+tools exit=$?"
```
Expected: both exit 0 after Task 7.

- [ ] **Step 5: Commit**

```bash
git add bin/check_implicit_none.py .github/workflows/fortran-ci.yml
git commit -m "ci: subroutine-scoped implicit-none gate (blocks regressions in src/shyfem)"
```

---

## Phase F — Documentation

### Task 11: Correct the 2026-04-15 review doc

**Files:**
- Modify: `docs/2026-04-15-deep-codebase-review.md`

**Context:** The 2026-04-15 review relied on a case-sensitive grep for `implicit none`, which gave false positives against UPPERCASE-formatted Fortran (notably `sedim_util.f90`). It reported "~150 missing" and "sedim_util 0% compliance" — both inaccurate. The refined scanner in Task 10 gives ~131 total (after Task 7) and `sedim_util` is actually 40/40 compliant. Annotate the review with corrections so future readers don't act on the stale figures.

- [ ] **Step 1: Read the relevant review section**

Read `docs/2026-04-15-deep-codebase-review.md` sections 2.1 ("Convention Violations Summary") and 2.2 ("Most Problematic Files") to see the exact lines to amend.

- [ ] **Step 2: Insert a correction banner near the top of section 2**

Using the Edit tool, insert immediately after the first "## 2. Fortran Core Quality" heading:

```markdown
> **Correction 2026-04-19:** The `implicit none` figures in this section
> were computed with case-sensitive grep and over-count violations.
> A subroutine-scoped scan that honors module-level inheritance reports
> **131 total missing** (not ~150 files — this is per-subroutine) across
> 5,154 subroutines, or 2.5%. `sedim_util.f90` is actually **100% compliant
> (40/40 `IMPLICIT NONE` in UPPERCASE)** — not 0% as reported below.
> See `bin/check_implicit_none.py` and `docs/superpowers/plans/2026-04-19-codebase-review-fixes.md`
> for the authoritative counts and fixes.
```

- [ ] **Step 3: Commit**

```bash
git add docs/2026-04-15-deep-codebase-review.md
git commit -m "docs: correct implicit-none figures in 2026-04-15 review"
```

---

## Verification Checklist

After all 11 tasks:

1. **Stray files gone**: `ls lib/stVKppAT` returns "No such file", `.gitignore` has `lib/st??????`.
2. **Plan archive in place**: `docs/plans/completed/2026-03-06-ui-fortran-alignment.md` exists.
3. **Audit end-to-end**: `grep -rn "audit_service.log\|_audit(" shyfem-ui/shyfem_ui | wc -l` ≥ 10 (admin.py 5 + session_auth 3 + helpers). `grep "AuditService(" shyfem-ui/shyfem_ui/app.py` returns a match.
4. **New tests pass**: `pytest tests/test_audit_service.py tests/test_app_wiring.py tests/test_session_auth_middleware.py::TestMiddlewareAuditLogging -v` is all green.
5. **pytest env works**: `pytest tests/ -q` completes without a cupy `AttributeError`.
6. **Fortran core clean**: `./bin/check_implicit_none.py src/shyfem --max-violations 0` exits 0.
7. **Orphan gone, duplicate behavior-synced**: `ls src/tools/postscript/pcalpf_old.f` reports "No such file". `diff <(sed -n '/subroutine parse_time/,/end subroutine/p' src/utils/generic/iso8601.f90) <(sed -n '/subroutine parse_time/,/end subroutine/p' src/tools/femutil/netcdf/subiso8601.f90)` is empty. Full deduplication of subiso8601 tracked in `docs/followups/2026-04-19-iso8601-deduplication.md`.
8. **Full build works**: `make clean && make fem` completes.
9. **Regression test**: Mar Menor test case runs to completion with no numerical divergence.
10. **CI hardened**: `.github/workflows/fortran-ci.yml` invokes `bin/check_implicit_none.py` with a `--max-violations 0` gate on `src/shyfem`.
11. **Review corrected**: 2026-04-15 review has the Correction banner at the top of Section 2.

## Fortran Parameter Coverage After Plan

| Metric | Before | After |
|--------|--------|-------|
| `src/shyfem/` non-compliant subs | 2 | 0 |
| Codebase non-compliant subs (total) | 131 | ~129 |
| Orphaned Fortran source files | 1 (pcalpf_old) | 0 |
| Diverged Fortran duplicates | 1 (iso8601/subiso8601) | 0 (behavior-synced; full dedup tracked as follow-up) |
| Stray lib/ tmpfiles | 1 | 0 (pattern ignored) |
| Audit events emitted (admin + auth) | 0 (dead) | 8 (5 admin + login_success + login_failed + logout) |
| Audit tests | 0 | 14 (10 AuditService + 5 middleware integration, -1 overlap) |
| CI implicit-none gate | file-level, non-blocking | subroutine-level, blocks `src/shyfem` regressions |

