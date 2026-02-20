"""Tests for SessionAuthMiddleware -- cookie auth, login page, WebSocket gating."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from shyfem_ui.middleware.session_auth import (
    SessionAuthMiddleware,
    _LOGIN_HTML,
    _parse_cookie,
    _user_var,
    get_current_user,
)


# ------------------------------------------------------------------
# Cookie parsing
# ------------------------------------------------------------------


class TestParseCookie:

    def test_parse_single_cookie(self):
        result = _parse_cookie(b"shyfem_session=abc123")
        assert result == {"shyfem_session": "abc123"}

    def test_parse_multiple_cookies(self):
        result = _parse_cookie(b"a=1; b=2; shyfem_session=tok99")
        assert result["a"] == "1"
        assert result["b"] == "2"
        assert result["shyfem_session"] == "tok99"

    def test_parse_empty(self):
        result = _parse_cookie(b"")
        assert result == {}

    def test_parse_no_value(self):
        result = _parse_cookie(b"flagonly")
        assert result == {"flagonly": ""}


# ------------------------------------------------------------------
# get_current_user
# ------------------------------------------------------------------


class TestGetCurrentUser:

    def test_returns_none_by_default(self):
        token = _user_var.set(None)
        try:
            assert get_current_user() is None
        finally:
            _user_var.reset(token)

    def test_returns_set_user(self):
        user = {"id": 1, "username": "alice", "role": "admin"}
        token = _user_var.set(user)
        try:
            assert get_current_user() == user
        finally:
            _user_var.reset(token)


# ------------------------------------------------------------------
# Local mode
# ------------------------------------------------------------------


class TestMiddlewareLocalMode:

    @pytest.mark.asyncio
    async def test_local_mode_injects_synthetic_admin(self):
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service, local_mode=True)

        scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        captured_user = None

        async def capture_app(scope, receive, send):
            nonlocal captured_user
            captured_user = get_current_user()

        mw = SessionAuthMiddleware(capture_app, auth_service, local_mode=True)
        await mw(scope, receive, send)

        assert captured_user is not None
        assert captured_user["username"] == "local"
        assert captured_user["role"] == "admin"
        assert captured_user["id"] == 0

    @pytest.mark.asyncio
    async def test_local_mode_passes_through_without_auth(self):
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service, local_mode=True)

        scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner_app.assert_called_once()
        # Auth service should NOT be called in local mode
        auth_service.validate_session.assert_not_called()


# ------------------------------------------------------------------
# HTTP request handling
# ------------------------------------------------------------------


def _make_scope(method="GET", path="/", cookies=None):
    """Build an ASGI HTTP scope dict."""
    headers = []
    if cookies:
        headers.append((b"cookie", cookies.encode("utf-8")))
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
    }


class TestMiddlewareHTTP:

    @pytest.mark.asyncio
    async def test_valid_cookie_passes_through(self):
        user = {"id": 1, "username": "alice", "role": "user", "is_active": True}
        auth_service = MagicMock()
        auth_service.validate_session.return_value = user

        captured_user = None

        async def capture_app(scope, receive, send):
            nonlocal captured_user
            captured_user = get_current_user()

        mw = SessionAuthMiddleware(capture_app, auth_service)
        scope = _make_scope(cookies="shyfem_session=valid-token")
        await mw(scope, AsyncMock(), AsyncMock())

        auth_service.validate_session.assert_called_once_with("valid-token")
        assert captured_user is not None
        assert captured_user["username"] == "alice"

    @pytest.mark.asyncio
    async def test_no_cookie_redirects_to_login(self):
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(path="/dashboard")
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        # Inner app should NOT be called
        inner_app.assert_not_called()
        # Should send a 302 redirect
        start_msg = send.call_args_list[0][0][0]
        assert start_msg["type"] == "http.response.start"
        assert start_msg["status"] == 302
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/login"

    @pytest.mark.asyncio
    async def test_get_login_serves_html(self):
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(method="GET", path="/login")
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 200
        headers = dict(start_msg["headers"])
        assert b"text/html" in headers[b"content-type"]

        body_msg = send.call_args_list[1][0][0]
        assert body_msg["type"] == "http.response.body"
        assert b"SHYFEM" in body_msg["body"]

    @pytest.mark.asyncio
    async def test_post_login_valid_creds_redirects(self):
        user = {"id": 5, "username": "bob", "role": "user", "is_active": True}
        auth_service = MagicMock()
        auth_service.authenticate.return_value = user
        auth_service.create_session.return_value = "new-session-token"

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service, session_ttl_hours=8)

        body = b"username=bob&password=s3cret"
        receive = AsyncMock(return_value={
            "type": "http.request",
            "body": body,
        })
        scope = _make_scope(method="POST", path="/login")
        send = AsyncMock()
        await mw(scope, receive, send)

        auth_service.authenticate.assert_called_once_with("bob", "s3cret")
        auth_service.create_session.assert_called_once_with(5, ttl_hours=8)

        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 302
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/"
        cookie_header = headers[b"set-cookie"].decode()
        assert "shyfem_session=new-session-token" in cookie_header
        assert "HttpOnly" in cookie_header
        assert "SameSite=Lax" in cookie_header

    @pytest.mark.asyncio
    async def test_post_login_invalid_creds_shows_error(self):
        auth_service = MagicMock()
        auth_service.authenticate.return_value = None

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        body = b"username=bob&password=wrong"
        receive = AsyncMock(return_value={
            "type": "http.request",
            "body": body,
        })
        scope = _make_scope(method="POST", path="/login")
        send = AsyncMock()
        await mw(scope, receive, send)

        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 200

        body_msg = send.call_args_list[1][0][0]
        assert b"Invalid" in body_msg["body"]

    @pytest.mark.asyncio
    async def test_get_logout_clears_cookie_and_redirects(self):
        auth_service = MagicMock()
        auth_service.delete_session.return_value = True

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(method="GET", path="/logout", cookies="shyfem_session=tok123")
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        auth_service.delete_session.assert_called_once_with("tok123")

        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 302
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/login"
        cookie_header = headers[b"set-cookie"].decode()
        assert "Max-Age=0" in cookie_header

    @pytest.mark.asyncio
    async def test_invalid_session_redirects_to_login(self):
        auth_service = MagicMock()
        auth_service.validate_session.return_value = None

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(cookies="shyfem_session=expired-token")
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        inner_app.assert_not_called()
        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 302
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/login"


# ------------------------------------------------------------------
# WebSocket handling
# ------------------------------------------------------------------


class TestMiddlewareWebSocket:

    @pytest.mark.asyncio
    async def test_valid_cookie_passes_through(self):
        user = {"id": 1, "username": "alice", "role": "user", "is_active": True}
        auth_service = MagicMock()
        auth_service.validate_session.return_value = user

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = {
            "type": "websocket",
            "headers": [(b"cookie", b"shyfem_session=ws-token")],
        }
        receive = AsyncMock()
        send = AsyncMock()
        await mw(scope, receive, send)

        inner_app.assert_called_once()
        auth_service.validate_session.assert_called_once_with("ws-token")

    @pytest.mark.asyncio
    async def test_no_cookie_closes_with_4001(self):
        auth_service = MagicMock()
        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = {
            "type": "websocket",
            "headers": [],
        }
        receive = AsyncMock()
        send = AsyncMock()
        await mw(scope, receive, send)

        inner_app.assert_not_called()
        # Should send websocket.close with code 4001
        send.assert_called()
        close_msg = send.call_args_list[0][0][0]
        assert close_msg["type"] == "websocket.close"
        assert close_msg["code"] == 4001

    @pytest.mark.asyncio
    async def test_invalid_session_closes_with_4001(self):
        auth_service = MagicMock()
        auth_service.validate_session.return_value = None

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = {
            "type": "websocket",
            "headers": [(b"cookie", b"shyfem_session=bad-token")],
        }
        receive = AsyncMock()
        send = AsyncMock()
        await mw(scope, receive, send)

        inner_app.assert_not_called()
        close_msg = send.call_args_list[0][0][0]
        assert close_msg["type"] == "websocket.close"
        assert close_msg["code"] == 4001
