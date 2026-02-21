# Phase 29.1: Static Asset Cache Headers — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add ASGI middleware that injects `Cache-Control` headers on static asset responses so browsers cache CSS, JS, fonts, and images.

**Architecture:** New `CacheHeaderMiddleware` class in `app.py` wraps the Shiny app as the innermost middleware. It intercepts `http.response.start` messages for requests whose path ends with a static extension, appending a `Cache-Control: public, max-age=N` header. Config field `static_cache_max_age` (default 86400) controls the value; 0 disables.

**Tech Stack:** Python ASGI, Pydantic settings, pytest + pytest-asyncio

---

### Task 1: Add config field

**Files:**
- Modify: `shyfem_ui/config.py:146-149` (after `trusted_proxies`)

**Step 1: Write the failing test**

Create `tests/test_cache_headers.py`:

```python
"""Tests for CacheHeaderMiddleware ASGI middleware."""

import pytest

from shyfem_ui.config import Config


class TestCacheHeaderConfig:
    """Config field for static_cache_max_age."""

    def test_default_max_age_is_86400(self):
        config = Config(shyfem_dir="/tmp/fake")
        assert config.static_cache_max_age == 86400

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SHYFEM_UI_STATIC_CACHE_MAX_AGE", "3600")
        config = Config(shyfem_dir="/tmp/fake")
        assert config.static_cache_max_age == 3600

    def test_zero_disables(self):
        config = Config(shyfem_dir="/tmp/fake", static_cache_max_age=0)
        assert config.static_cache_max_age == 0
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_cache_headers.py -v`
Expected: FAIL — `static_cache_max_age` attribute does not exist

**Step 3: Add config field**

In `shyfem_ui/config.py`, after `trusted_proxies` field (line 149), add:

```python
    # Static asset caching
    static_cache_max_age: int = Field(
        default=86400,
        description="Cache-Control max-age for static assets in seconds (0 = disabled)"
    )
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_cache_headers.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/config.py shyfem-ui/tests/test_cache_headers.py
git commit -m "feat(config): add static_cache_max_age setting for cache header middleware"
```

---

### Task 2: Implement CacheHeaderMiddleware

**Files:**
- Modify: `shyfem_ui/app.py:289-291` (after `RateLimitMiddleware` class, before `_HEAD_EXTRAS`)

**Step 1: Write the failing tests**

Append to `tests/test_cache_headers.py`:

```python
from shyfem_ui.app import CacheHeaderMiddleware


def _http_scope(path: str = "/") -> dict:
    """Build a minimal HTTP ASGI scope with a path."""
    return {
        "type": "http",
        "path": path,
        "client": ("127.0.0.1", 9999),
        "headers": [],
    }


def _ws_scope() -> dict:
    """Build a minimal WebSocket ASGI scope."""
    return {
        "type": "websocket",
        "path": "/ws",
        "client": ("127.0.0.1", 9999),
        "headers": [],
    }


async def _noop_receive():
    return {}


async def _mock_app(scope, receive, send):
    """Tiny ASGI app that returns 200 with a text/plain body."""
    body = b"OK"
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"text/plain"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({"type": "http.response.body", "body": body})


class TestCacheHeaderMiddleware:
    """Tests for CacheHeaderMiddleware."""

    @pytest.mark.asyncio
    async def test_css_gets_cache_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/static/app.css"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert headers[b"cache-control"] == b"public, max-age=86400"

    @pytest.mark.asyncio
    async def test_js_gets_cache_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/assets/bundle.js"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert headers[b"cache-control"] == b"public, max-age=86400"

    @pytest.mark.asyncio
    async def test_woff2_font_gets_cache_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/fonts/roboto.woff2"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert headers[b"cache-control"] == b"public, max-age=86400"

    @pytest.mark.asyncio
    async def test_png_image_gets_cache_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/img/logo.png"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert headers[b"cache-control"] == b"public, max-age=86400"

    @pytest.mark.asyncio
    async def test_html_path_no_cache_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/index.html"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert b"cache-control" not in headers

    @pytest.mark.asyncio
    async def test_api_path_no_cache_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/api/projects"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert b"cache-control" not in headers

    @pytest.mark.asyncio
    async def test_root_path_no_cache_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert b"cache-control" not in headers

    @pytest.mark.asyncio
    async def test_websocket_bypasses_middleware(self):
        call_count = 0

        async def ws_app(scope, receive, send):
            nonlocal call_count
            call_count += 1

        mw = CacheHeaderMiddleware(ws_app, max_age=86400)
        await mw(_ws_scope(), _noop_receive, lambda msg: None)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_configurable_max_age(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=3600)
        sent = []
        await mw(_http_scope("/static/app.css"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert headers[b"cache-control"] == b"public, max-age=3600"

    @pytest.mark.asyncio
    async def test_max_age_zero_disables_header(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=0)
        sent = []
        await mw(_http_scope("/static/app.css"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert b"cache-control" not in headers

    @pytest.mark.asyncio
    async def test_body_message_passes_through_unchanged(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/static/app.css"), _noop_receive, sent.append)
        assert sent[1] == {"type": "http.response.body", "body": b"OK"}

    @pytest.mark.asyncio
    async def test_original_headers_preserved(self):
        mw = CacheHeaderMiddleware(_mock_app, max_age=86400)
        sent = []
        await mw(_http_scope("/static/app.css"), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        assert headers[b"content-type"] == b"text/plain"
        assert headers[b"cache-control"] == b"public, max-age=86400"
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_cache_headers.py::TestCacheHeaderMiddleware -v`
Expected: FAIL — `cannot import name 'CacheHeaderMiddleware'`

