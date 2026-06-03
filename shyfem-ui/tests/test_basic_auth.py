"""Tests for BasicAuthMiddleware ASGI middleware."""

import base64

import pytest

from shyfem_ui.middleware.basic_auth import BasicAuthMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_send():
    """Return an async send callable that collects messages into a list."""
    sent = []

    async def send(message):
        sent.append(message)

    return sent, send


async def _mock_app(scope, receive, send):
    """Tiny ASGI app that always returns 200 OK for HTTP, accept for WS."""
    if scope["type"] == "websocket":
        await send({"type": "websocket.accept"})
        return
    if scope["type"] not in ("http",):
        # For non-http/ws scopes (e.g. lifespan), just return silently.
        return
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


async def _noop_receive():
    """No-op ASGI receive callable."""
    return {}


def _basic_header(username: str, password: str) -> bytes:
    """Build a base64-encoded Basic auth header value."""
    raw = f"{username}:{password}".encode()
    return b"Basic " + base64.b64encode(raw)


def _http_scope(auth_header: bytes | None = None) -> dict:
    """Build a minimal HTTP ASGI scope, optionally with an Authorization header."""
    headers = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header))
    return {"type": "http", "headers": headers}


def _ws_scope(auth_header: bytes | None = None) -> dict:
    """Build a minimal WebSocket ASGI scope."""
    headers = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header))
    return {"type": "websocket", "headers": headers}


USERNAME = "admin"
PASSWORD = "s3cret"


@pytest.fixture()
def middleware():
    """Return a BasicAuthMiddleware wrapping the mock app."""
    return BasicAuthMiddleware(_mock_app, USERNAME, PASSWORD)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasicAuthMiddleware:
    """Tests for BasicAuthMiddleware."""

    @pytest.mark.asyncio
    async def test_valid_credentials_pass_through(self, middleware):
        """Valid credentials pass through to inner app and get 200."""
        sent, send = _make_send()
        scope = _http_scope(_basic_header(USERNAME, PASSWORD))
        await middleware(scope, _noop_receive, send)

        assert any(msg.get("status") == 200 for msg in sent)

    @pytest.mark.asyncio
    async def test_invalid_password_returns_401(self, middleware):
        """Wrong password returns 401."""
        sent, send = _make_send()
        scope = _http_scope(_basic_header(USERNAME, "wrong"))
        await middleware(scope, _noop_receive, send)

        assert any(msg.get("status") == 401 for msg in sent)

    @pytest.mark.asyncio
    async def test_invalid_username_returns_401(self, middleware):
        """Wrong username returns 401."""
        sent, send = _make_send()
        scope = _http_scope(_basic_header("nobody", PASSWORD))
        await middleware(scope, _noop_receive, send)

        assert any(msg.get("status") == 401 for msg in sent)

    @pytest.mark.asyncio
    async def test_missing_auth_header_returns_401_with_realm(self, middleware):
        """Missing Authorization header returns 401 with WWW-Authenticate realm."""
        sent, send = _make_send()
        scope = _http_scope()  # no auth header
        await middleware(scope, _noop_receive, send)

        start = next(msg for msg in sent if msg.get("status") == 401)
        header_dict = dict(start["headers"])
        www_auth = header_dict[b"www-authenticate"].decode()
        assert "SHYFEM Workbench" in www_auth

    @pytest.mark.asyncio
    async def test_malformed_base64_returns_401(self, middleware):
        """Malformed base64 in Authorization header returns 401."""
        sent, send = _make_send()
        scope = _http_scope(b"Basic %%%notbase64%%%")
        await middleware(scope, _noop_receive, send)

        assert any(msg.get("status") == 401 for msg in sent)

    @pytest.mark.asyncio
    async def test_non_basic_scheme_returns_401(self, middleware):
        """Non-Basic auth scheme (e.g. Bearer) returns 401."""
        sent, send = _make_send()
        scope = _http_scope(b"Bearer some-token")
        await middleware(scope, _noop_receive, send)

        assert any(msg.get("status") == 401 for msg in sent)

    @pytest.mark.asyncio
    async def test_websocket_bad_auth_sends_close_4001(self, middleware):
        """WebSocket with bad/no auth sends close code 4001."""
        sent, send = _make_send()
        scope = _ws_scope()  # no auth
        await middleware(scope, _noop_receive, send)

        close_msg = next(
            msg for msg in sent if msg.get("type") == "websocket.close"
        )
        assert close_msg["code"] == 4001

    @pytest.mark.asyncio
    async def test_websocket_valid_auth_passes_through(self, middleware):
        """WebSocket with valid auth passes through to inner app."""
        sent, send = _make_send()
        scope = _ws_scope(_basic_header(USERNAME, PASSWORD))
        await middleware(scope, _noop_receive, send)

        assert any(msg.get("type") == "websocket.accept" for msg in sent)

    @pytest.mark.asyncio
    async def test_lifespan_scope_passes_through_without_auth(self, middleware):
        """Non-http/websocket scopes (e.g. 'lifespan') pass through without auth."""
        sent, send = _make_send()
        scope = {"type": "lifespan", "headers": []}
        await middleware(scope, _noop_receive, send)

        # The mock app returns silently for lifespan; key is no 401.
        assert not any(msg.get("status") == 401 for msg in sent)

    @pytest.mark.asyncio
    async def test_password_with_colon_handled_correctly(self):
        """Password containing a colon is handled correctly (split on first colon)."""
        colon_password = "pass:word:extra"
        mw = BasicAuthMiddleware(_mock_app, USERNAME, colon_password)

        sent, send = _make_send()
        scope = _http_scope(_basic_header(USERNAME, colon_password))
        await mw(scope, _noop_receive, send)

        assert any(msg.get("status") == 200 for msg in sent)
