# Phase 31: Health Endpoint — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `/health` HTTP endpoint that returns JSON status (version, uptime, DB, queue) and bypasses auth/rate-limiting.

**Architecture:** New `HealthCheckMiddleware` ASGI class wraps the app as the outermost middleware. It intercepts `GET /health` and returns JSON directly. DB health is probed via `SELECT 1`. Active job count uses `getattr(job_queue, 'active_job_count', -1)` to duck-type LocalJobQueue without changing the abstract base.

**Tech Stack:** Python ASGI, stdlib json, SQLAlchemy text(), pytest + pytest-asyncio

---

### Task 1: Implement HealthCheckMiddleware with tests

**Files:**
- Modify: `shyfem_ui/app.py` (after `CacheHeaderMiddleware`, before `_HEAD_EXTRAS`)
- Create: `tests/test_health.py`

**Step 1: Write the failing tests**

Create `tests/test_health.py`:

```python
"""Tests for HealthCheckMiddleware."""

import json
import time

import pytest

from shyfem_ui.app import HealthCheckMiddleware


def _http_scope(path: str = "/", method: str = "GET") -> dict:
    return {
        "type": "http",
        "path": path,
        "method": method,
        "client": ("127.0.0.1", 9999),
        "headers": [],
    }


def _ws_scope() -> dict:
    return {"type": "websocket", "path": "/ws", "client": ("127.0.0.1", 9999), "headers": []}


async def _noop_receive():
    return {}


async def _mock_app(scope, receive, send):
    body = b"OK"
    await send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"text/plain"]]})
    await send({"type": "http.response.body", "body": body})


def _mock_db_check_ok():
    return True


def _mock_db_check_fail():
    raise RuntimeError("DB down")


def _mock_job_queue(active=3):
    class Q:
        @property
        def active_job_count(self):
            return active
    return Q()


def _mock_job_queue_no_attr():
    return object()


class TestHealthCheckMiddleware:

    @pytest.mark.asyncio
    async def test_health_returns_200_json(self):
        mw = HealthCheckMiddleware(_mock_app, db_check=_mock_db_check_ok, job_queue=_mock_job_queue())
        sent = []
        await mw(_http_scope("/health"), _noop_receive, sent.append)
        assert sent[0]["status"] == 200
        headers = dict(sent[0]["headers"])
        assert headers[b"content-type"] == b"application/json"
        body = json.loads(sent[1]["body"])
        assert body["status"] == "ok"
        assert body["version"] == "0.1.0"
        assert body["database"] == "ok"
        assert body["active_jobs"] == 3
        assert "uptime_seconds" in body

    @pytest.mark.asyncio
    async def test_health_db_error_returns_degraded(self):
        mw = HealthCheckMiddleware(_mock_app, db_check=_mock_db_check_fail, job_queue=_mock_job_queue())
        sent = []
        await mw(_http_scope("/health"), _noop_receive, sent.append)
        body = json.loads(sent[1]["body"])
        assert body["status"] == "degraded"
        assert body["database"] == "error"
        assert body["active_jobs"] == 3

    @pytest.mark.asyncio
    async def test_health_no_job_queue_attr_returns_minus_one(self):
        mw = HealthCheckMiddleware(_mock_app, db_check=_mock_db_check_ok, job_queue=_mock_job_queue_no_attr())
        sent = []
        await mw(_http_scope("/health"), _noop_receive, sent.append)
        body = json.loads(sent[1]["body"])
        assert body["active_jobs"] == -1
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_non_health_path_passes_through(self):
        mw = HealthCheckMiddleware(_mock_app, db_check=_mock_db_check_ok, job_queue=_mock_job_queue())
        sent = []
        await mw(_http_scope("/"), _noop_receive, sent.append)
        assert sent[0]["status"] == 200
        assert sent[1]["body"] == b"OK"

    @pytest.mark.asyncio
    async def test_post_health_passes_through(self):
        mw = HealthCheckMiddleware(_mock_app, db_check=_mock_db_check_ok, job_queue=_mock_job_queue())
        sent = []
        await mw(_http_scope("/health", method="POST"), _noop_receive, sent.append)
        assert sent[1]["body"] == b"OK"

    @pytest.mark.asyncio
    async def test_websocket_bypasses(self):
        call_count = 0
        async def ws_app(scope, receive, send):
            nonlocal call_count
            call_count += 1
        mw = HealthCheckMiddleware(ws_app, db_check=_mock_db_check_ok, job_queue=_mock_job_queue())
        await mw(_ws_scope(), _noop_receive, lambda msg: None)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_uptime_increases(self):
        mw = HealthCheckMiddleware(_mock_app, db_check=_mock_db_check_ok, job_queue=_mock_job_queue())
        sent = []
        await mw(_http_scope("/health"), _noop_receive, sent.append)
        body = json.loads(sent[1]["body"])
        assert body["uptime_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_both_db_and_queue_error(self):
        class BadQueue:
            @property
            def active_job_count(self):
                raise RuntimeError("queue broken")
        mw = HealthCheckMiddleware(_mock_app, db_check=_mock_db_check_fail, job_queue=BadQueue())
        sent = []
        await mw(_http_scope("/health"), _noop_receive, sent.append)
        body = json.loads(sent[1]["body"])
        assert body["status"] == "degraded"
        assert body["database"] == "error"
        assert body["active_jobs"] == -1
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_health.py -v`
Expected: FAIL — `cannot import name 'HealthCheckMiddleware'`

