"""Tests for RequestIdMiddleware."""

import logging
import uuid

from shyfem_ui.middleware.request_id import (
    RequestIdFilter,
    RequestIdMiddleware,
    request_id_var,
)


def _http_scope(headers=None) -> dict:
    return {
        "type": "http",
        "path": "/test",
        "method": "GET",
        "client": ("127.0.0.1", 9999),
        "headers": headers or [],
    }


def _ws_scope() -> dict:
    return {"type": "websocket", "path": "/ws", "client": ("127.0.0.1", 9999), "headers": []}


async def _noop_receive():
    return {}


async def _echo_app(scope, receive, send):
    body = b"OK"
    result = send({"type": "http.response.start", "status": 200, "headers": []})
    if result is not None:
        await result
    result = send({"type": "http.response.body", "body": body})
    if result is not None:
        await result


class TestRequestIdMiddleware:

    async def test_generates_uuid(self):
        mw = RequestIdMiddleware(_echo_app)
        sent = []
        await mw(_http_scope(), _noop_receive, sent.append)
        headers = dict(sent[0]["headers"])
        req_id = headers[b"x-request-id"].decode()
        # Verify it's a valid UUID
        uuid.UUID(req_id)

    async def test_propagates_incoming_header(self):
        incoming_id = "my-custom-request-id-123"
        headers = [[b"x-request-id", incoming_id.encode()]]
        mw = RequestIdMiddleware(_echo_app)
        sent = []
        await mw(_http_scope(headers=headers), _noop_receive, sent.append)
        resp_headers = dict(sent[0]["headers"])
        assert resp_headers[b"x-request-id"].decode() == incoming_id

    async def test_sets_context_var(self):
        captured_id = None

        async def capturing_app(scope, receive, send):
            nonlocal captured_id
            captured_id = request_id_var.get()
            await _echo_app(scope, receive, send)

        mw = RequestIdMiddleware(capturing_app)
        sent = []
        await mw(_http_scope(), _noop_receive, sent.append)
        assert captured_id is not None
        uuid.UUID(captured_id)

    async def test_resets_context_var_after_request(self):
        mw = RequestIdMiddleware(_echo_app)
        sent = []
        await mw(_http_scope(), _noop_receive, sent.append)
        assert request_id_var.get() is None

    async def test_websocket_passthrough(self):
        call_count = 0

        async def ws_app(scope, receive, send):
            nonlocal call_count
            call_count += 1

        mw = RequestIdMiddleware(ws_app)
        await mw(_ws_scope(), _noop_receive, lambda msg: None)
        assert call_count == 1


class TestRequestIdFilter:

    def test_filter_with_id(self):
        token = request_id_var.set("test-id-abc")
        try:
            f = RequestIdFilter()
            record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
            f.filter(record)
            assert record.request_id == "test-id-abc"
        finally:
            request_id_var.reset(token)

    def test_filter_without_id(self):
        f = RequestIdFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f.filter(record)
        assert record.request_id == "-"


class TestRequestIdSanitizing:
    """SEC-07: a client-supplied X-Request-Id is echoed in the response and
    written into every log line, so only a short, plain token is accepted.
    Anything else is replaced by a fresh UUID."""

    async def _run(self, incoming: bytes):
        seen = {}

        async def capturing_app(scope, receive, send):
            seen["ctx"] = request_id_var.get()
            await _echo_app(scope, receive, send)

        mw = RequestIdMiddleware(capturing_app)
        sent = []
        await mw(_http_scope(headers=[[b"x-request-id", incoming]]), _noop_receive, sent.append)
        echoed = dict(sent[0]["headers"])[b"x-request-id"].decode("latin-1")
        return echoed, seen["ctx"]

    async def test_overlong_id_replaced(self):
        incoming = b"a" * 10_000
        echoed, ctx = await self._run(incoming)
        assert echoed != incoming.decode()
        uuid.UUID(echoed)
        assert ctx == echoed

    async def test_128_char_id_still_accepted(self):
        incoming = b"b" * 128
        echoed, ctx = await self._run(incoming)
        assert echoed == ctx == incoming.decode()

    async def test_129_char_id_replaced(self):
        echoed, _ = await self._run(b"b" * 129)
        uuid.UUID(echoed)

    async def test_control_characters_replaced(self):
        echoed, ctx = await self._run(b"abc\r\nX-Injected: 1")
        assert "\n" not in echoed and "\r" not in echoed
        uuid.UUID(echoed)
        uuid.UUID(ctx)

    async def test_log_forging_characters_replaced(self):
        echoed, ctx = await self._run("id] ERROR: forged \xe9".encode("latin-1"))
        uuid.UUID(echoed)
        uuid.UUID(ctx)

    async def test_nginx_style_hex_id_kept(self):
        incoming = b"0f1e2d3c4b5a69788796a5b4c3d2e1f0"
        echoed, ctx = await self._run(incoming)
        assert echoed == ctx == incoming.decode()
