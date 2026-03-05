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


from shyfem_ui.middleware.cache_headers import CacheHeaderMiddleware
from shyfem_ui.app import create_app


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


async def _call_send(send, message):
    """Call send, awaiting only if it returns a coroutine."""
    result = send(message)
    if result is not None:
        await result


async def _mock_app(scope, receive, send):
    """Tiny ASGI app that returns 200 with a text/plain body."""
    body = b"OK"
    await _call_send(send, {
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"text/plain"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await _call_send(send, {"type": "http.response.body", "body": body})


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


class TestCacheHeaderIntegration:
    """Integration: middleware is wired into create_app()."""

    def test_create_app_wraps_with_cache_middleware(self):
        config = Config(shyfem_dir="/tmp/fake", static_cache_max_age=7200)
        app = create_app(config)
        # Walk the .app chain to find CacheHeaderMiddleware
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