**Step 3: Implement the middleware**

In `shyfem_ui/app.py`, add the import at the top (after existing imports, around line 11):

```python
import json
```

Then after `CacheHeaderMiddleware` class (around line 330, before `_HEAD_EXTRAS`), add:

```python
class HealthCheckMiddleware:
    """ASGI middleware that serves a /health JSON endpoint.

    Placed as the outermost middleware so it bypasses auth and rate limiting.
    """

    def __init__(self, app, db_check=None, job_queue=None):
        self.app = app
        self._start_time = time.monotonic()
        self._db_check = db_check
        self._job_queue = job_queue

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if scope.get("path") != "/health" or scope.get("method", "GET") != "GET":
            return await self.app(scope, receive, send)

        from shyfem_ui import __version__

        # Probe database
        db_ok = True
        try:
            if self._db_check:
                self._db_check()
        except Exception:
            db_ok = False

        # Probe job queue
        active_jobs = -1
        try:
            active_jobs = getattr(self._job_queue, "active_job_count", -1)
            if callable(active_jobs):
                active_jobs = active_jobs()
        except Exception:
            active_jobs = -1

        status = "ok" if db_ok and active_jobs != -1 else "degraded"

        payload = {
            "status": status,
            "version": __version__,
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "database": "ok" if db_ok else "error",
            "active_jobs": active_jobs,
        }

        body = json.dumps(payload).encode()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({"type": "http.response.body", "body": body})
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_health.py -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_health.py
git commit -m "$(cat <<'EOF'
feat: add HealthCheckMiddleware with /health JSON endpoint

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Wire middleware into create_app() and add DB check

**Files:**
- Modify: `shyfem_ui/app.py:55-95` (inside `create_app()`)

**Step 1: Write the failing integration test**

Append to `tests/test_health.py`:

```python
from shyfem_ui.app import create_app
from shyfem_ui.config import Config


class TestHealthIntegration:

    def test_health_middleware_is_outermost(self):
        config = Config(shyfem_dir="/tmp/fake")
        app = create_app(config)
        # Outermost wrapper should be HealthCheckMiddleware
        assert isinstance(app, HealthCheckMiddleware)

    def test_health_middleware_has_db_check(self):
        config = Config(shyfem_dir="/tmp/fake")
        app = create_app(config)
        assert app._db_check is not None
        assert callable(app._db_check)
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_health.py::TestHealthIntegration -v`
Expected: FAIL — app is not HealthCheckMiddleware

**Step 3: Wire into create_app()**

In `shyfem_ui/app.py`, add a DB check helper function (before `create_app`):

```python
def _check_db_health():
    """Probe database with SELECT 1."""
    from sqlalchemy import text
    from shyfem_ui.db.base import get_engine
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
```

Then in `create_app()`, after the rate limiter block (line 93) and before `return app` (line 95), add:

```python
    # Health check endpoint (outermost — bypasses auth and rate limiting)
    app = HealthCheckMiddleware(app, db_check=_check_db_health, job_queue=job_queue)
```

**Step 4: Run all health tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_health.py -v`
Expected: 10 PASSED (8 unit + 2 integration)

**Step 5: Run entire test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: all passed, 0 failed

**Step 6: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_health.py
git commit -m "$(cat <<'EOF'
feat: wire HealthCheckMiddleware into create_app() with DB probe

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Update TODO_NEXT.md

**Files:**
- Modify: `shyfem-ui/TODO_NEXT.md:306-325`

**Step 1: Update Phase 31 section**

Replace:

```markdown
## Phase 31: Health & Monitoring

> No way to check if the app is healthy or monitor performance in production.

- [ ] **31.1** Add `/health` HTTP endpoint
  - Bypass auth middleware. Return JSON: `{"status": "ok", "version": "0.1.0",
    "uptime_seconds": N, "database": "ok|error", "queue_depth": N}`
  - Implement as ASGI middleware that intercepts `/health` path

- [ ] **31.2** Add structured JSON logging
  - `SHYFEM_UI_LOG_FORMAT=json` config option
  - Use `python-json-logger` or custom formatter
  - Fields: timestamp, level, logger, message, extra context

- [ ] **31.3** Add `/metrics` Prometheus endpoint
  - Server mode only. Expose: requests_total, request_duration_seconds,
    active_websocket_connections, job_queue_depth, job_status_counts
  - Use `prometheus_client` library (optional dependency)
```

With:

```markdown
## Phase 31: Health & Monitoring

> Health check endpoint for load balancers and uptime monitoring.

- [x] **31.1** Add `/health` HTTP endpoint — 10 tests
  - `HealthCheckMiddleware` as outermost ASGI wrapper (bypasses auth + rate limit)
  - Returns JSON: status, version, uptime_seconds, database, active_jobs
  - `"ok"` when healthy, `"degraded"` when DB or queue has errors
  - DB probe via `SELECT 1`, job count via `active_job_count` property

- [x] **31.2** ~~Add structured JSON logging~~ — SKIPPED
  - Low priority. stdlib logging adequate for current usage.

- [x] **31.3** ~~Add `/metrics` Prometheus endpoint~~ — SKIPPED
  - Adds `prometheus_client` dependency and significant instrumentation. Low ROI.
```

**Step 2: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/TODO_NEXT.md
git commit -m "$(cat <<'EOF'
docs: mark Phase 31 complete in TODO_NEXT.md

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```
