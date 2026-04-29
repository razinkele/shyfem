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


def _make_scope(method="GET", path="/", cookies=None, root_path=""):
    """Build an ASGI HTTP scope dict."""
    headers = []
    if cookies:
        headers.append((b"cookie", cookies.encode("utf-8")))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
    }
    if root_path:
        scope["root_path"] = root_path
    return scope


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
    async def test_get_login_includes_csrf_token(self):
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(method="GET", path="/login")
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        start_msg = send.call_args_list[0][0][0]
        # Check CSRF cookie is set
        headers_list = start_msg["headers"]
        csrf_cookie = None
        for name, value in headers_list:
            if name == b"set-cookie" and b"csrf_token=" in value:
                csrf_cookie = value.decode()
                break
        assert csrf_cookie is not None, "Login page should set a csrf_token cookie"
        assert "SameSite=Lax" in csrf_cookie

        # Check hidden input in HTML body
        body_msg = send.call_args_list[1][0][0]
        html = body_msg["body"].decode()
        assert 'name="csrf_token"' in html

    @pytest.mark.asyncio
    async def test_post_login_valid_creds_redirects(self):
        user = {"id": 5, "username": "bob", "role": "user", "is_active": True}
        auth_service = MagicMock()
        auth_service.authenticate.return_value = user
        auth_service.create_session.return_value = "new-session-token"

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service, session_ttl_hours=8)

        csrf = "test-csrf-token"
        body = f"username=bob&password=s3cret&csrf_token={csrf}".encode()
        receive = AsyncMock(return_value={
            "type": "http.request",
            "body": body,
        })
        scope = _make_scope(method="POST", path="/login", cookies=f"csrf_token={csrf}")
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

        csrf = "test-csrf-token"
        body = f"username=bob&password=wrong&csrf_token={csrf}".encode()
        receive = AsyncMock(return_value={
            "type": "http.request",
            "body": body,
        })
        scope = _make_scope(method="POST", path="/login", cookies=f"csrf_token={csrf}")
        send = AsyncMock()
        await mw(scope, receive, send)

        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 200

        body_msg = send.call_args_list[1][0][0]
        assert b"Invalid" in body_msg["body"]

    @pytest.mark.asyncio
    async def test_post_login_csrf_mismatch_shows_error(self):
        auth_service = MagicMock()
        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        body = b"username=bob&password=s3cret&csrf_token=form-token"
        receive = AsyncMock(return_value={
            "type": "http.request",
            "body": body,
        })
        scope = _make_scope(method="POST", path="/login", cookies="csrf_token=different-token")
        send = AsyncMock()
        await mw(scope, receive, send)

        # Should NOT authenticate
        auth_service.authenticate.assert_not_called()
        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 200
        body_msg = send.call_args_list[1][0][0]
        assert b"Invalid request" in body_msg["body"]

    @pytest.mark.asyncio
    async def test_post_login_missing_csrf_shows_error(self):
        auth_service = MagicMock()
        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        body = b"username=bob&password=s3cret"
        receive = AsyncMock(return_value={
            "type": "http.request",
            "body": body,
        })
        scope = _make_scope(method="POST", path="/login")
        send = AsyncMock()
        await mw(scope, receive, send)

        auth_service.authenticate.assert_not_called()
        start_msg = send.call_args_list[0][0][0]
        assert start_msg["status"] == 200
        body_msg = send.call_args_list[1][0][0]
        assert b"Invalid request" in body_msg["body"]

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

    @pytest.mark.asyncio
    async def test_csrf_cookie_has_httponly(self):
        auth_service = MagicMock()
        auth_service.authenticate.return_value = None
        mw = SessionAuthMiddleware(AsyncMock(), auth_service)
        sent = []
        async def send(msg):
            sent.append(msg)
        await mw._serve_login_page(send, error="", root_path="")
        set_cookie_headers = [
            v.decode() for msg in sent if msg.get("type") == "http.response.start"
            for k, v in msg["headers"] if k == b"set-cookie"
        ]
        csrf_cookies = [h for h in set_cookie_headers if h.startswith("csrf_token=")]
        assert csrf_cookies, "Expected csrf_token Set-Cookie header"
        assert "HttpOnly" in csrf_cookies[0], (
            f"CSRF cookie missing HttpOnly: {csrf_cookies[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_csrf_cookie_secure_when_use_secure_cookies(self):
        auth_service = MagicMock()
        auth_service.authenticate.return_value = None
        mw = SessionAuthMiddleware(AsyncMock(), auth_service, use_secure_cookies=True)
        sent = []
        async def send(msg):
            sent.append(msg)
        await mw._serve_login_page(send, error="", root_path="")
        set_cookie_headers = [
            v.decode() for msg in sent if msg.get("type") == "http.response.start"
            for k, v in msg["headers"] if k == b"set-cookie"
        ]
        csrf_cookies = [h for h in set_cookie_headers if h.startswith("csrf_token=")]
        assert csrf_cookies
        assert "Secure" in csrf_cookies[0], (
            f"CSRF cookie missing Secure when use_secure_cookies=True: {csrf_cookies[0]!r}"
        )


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


# ------------------------------------------------------------------
# Reverse proxy root_path support
# ------------------------------------------------------------------


class TestMiddlewareRootPath:
    """Verify redirects and form actions include the ASGI root_path prefix."""

    ROOT = "/shyfem-ui"

    @pytest.mark.asyncio
    async def test_unauthenticated_redirect_includes_root_path(self):
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(path="/dashboard", root_path=self.ROOT)
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        start_msg = send.call_args_list[0][0][0]
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/shyfem-ui/login"

    @pytest.mark.asyncio
    async def test_login_form_action_includes_root_path(self):
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(method="GET", path="/login", root_path=self.ROOT)
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        body_msg = send.call_args_list[1][0][0]
        html = body_msg["body"].decode("utf-8")
        assert 'action="/shyfem-ui/login"' in html

    @pytest.mark.asyncio
    async def test_post_login_redirects_to_root_path(self):
        user = {"id": 1, "username": "u", "role": "user", "is_active": True}
        auth_service = MagicMock()
        auth_service.authenticate.return_value = user
        auth_service.create_session.return_value = "tok"

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        csrf = "test-csrf-token"
        receive = AsyncMock(return_value={"body": f"username=u&password=p&csrf_token={csrf}".encode()})
        scope = _make_scope(method="POST", path="/login", cookies=f"csrf_token={csrf}", root_path=self.ROOT)
        send = AsyncMock()
        await mw(scope, receive, send)

        start_msg = send.call_args_list[0][0][0]
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/shyfem-ui/"
        cookie = headers[b"set-cookie"].decode()
        assert "Path=/shyfem-ui" in cookie

    @pytest.mark.asyncio
    async def test_logout_redirects_with_root_path(self):
        auth_service = MagicMock()
        auth_service.delete_session.return_value = True

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(
            method="GET", path="/logout",
            cookies="shyfem_session=tok", root_path=self.ROOT,
        )
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        start_msg = send.call_args_list[0][0][0]
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/shyfem-ui/login"
        cookie = headers[b"set-cookie"].decode()
        assert "Path=/shyfem-ui" in cookie

    @pytest.mark.asyncio
    async def test_invalid_session_redirect_includes_root_path(self):
        auth_service = MagicMock()
        auth_service.validate_session.return_value = None

        inner_app = AsyncMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = _make_scope(
            cookies="shyfem_session=bad", root_path=self.ROOT,
        )
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        start_msg = send.call_args_list[0][0][0]
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/shyfem-ui/login"

    @pytest.mark.asyncio
    async def test_constructor_root_path_used_as_fallback(self):
        """When scope has no root_path, the constructor value is used."""
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service, root_path="/shyfem-ui")

        # Scope WITHOUT root_path — simulates Shiny Server
        scope = _make_scope(path="/dashboard")
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        start_msg = send.call_args_list[0][0][0]
        headers = dict(start_msg["headers"])
        assert headers[b"location"] == b"/shyfem-ui/login"

    @pytest.mark.asyncio
    async def test_websocket_allowed_without_cookie_when_behind_proxy(self):
        """Shiny Server's internal WS from localhost — allow through behind proxy."""
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service, root_path="/shyfem-ui")

        scope = {"type": "websocket", "headers": [], "client": ("127.0.0.1", 12345)}
        await mw(scope, AsyncMock(), AsyncMock())

        inner_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_rejected_without_cookie_direct_deploy(self):
        """Without root_path (direct deploy), WS without cookie is rejected."""
        inner_app = AsyncMock()
        auth_service = MagicMock()
        mw = SessionAuthMiddleware(inner_app, auth_service)

        scope = {"type": "websocket", "headers": [], "client": ("127.0.0.1", 12345)}
        send = AsyncMock()
        await mw(scope, AsyncMock(), send)

        inner_app.assert_not_called()
        close_msg = send.call_args_list[0][0][0]
        assert close_msg["code"] == 4001

    @pytest.mark.asyncio
    async def test_websocket_rejected_without_auth_behind_proxy_non_local(self):
        """WS from non-localhost behind proxy must still require auth."""
        app_called = False
        async def dummy_app(scope, receive, send):
            nonlocal app_called
            app_called = True

        auth_service = MagicMock()
        auth_service.validate_session.return_value = None
        middleware = SessionAuthMiddleware(
            dummy_app, auth_service=auth_service, root_path="/shyfem-ui"
        )

        scope = {
            "type": "websocket",
            "path": "/shyfem-ui/ws",
            "headers": [],
            "client": ("1.2.3.4", 12345),
        }
        sent = []
        async def receive(): return {"type": "websocket.connect"}
        async def send(msg): sent.append(msg)

        await middleware(scope, receive, send)
        assert any(m.get("code") == 4001 for m in sent), \
            "Non-localhost unauthenticated WS should be rejected behind proxy"
        assert not app_called

    @pytest.mark.asyncio
    async def test_websocket_allowed_from_localhost_behind_proxy(self):
        """WS from localhost behind proxy is allowed (Shiny Server internal)."""
        app_called = False
        async def dummy_app(scope, receive, send):
            nonlocal app_called
            app_called = True

        auth_service = MagicMock()
        auth_service.validate_session.return_value = None
        middleware = SessionAuthMiddleware(
            dummy_app, auth_service=auth_service, root_path="/shyfem-ui"
        )

        scope = {
            "type": "websocket",
            "path": "/shyfem-ui/ws",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
        sent = []
        async def receive(): return {"type": "websocket.connect"}
        async def send(msg): sent.append(msg)

        await middleware(scope, receive, send)
        assert app_called, "Localhost WS behind proxy should be allowed through"


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