**Step 3: Implement the middleware**

In `shyfem_ui/app.py`, after `RateLimitMiddleware` (line 289), before `_HEAD_EXTRAS` (line 292), add:

```python

_STATIC_EXTENSIONS = frozenset({
    ".css", ".js", ".woff2", ".woff", ".ttf", ".png", ".svg", ".ico",
})


class CacheHeaderMiddleware:
    """ASGI middleware that adds Cache-Control headers to static asset responses."""

    def __init__(self, app, max_age: int = 86400):
        self.app = app
        self.max_age = max_age

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.max_age <= 0:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        # Use posixpath-style suffix extraction (no Path needed)
        dot = path.rfind(".")
        ext = path[dot:].lower() if dot != -1 else ""

        if ext not in _STATIC_EXTENSIONS:
            return await self.app(scope, receive, send)

        cache_value = f"public, max-age={self.max_age}".encode()

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"cache-control", cache_value])
                message = {**message, "headers": headers}
            await send(message)

        return await self.app(scope, receive, send_with_cache)
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_cache_headers.py -v`
Expected: 15 PASSED (3 config + 12 middleware)

**Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_cache_headers.py
git commit -m "feat: add CacheHeaderMiddleware for static asset caching"
```

---

### Task 3: Wire middleware into create_app()

**Files:**
- Modify: `shyfem_ui/app.py:71-75` (inside `create_app()`)

**Step 1: Write the failing integration test**

Append to `tests/test_cache_headers.py`:

```python
from shyfem_ui.app import create_app
from shyfem_ui.config import Config


class TestCacheHeaderIntegration:
    """Integration: middleware is wired into create_app()."""

    def test_create_app_wraps_with_cache_middleware(self):
        config = Config(shyfem_dir="/tmp/fake", static_cache_max_age=7200)
        app = create_app(config)
        # The outermost app won't be CacheHeaderMiddleware (rate limit / auth
        # wrap outside it), but we can verify the config was consumed by
        # checking that the class appears in the middleware chain.
        # Walk the .app chain to find CacheHeaderMiddleware.
        current = app
        found = False
        for _ in range(10):
            if isinstance(current, CacheHeaderMiddleware):
                found = True
                assert current.max_age == 7200
                break
            current = getattr(current, "app", None)
            if current is None:
                break
        assert found, "CacheHeaderMiddleware not found in middleware chain"

    def test_create_app_skips_cache_when_zero(self):
        config = Config(shyfem_dir="/tmp/fake", static_cache_max_age=0)
        app = create_app(config)
        current = app
        for _ in range(10):
            assert not isinstance(current, CacheHeaderMiddleware), \
                "CacheHeaderMiddleware should not be in chain when max_age=0"
            current = getattr(current, "app", None)
            if current is None:
                break
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_cache_headers.py::TestCacheHeaderIntegration -v`
Expected: FAIL — CacheHeaderMiddleware not found in middleware chain

**Step 3: Wire middleware in create_app()**

In `shyfem_ui/app.py`, after `app = App(app_ui, server)` (line 71), before the debug middleware block (line 73), insert:

```python
    # Cache headers for static assets
    if config.static_cache_max_age > 0:
        app = CacheHeaderMiddleware(app, max_age=config.static_cache_max_age)
```

**Step 4: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_cache_headers.py -v`
Expected: 17 PASSED (3 config + 12 middleware + 2 integration)

**Step 5: Run entire test suite to verify no regressions**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: 467+ passed, 0 failed

**Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_cache_headers.py
git commit -m "feat: wire CacheHeaderMiddleware into create_app()"
```

---

### Task 4: Update TODO_NEXT.md and verify

**Files:**
- Modify: `shyfem-ui/TODO_NEXT.md:274-286`

**Step 1: Mark phase 29.1 complete, 29.2 and 29.3 as skipped**

Update TODO_NEXT.md Phase 29 section:

```markdown
## Phase 29: Frontend Bundle Optimization

> Static assets have no cache headers. Lazy tabs and Plotly precision
> optimization are low ROI for the current scale.

- [x] **29.1** Add static asset cache headers — 17 tests
  - `CacheHeaderMiddleware` adds `Cache-Control: public, max-age=N` for
    `.css`, `.js`, `.woff2`, `.woff`, `.ttf`, `.png`, `.svg`, `.ico`
  - `static_cache_max_age` config (default 86400, env `SHYFEM_UI_STATIC_CACHE_MAX_AGE`)
  - max_age=0 disables header injection

- [x] **29.2** ~~Add lazy tab content rendering~~ — SKIPPED
  - Shiny is server-rendered, not SPA. Invasive refactor of all 9 page modules. Low ROI.

- [x] **29.3** ~~Optimize Plotly figure serialization~~ — SKIPPED
  - Micro-optimization. Negligible benefit for current mesh sizes.
```

**Step 2: Commit**

```bash
git add shyfem-ui/TODO_NEXT.md
git commit -m "docs: mark Phase 29 complete in TODO_NEXT.md"
```
