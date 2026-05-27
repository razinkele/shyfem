# Trusted Server-Side Identity in the Shiny WebSocket Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `get_current_user()` return the real user inside Shiny reactive/WebSocket handlers in the proxied production deployment, so the existing per-project access guards, project activation, and project listing enforce correctly — closing the access-control gap in `docs/followups/2026-05-27-prod-viewer-write-bypass.md`.

**Architecture:** A distinct, server-issued, session-lived **WS-auth token** is minted by the cookie-authenticated `whoami` endpoint, attached by the browser to Shiny's WebSocket URL (`?_wsauth=`), and validated in `SessionAuthMiddleware`'s WS branch, which then sets `_user_var` to the real user. The token is a pointer to the existing `AuthSession` (it inherits the session's validity), so no new auth model semantics are introduced. **Approach 1** (URL transport) is gated on a feasibility spike (Phase 0); **Approach 2** (token via `setInputValue` + a session-scoped identity reactive + rewired guards) is the fallback if the spike fails.

**Tech Stack:** Python 3.13, Shiny for Python, Starlette/ASGI middleware, SQLAlchemy + Alembic (SQLite), pytest + pytest-asyncio, Playwright.

**Spec:** `docs/superpowers/specs/2026-05-28-ws-trusted-identity-design.md`

**Conventions for every task:**
- Run tests from `/home/razinka/shyfem/shyfem-ui/` with: `CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest <args>`.
- Playwright tests are excluded from default pytest (`--ignore-glob`); run them explicitly.
- Commit after each task with conventional-commit messages.
- All paths are relative to `/home/razinka/shyfem/shyfem-ui/` unless absolute.

---

## Phase 0 — Feasibility spike (decides Approach 1 vs 2) — DO THIS FIRST

**Goal:** Determine whether a query parameter can be attached to Shiny-for-Python's WebSocket URL AND survives the Shiny Server → app internal-WS hop. The outcome selects Phase 3A (Approach 1) or Phase 3B (Approach 2). This is a throwaway spike — its code is reverted; only the recorded finding is kept.

> ⚠️ Part 2 below **requires a Shiny-Server-backed environment** (a local Shiny Server install or the staging/laguna deployment). It cannot be validated on a bare dev box. If no such environment is available at all, skip to Phase 3B (Approach 2) and record that decision.

- [ ] **Step 1: Add a temporary probe in the middleware WS branch.** In `shyfem_ui/middleware/session_auth.py`, inside the `if scope["type"] == "websocket":` block (around line 604), add at the top:

```python
import logging as _spike_log
_spike_log.getLogger("shyfem_ui").warning(
    "SPIKE ws query_string=%r client=%r", scope.get("query_string"), scope.get("client")
)
```

- [ ] **Step 2: Add a temporary client probe.** In `shyfem_ui/app.py`, in the `DOMContentLoaded` JS (near line 408), before Shiny initializes, log `window.location` and attempt to set a WS-URL param via whatever hook Shiny exposes (try, in order: a `Shiny`/`window` config global read at connect time; wrapping `WebSocket`; a query param on the page URL that Shiny echoes). The goal is to discover the working hook, not to finalize it.

- [ ] **Step 3: Local run.** Start the app locally (`/opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app`), open it, and confirm the SPIKE log shows the param arriving in `query_string`. Records the client hook that worked. Expected: param visible (proves the client half only — there is no proxy locally).

- [ ] **Step 4: Behind Shiny Server (decisive).** Deploy the probe build to a Shiny-Server-backed env. Open the app through the proxy and confirm whether the SPIKE log shows the param surviving the internal-WS hop. Also confirm: (a) Shiny's auto-reconnect (kill the network briefly) reuses the URL with the param intact; (b) Shiny Server does not open its own token-less internal WS that a strict middleware would wrongly close.

- [ ] **Step 5: Record the decision + revert the probes.** Write the findings (which client hook works; did the param survive the proxy; reconnect behavior) into a new section "Spike results (YYYY-MM-DD)" at the bottom of `docs/superpowers/specs/2026-05-28-ws-trusted-identity-design.md`. Revert the Step 1–2 probe code. Commit:

```bash
git add docs/superpowers/specs/2026-05-28-ws-trusted-identity-design.md
git commit -m "docs(spec): record WS-token transport feasibility spike results"
```

**Branch decision:** param survives the proxy + reconnect intact → execute **Phase 3A** (and skip 3B). Otherwise → execute **Phase 3B** (and skip 3A). Phases 1, 2, 4, 5 run regardless.

---

## Phase 1 — Shared backend: WS-auth token model + service methods

### Task 1.1: `WSAuthToken` model + migration

**Files:**
- Modify: `shyfem_ui/models/user.py` (add model near `AuthSession`, ~line 103)
- Create: `migrations/versions/<generated>_ws_auth_tokens.py`

- [ ] **Step 1: Add the model.** In `shyfem_ui/models/user.py`, after the `AuthSession` class, add (mirroring `AuthSession`'s column style and `is_expired`):

```python
class WSAuthToken(Base):
    """A short-lived, server-issued token that bridges the authenticated HTTP
    session into the Shiny WebSocket scope. Distinct from the session cookie;
    a pointer to the owning AuthSession, whose validity it inherits."""

    __tablename__ = "ws_auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    session_token: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    def __repr__(self) -> str:
        return f"<WSAuthToken(id={self.id}, user_id={self.user_id}, expired={self.is_expired})>"
```

- [ ] **Step 2: Generate the migration.** Current Alembic head is `379248193d58`. Run:

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m alembic revision --autogenerate -m "ws_auth_tokens"
```

- [ ] **Step 3: Verify the migration.** Open the generated file. Confirm `down_revision = '379248193d58'` and that `upgrade()` creates the table; if autogenerate missed it, write it manually:

```python
def upgrade() -> None:
    op.create_table(
        "ws_auth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("session_token", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ws_auth_tokens_token", "ws_auth_tokens", ["token"], unique=True)
    op.create_index("ix_ws_auth_tokens_session_token", "ws_auth_tokens", ["session_token"])


def downgrade() -> None:
    op.drop_index("ix_ws_auth_tokens_session_token", table_name="ws_auth_tokens")
    op.drop_index("ix_ws_auth_tokens_token", table_name="ws_auth_tokens")
    op.drop_table("ws_auth_tokens")
```

- [ ] **Step 4: Apply + verify.**

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m alembic upgrade head
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m alembic heads   # new revision is head
```
Expected: upgrade runs cleanly; `ws_auth_tokens` exists.

- [ ] **Step 5: Commit.**

```bash
git add shyfem_ui/models/user.py migrations/versions/*ws_auth_tokens*.py
git commit -m "feat(auth): add WSAuthToken model + migration"
```

### Task 1.2: `AuthService.create_ws_token` / `validate_ws_token`

**Files:**
- Modify: `shyfem_ui/services/auth_service.py` (after `cleanup_expired_sessions`, ~line 418; import `WSAuthToken`)
- Test: `tests/test_auth_service.py` (extend; if absent, create)

- [ ] **Step 1: Write the failing test.** In `tests/test_auth_service.py`:

```python
from datetime import datetime, timedelta, timezone

def _svc(db_factory):
    from shyfem_ui.services.auth_service import AuthService
    return AuthService(session_factory=db_factory)

class TestWSToken:
    def test_create_and_validate_returns_user(self, auth_service, a_user):
        # a_user: a created active user; auth_service bound to the test db.
        sess = auth_service.create_session(a_user.id)
        ws = auth_service.create_ws_token(a_user.id, sess)
        assert isinstance(ws, str) and ws != sess          # distinct from cookie token
        u = auth_service.validate_ws_token(ws)
        assert u is not None and u["id"] == a_user.id

    def test_unknown_token_returns_none(self, auth_service):
        assert auth_service.validate_ws_token("nope") is None

    def test_invalid_when_parent_session_gone(self, auth_service, a_user):
        sess = auth_service.create_session(a_user.id)
        ws = auth_service.create_ws_token(a_user.id, sess)
        auth_service.delete_session(sess)                   # logout
        assert auth_service.validate_ws_token(ws) is None   # inherits session death
```

(Build `auth_service`/`a_user` fixtures from the existing patterns in `tests/test_auth_service.py` / `tests/test_access_control.py`; bind `AuthService(session_factory=...)` to the test DB. Create an active `User` with a `password_hash`.)

- [ ] **Step 2: Run → FAIL.** `CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_auth_service.py::TestWSToken -v` → `AttributeError: 'AuthService' object has no attribute 'create_ws_token'`.

- [ ] **Step 3: Implement.** Add `WSAuthToken` to the model import at the top of `auth_service.py` (the line importing `AuthSession`, `User`), then:

```python
def create_ws_token(self, user_id: int, session_token: str, ttl_hours: int = 24) -> str:
    """Mint a WS-auth token bound to an existing HTTP session.

    Distinct from the session cookie value; expires no later than the session.
    """
    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    session = self._session_factory()
    try:
        session.add(WSAuthToken(
            token=token, session_token=session_token,
            user_id=user_id, expires_at=expires_at,
        ))
        session.commit()
        return token
    except Exception:
        session.rollback()
        logger.exception("Database error in create_ws_token")
        raise
    finally:
        session.close()

def validate_ws_token(self, token: str) -> dict | None:
    """Validate a WS-auth token. Returns the user dict only if the token row
    exists, is unexpired, AND its parent HTTP session still validates."""
    session = self._session_factory()
    try:
        row = session.query(WSAuthToken).filter_by(token=token).first()
        if row is None:
            return None
        if row.is_expired:
            session.delete(row)
            session.commit()
            return None
        parent = row.session_token
    except Exception:
        session.rollback()
        logger.exception("Database error in validate_ws_token")
        raise
    finally:
        session.close()
    # Inherit the parent session's validity (expiry, user active, logout).
    return self.validate_session(parent)
```

- [ ] **Step 4: Run → PASS.** Same pytest command → green.
- [ ] **Step 5: Commit.**

```bash
git add shyfem_ui/services/auth_service.py tests/test_auth_service.py
git commit -m "feat(auth): create_ws_token + validate_ws_token (session-inherited validity)"
```

### Task 1.3: purge WS tokens on logout + expiry cleanup

**Files:**
- Modify: `shyfem_ui/services/auth_service.py` (`delete_session` ~377, `cleanup_expired_sessions` ~398)
- Test: `tests/test_auth_service.py`

- [ ] **Step 1: Write the failing test.** Add to `TestWSToken`:

```python
def test_cleanup_removes_expired_ws_tokens(self, auth_service, a_user):
    from shyfem_ui.models.user import WSAuthToken
    sess = auth_service.create_session(a_user.id)
    ws = auth_service.create_ws_token(a_user.id, sess, ttl_hours=-1)  # already expired
    removed = auth_service.cleanup_expired_sessions()
    assert removed >= 1
    assert auth_service.validate_ws_token(ws) is None
```

- [ ] **Step 2: Run → FAIL** (`cleanup_expired_sessions` doesn't touch `ws_auth_tokens` yet; the count won't include it).
- [ ] **Step 3: Implement.** In `delete_session`, after deleting the `AuthSession`, also purge its WS tokens (before `commit()`):

```python
            session.query(WSAuthToken).filter_by(session_token=token).delete()
```

In `cleanup_expired_sessions`, after computing `count` for expired sessions, also delete expired WS tokens and include them in the count:

```python
            ws_expired = session.query(WSAuthToken).filter(WSAuthToken.expires_at <= now).all()
            count += len(ws_expired)
            for w in ws_expired:
                session.delete(w)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit.**

```bash
git add shyfem_ui/services/auth_service.py tests/test_auth_service.py
git commit -m "feat(auth): purge WS tokens on logout and during expiry cleanup"
```

---

## Phase 2 — `whoami` returns the WS token

### Task 2.1: mint + return the token from `_handle_whoami`

**Files:**
- Modify: `shyfem_ui/middleware/session_auth.py` (`_handle_whoami`, ~801-841)
- Test: `tests/test_session_auth.py` (extend; if absent, create — drive `_handle_whoami` directly)

- [ ] **Step 1: Write the failing test.** In `tests/test_session_auth.py`, exercise `_handle_whoami` with a valid session and assert the JSON body contains a non-empty `ws_token` that `validate_ws_token` accepts:

```python
import json, asyncio

def test_whoami_returns_ws_token(auth_middleware, valid_session_token, auth_service):
    # auth_middleware: a SessionAuthMiddleware built over the test app + test db.
    # valid_session_token: from auth_service.create_session(user.id).
    sent = []
    async def send(msg): sent.append(msg)
    asyncio.get_event_loop().run_until_complete(
        auth_middleware._handle_whoami(valid_session_token, send)
    )
    body = b"".join(m["body"] for m in sent if m["type"] == "http.response.body")
    data = json.loads(body)
    assert data["ws_token"]
    assert auth_service.validate_ws_token(data["ws_token"]) is not None
```

(Reuse/adapt existing `session_auth` test fixtures; build the middleware with the test DB-backed `AuthService`.)

- [ ] **Step 2: Run → FAIL** (`KeyError: 'ws_token'`).
- [ ] **Step 3: Implement.** In `_handle_whoami`, after the `user is None` guard, mint the token and add it to the body:

```python
        ws_token = self.auth_service.create_ws_token(user["id"], session_token)
        body = json.dumps(
            {
                "username": user.get("username", ""),
                "display_name": user.get("display_name", ""),
                "role": user.get("role", ""),
                "ws_token": ws_token,
            }
        ).encode()
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit.**

```bash
git add shyfem_ui/middleware/session_auth.py tests/test_session_auth.py
git commit -m "feat(auth): whoami mints and returns a WS-auth token"
```

---

## Phase 3A — Approach 1: URL transport + middleware enforcement (EXECUTE ONLY IF the Phase 0 spike passed)

> 🛑 If the spike failed, SKIP this whole phase and execute Phase 3B instead.

### Task 3A.1: middleware validates `_wsauth` and sets the real user

**Files:**
- Modify: `shyfem_ui/middleware/session_auth.py` (WS branch, ~604-625)
- Test: `tests/test_session_auth.py`

- [ ] **Step 1: Write the failing test.** Drive the middleware's `__call__` with a `websocket` scope carrying `query_string=b"_wsauth=<valid>"` and assert the wrapped app runs with `get_current_user()` returning the real user (capture it via a stub inner app that reads `_user_var`). Add a second case: an invalid `_wsauth` in server mode (`root_path="/x"`) → a `websocket.close` with code `4001` is sent.

```python
# Pseudocode shape — adapt to the existing middleware test harness:
# scope = {"type":"websocket","path":"/","query_string":b"_wsauth="+ws.encode(),
#          "client":("127.0.0.1",0),"headers":[]}
# captured = {}
# async def inner_app(s, r, sd):
#     from shyfem_ui.middleware.session_auth import get_current_user
#     captured["user"] = get_current_user()
# mw = SessionAuthMiddleware(inner_app, auth_service=..., root_path="/x")
# run mw(scope, recv, send); assert captured["user"]["id"] == user.id
```

- [ ] **Step 2: Run → FAIL** (current code sets `user=None`).
- [ ] **Step 3: Implement.** In the WS branch, replace the body so that when the cookie yields no user, a valid `_wsauth` query param establishes identity:

```python
        if scope["type"] == "websocket":
            user = None
            if session_token:
                user = self.auth_service.validate_session(session_token)

            if user is None:
                # Bridge: validate a WS-auth token from the query string.
                from urllib.parse import parse_qs
                qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
                ws_token = (qs.get("_wsauth") or [None])[0]
                if ws_token:
                    user = self.auth_service.validate_ws_token(ws_token)

            if user is None:
                client = scope.get("client")
                client_host = client[0] if client else None
                is_local = client_host in ("127.0.0.1", "::1")
                if not (self.root_path and is_local):
                    await send({"type": "websocket.close", "code": 4001})
                    return
                # else: local/unauth mode (root_path empty) — user stays None.

            token = _user_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)
            return
```

(Note: this keeps the existing local-mode admit-None path for `root_path=""`. Task 3A.3 tightens server-mode behavior.)

- [ ] **Step 4: Run → PASS** (valid token → real user; the close-on-invalid case is covered in 3A.3's test if not already here).
- [ ] **Step 5: Commit.**

```bash
git add shyfem_ui/middleware/session_auth.py tests/test_session_auth.py
git commit -m "feat(auth): validate WS-auth token in the WebSocket middleware branch"
```

### Task 3A.2: attach `?_wsauth=` to Shiny's WebSocket URL

**Files:**
- Modify: `shyfem_ui/app.py` (the `whoami` `.then(...)` block, ~423-429, using the client hook recorded by the spike)

- [ ] **Step 1: Implement** (no unit test — this is browser glue verified by Phase 4 integration). In the `fetch('api/whoami')` success handler, after reading `data`, attach the token using the hook the spike identified. Example shape (replace with the spike's confirmed mechanism):

```javascript
    if (data.ws_token) {
      // Attach to Shiny's WS URL before it connects (mechanism per spike).
      window.__shyfem_ws_token = data.ws_token;
      // e.g. if Shiny reads a query param on the page/WS URL:
      // patch the WebSocket URL builder / set the documented Shiny option here.
    }
```

- [ ] **Step 2: Manual smoke (local).** Start the app; in DevTools confirm the WS connects with `?_wsauth=` present and the app still loads.
- [ ] **Step 3: Commit.**

```bash
git add shyfem_ui/app.py
git commit -m "feat(auth): attach WS-auth token to the Shiny WebSocket URL"
```

### Task 3A.3: server-mode token-less WS → close (defense)

**Files:**
- Modify: `shyfem_ui/middleware/session_auth.py` (WS branch — already closes when `not (root_path and is_local)`; this task adds an explicit test pinning server-mode behavior)
- Test: `tests/test_session_auth.py`

- [ ] **Step 1: Write the test.** Server mode (`root_path="/x"`), `is_local=True`, **no** `_wsauth` and no cookie → assert a `websocket.close` `4001` is sent (NOT admitted as `None`).

> Decision pinned: behind the proxy, a token-less WS is closed, never admitted as `None`. The Step-3 code in 3A.1 already does this *only* when `not (root_path and is_local)`. Because Shiny Server connects from localhost (`is_local=True`) with `root_path` set, that path currently admits `None`. **Tighten it:** in server mode, require identity. Change the final guard to close whenever `user is None` and `root_path` is set:

```python
            if user is None:
                client = scope.get("client")
                client_host = client[0] if client else None
                is_local = client_host in ("127.0.0.1", "::1")
                if self.root_path:                 # server mode → identity required
                    await send({"type": "websocket.close", "code": 4001})
                    return
                if not is_local:                   # local mode but non-local client
                    await send({"type": "websocket.close", "code": 4001})
                    return
                # local mode + localhost → user stays None (dev/test)
```

- [ ] **Step 2: Run → FAIL then implement → PASS.** Run the full `tests/test_session_auth.py` and confirm the local-mode tests (root_path="") still pass and the new server-mode close test passes.

> ⚠️ This depends on the spike's confirmation that Shiny Server does NOT open its own token-less internal WS (Phase 0, Step 4b). If it does, those connections would be closed — in that case, narrow the close to connections that look like browser sessions, per the spike findings, and document it here.

- [ ] **Step 3: Commit.**

```bash
git add shyfem_ui/middleware/session_auth.py tests/test_session_auth.py
git commit -m "feat(auth): require WS identity in server mode (close token-less WS)"
```

---

## Phase 3B — Approach 2 fallback: setInputValue transport + reactive identity (EXECUTE ONLY IF the Phase 0 spike failed)

> 🛑 If the spike passed, SKIP this whole phase (Phase 3A is in effect).

**Why this differs:** the token cannot ride the WS URL, so the middleware cannot set `_user_var`. Instead the browser pushes the token as a reactive input, a session-scoped reactive resolves it to a real user server-side once, and the consumers read that resolved identity. This is larger because it rewires the consumers; the token is still server-validated (non-spoofable).

### Task 3B.1: push the token via `setInputValue`

**Files:** Modify `shyfem_ui/app.py` (whoami `.then` block).

- [ ] **Step 1: Implement.** In the `fetch('api/whoami')` handler:

```javascript
    if (data.ws_token && window.Shiny && window.Shiny.setInputValue) {
      window.Shiny.setInputValue('_wsauth', data.ws_token, {priority: 'event'});
    }
```
- [ ] **Step 2: Commit.** `git commit -m "feat(auth): push WS-auth token via setInputValue (fallback transport)"`

### Task 3B.2: session-scoped identity resolver

**Files:**
- Modify: `shyfem_ui/app.py` (top-level server, near the `current_user_role` reactive ~753-758)
- Create: `shyfem_ui/services/ws_identity.py` (pure resolver) + `tests/test_ws_identity.py`

- [ ] **Step 1: Failing test** for a pure resolver in `tests/test_ws_identity.py`:

```python
from shyfem_ui.services.ws_identity import resolve_ws_user

def test_resolve_returns_user_for_valid_token(fake_auth):
    # fake_auth.validate_ws_token returns a user dict for "good"
    assert resolve_ws_user("good", fake_auth)["id"] == 1

def test_resolve_none_for_blank_or_invalid(fake_auth):
    assert resolve_ws_user("", fake_auth) is None
    assert resolve_ws_user("bad", fake_auth) is None
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `shyfem_ui/services/ws_identity.py`:

```python
from __future__ import annotations

def resolve_ws_user(ws_token: str | None, auth_service) -> dict | None:
    """Resolve a WS-auth token to a user dict, server-side. Pure wrapper for testability."""
    if not ws_token:
        return None
    return auth_service.validate_ws_token(ws_token)
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Wire a session reactive** in `app.py`'s top-level server. Add a reactive value + effect that resolves identity once `input._wsauth()` is set, and expose a getter `current_user()` parallel to the existing `user_role()`:

```python
    _ws_user = reactive.value(None)

    @reactive.effect
    def _resolve_ws_identity():
        from shyfem_ui.services.auth_service import AuthService
        from shyfem_ui.services.ws_identity import resolve_ws_user
        tok = input._wsauth() if "_wsauth" in input else None
        _ws_user.set(resolve_ws_user(tok, AuthService()))

    def current_user():
        # Real, server-validated user in the WS scope (fallback path).
        return _ws_user.get()
```

- [ ] **Step 6: Commit.** `git commit -m "feat(auth): session-scoped WS identity resolver (fallback)"`

### Task 3B.3: rewire consumers to the resolved identity

**Files:** Modify the 9 guarded handlers + `home.py` activation/listing. Each `*_server` must receive `current_user` (thread it from `app.py` like `user_role`/`active_project` are threaded).

> **Pattern (apply to every site):** replace `get_current_user()` with the threaded `current_user()` getter. The guard logic is otherwise unchanged.

- [ ] **Step 1: Thread `current_user` into each page server** the same way `active_project` is threaded in `app.py` (add the kwarg to each `*_server(...)` call and signature).

- [ ] **Step 2: Replace the identity source at each guard.** For each row, change the `get_current_user()` call to the threaded `current_user()`:

| Page | Handler | approx. line |
|---|---|---|
| run.py | `_submit_job` | 590 |
| files.py | `_handle_upload` | 303 |
| files.py | `_do_delete` | 432 |
| partitioning.py | `_run_shyparts` | 243 |
| grid_prep.py | `_run_shypre` | 283 |
| ensemble.py | `_submit_ensemble` | 514 |
| simulation.py | `_confirm_save` | 350 |
| physics.py | `save_file` | 448 |
| postprocess.py | `_run_shyelab` | 498 |

Also: `home.py:_current_user` (253) and the `_refresh_projects`/`_activate_project` user source (281, 661) → use `current_user()`.

- [ ] **Step 3: Run the full suite + Playwright auth tests** after each file's change. Commit per file:

```bash
git commit -m "fix(auth): <page> guards use server-validated WS identity (fallback)"
```

---

## Phase 4 — Integration & isolation tests (prod-config; ties to deferred Phase H, Task H0)

### Task 4.1: a `root_path`-set auth server variant

**Files:**
- Modify: `tests/_test_auth_app.py` (parametrize `root_path`) or add `tests/_test_auth_app_proxy.py`
- Modify: `tests/conftest.py` (add a `pw_proxy_viewer_page` fixture that logs in and ensures the `?_wsauth=`/`setInputValue` path is exercised)

- [ ] **Step 1:** Add an auth-server variant with `root_path="/shyfem-ui"` (matching prod), seeding a `viewer1` user + a shared "Shared" project at `viewer` permission (idempotent), reusing the seeding shape from the deferred Phase H plan.
- [ ] **Step 2:** Smoke test `test_proxy_viewer_can_login_and_identity_resolves` — assert `api/whoami` returns a `ws_token` and, after the app loads, a reactive endpoint reflects the real user (not None). Run → PASS.
- [ ] **Step 3: Commit.** `git commit -m "test(auth): root_path-set auth server variant for prod-config coverage"`

### Task 4.2: viewer cannot perform editor writes (prod config)

**Files:** Create `tests/test_playwright_ws_identity.py`.

- [ ] **Step 1:** Against the `root_path`-set server, drive `viewer1` through the real UI to the shared project and attempt one representative editor write (e.g. `run.py` submit). Assert BOTH: the permission toast appears AND the mutation did not occur (out-of-band DB/job-count check, per the Phase H design). Run → it must FAIL before this plan's fix is in effect and PASS after.
- [ ] **Step 2:** Extend to the remaining 8 handlers (partitioning `.par`/`.bas`, files upload/delete, ensemble submit, simulation save, physics save, postprocess shyelab), each asserting its specific mutation-absence. (Reuse the deferred Phase H H2–H10 design; these now run against the fixed identity path.)
- [ ] **Step 3: Commit.** `git commit -m "test(auth): viewer write-denial proven under prod-config WS identity"`

### Task 4.3: read + activation isolation

**Files:** `tests/test_playwright_ws_identity.py`.

- [ ] **Step 1:** As `viewer1`, assert the dashboard lists only projects they own/are shared on (NOT every project). Run → PASS.
- [ ] **Step 2:** As `viewer1`, attempt to activate a non-shared `project_id` (drive the open path) → assert "Project not found"/refused and no context loads. Run → PASS.
- [ ] **Step 3: Commit.** `git commit -m "test(auth): dashboard listing + activation are isolated per user"`

---

## Phase 5 — Rollout documentation

### Task 5.1: document log scrubbing + deploy ordering

**Files:** Modify `docs/followups/2026-05-27-prod-viewer-write-bypass.md` (mark in-progress + link the spec/plan) and add a deployment note where deployment config is documented (search `MEMORY`/deployment notes; e.g. a `docs/` deployment section).

- [ ] **Step 1:** Add a "Deployment steps" subsection: (a) configure the nginx/Shiny Server access-log format to strip the `_wsauth` query param; (b) ship server + client together (a server validating tokens while clients don't yet attach them would close WS connections); (c) heads-up to users that project visibility/editing becomes enforced (was broken-open). 
- [ ] **Step 2: Commit.** `git commit -m "docs: rollout + log-scrubbing steps for WS trusted-identity fix"`

---

## Self-Review

**Spec coverage:**
- Threat model (server-issued, server-validated, session-bound, expiring) → Tasks 1.1–1.3 (distinct table, session-inherited validity, cleanup). ✔
- Architecture data-flow steps 1–5 → whoami mint (2.1), URL attach (3A.2), middleware validate (3A.1), downstream unchanged (no rewire in 3A). ✔
- Component 1 token (distinct, session-lived, not single-use) → 1.1/1.2 (separate `ws_auth_tokens`, inherits parent session, no consume-on-use). ✔
- Component 2 transport + spike → Phase 0; fallback → Phase 3B. ✔
- Component 3 enforcement + local-mode preservation → 3A.1/3A.3 (server-mode close; `root_path=""` stays admit-None). ✔
- Error-handling table → 3A.3 (close 4001), 2.1 (401 unchanged), validate_ws_token fail-closed. ✔
- Testing strategy (unit/middleware/integration/isolation/regression) → 1.2, 2.1, 3A.1/3A.3, Phase 4. ✔
- Rollout (log scrub, deploy ordering, behavior change) → Phase 5. ✔

**Placeholder scan:** Phase 0 client hook and Task 3A.2 JS are intentionally spike-determined (the spike's job is to find the exact mechanism); every backend/test task has concrete code. No "TBD/add error handling" placeholders in the deterministic tasks.

**Type consistency:** `create_ws_token(user_id, session_token, ttl_hours)` and `validate_ws_token(token) -> dict | None` are used consistently in 1.2, 1.3, 2.1, 3A.1, 3B.2. `_wsauth` is the param/input name throughout. `WSAuthToken` table/columns match between 1.1 model and migration.
