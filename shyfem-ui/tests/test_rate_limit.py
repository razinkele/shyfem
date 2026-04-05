"""Tests for RateLimitMiddleware ASGI middleware."""

import pytest
from unittest.mock import patch

from shyfem_ui.middleware.rate_limit import RateLimitMiddleware


def _http_scope(client_ip: str = "192.168.1.1", port: int = 12345):
    """Build a minimal HTTP ASGI scope."""
    return {
        "type": "http",
        "client": (client_ip, port),
        "headers": [],
    }


def _ws_scope(client_ip: str = "192.168.1.1", port: int = 12345):
    """Build a minimal WebSocket ASGI scope."""
    return {
        "type": "websocket",
        "client": (client_ip, port),
        "headers": [],
    }


async def _noop_receive():
    """No-op ASGI receive callable."""
    return {}


async def _mock_app(scope, receive, send):
    """Tiny ASGI app that always returns 200 OK."""
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


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    @pytest.mark.asyncio
    async def test_requests_under_limit_pass_through(self):
        """Requests under the rate limit are forwarded to the inner app (200)."""
        mw = RateLimitMiddleware(_mock_app, rpm=5)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        for _ in range(3):
            sent.clear()
            await mw(_http_scope(), _noop_receive, capture_send)

        # Last request should have passed through to the inner app
        assert len(sent) == 2
        assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_requests_at_limit_return_429(self):
        """Once rate limit is reached, middleware returns 429 with Retry-After."""
        mw = RateLimitMiddleware(_mock_app, rpm=3)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        # Make exactly 3 requests to fill the bucket
        for _ in range(3):
            sent.clear()
            await mw(_http_scope(), _noop_receive, capture_send)
            assert sent[0]["status"] == 200

        # 4th request should be rate-limited
        sent.clear()
        await mw(_http_scope(), _noop_receive, capture_send)
        assert sent[0]["status"] == 429

        # Verify Retry-After header is present
        headers = dict(sent[0]["headers"])
        assert headers[b"retry-after"] == b"60"

    @pytest.mark.asyncio
    async def test_sliding_window_resets_after_expiry(self):
        """After the 60-second window elapses, old requests are pruned."""
        mw = RateLimitMiddleware(_mock_app, rpm=2)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        base_time = 1000.0

        with patch("shyfem_ui.middleware.rate_limit.time") as mock_time:
            # Two requests at t=1000
            mock_time.monotonic.return_value = base_time
            for _ in range(2):
                sent.clear()
                await mw(_http_scope(), _noop_receive, capture_send)
                assert sent[0]["status"] == 200

            # 3rd request at t=1000 should be blocked
            sent.clear()
            await mw(_http_scope(), _noop_receive, capture_send)
            assert sent[0]["status"] == 429

            # Advance past the 60-second window
            mock_time.monotonic.return_value = base_time + 61.0

            # Request should now pass through (old timestamps pruned)
            sent.clear()
            await mw(_http_scope(), _noop_receive, capture_send)
            assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_websocket_scopes_bypass_rate_limiting(self):
        """WebSocket scopes are forwarded directly without rate limiting."""
        call_count = 0

        async def ws_app(scope, receive, send):
            nonlocal call_count
            call_count += 1

        mw = RateLimitMiddleware(ws_app, rpm=1)

        # Even with rpm=1, WS connections should never be rate-limited
        for _ in range(5):
            await mw(_ws_scope(), _noop_receive, lambda msg: None)

        assert call_count == 5
        # No HTTP timestamps should have been recorded
        assert len(mw._requests) == 0

    @pytest.mark.asyncio
    async def test_different_client_ips_independent_buckets(self):
        """Each client IP has its own independent rate limit bucket."""
        mw = RateLimitMiddleware(_mock_app, rpm=2)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        # Fill up client A's bucket
        for _ in range(2):
            sent.clear()
            await mw(_http_scope("10.0.0.1"), _noop_receive, capture_send)
            assert sent[0]["status"] == 200

        # Client A is now rate-limited
        sent.clear()
        await mw(_http_scope("10.0.0.1"), _noop_receive, capture_send)
        assert sent[0]["status"] == 429

        # Client B should still be allowed
        sent.clear()
        await mw(_http_scope("10.0.0.2"), _noop_receive, capture_send)
        assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_429_body_contains_rate_limit_message(self):
        """The 429 response body contains a human-readable rate limit message."""
        mw = RateLimitMiddleware(_mock_app, rpm=1)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        # First request passes
        await mw(_http_scope(), _noop_receive, capture_send)
        assert sent[0]["status"] == 200

        # Second request is rate-limited
        sent.clear()
        await mw(_http_scope(), _noop_receive, capture_send)

        assert sent[0]["status"] == 429
        body_msg = sent[1]["body"]
        assert b"Rate limit exceeded" in body_msg

    @pytest.mark.asyncio
    async def test_stale_clients_evicted_when_over_max(self):
        """Stale client entries are pruned when dict exceeds max_clients."""
        mw = RateLimitMiddleware(_mock_app, rpm=5, max_clients=2)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        base_time = 1000.0
        with patch("shyfem_ui.middleware.rate_limit.time") as mock_time:
            # Add 3 clients at t=1000
            mock_time.monotonic.return_value = base_time
            for ip in ["10.0.0.1", "10.0.0.2", "10.0.0.3"]:
                sent.clear()
                await mw(_http_scope(ip), _noop_receive, capture_send)
                assert sent[0]["status"] == 200

            # At t=1000, all 3 are fresh — no eviction yet because pruning checks
            # Move past the window so entries become stale
            mock_time.monotonic.return_value = base_time + 61.0

            # New request triggers pruning
            sent.clear()
            await mw(_http_scope("10.0.0.4"), _noop_receive, capture_send)
            assert sent[0]["status"] == 200

            # Stale entries should be pruned, only fresh client(s) remain
            assert len(mw._requests) <= 2

    @pytest.mark.asyncio
    async def test_evicted_client_can_make_requests_again(self):
        """After eviction, a returning client starts fresh."""
        mw = RateLimitMiddleware(_mock_app, rpm=2, max_clients=1)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        base_time = 1000.0
        with patch("shyfem_ui.middleware.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = base_time
            # Client A makes requests
            for _ in range(2):
                sent.clear()
                await mw(_http_scope("10.0.0.1"), _noop_receive, capture_send)

            # Move past window so A becomes stale
            mock_time.monotonic.return_value = base_time + 61.0

            # Client B triggers eviction of A
            sent.clear()
            await mw(_http_scope("10.0.0.2"), _noop_receive, capture_send)
            assert sent[0]["status"] == 200

            # Client A returns — should get fresh bucket
            sent.clear()
            await mw(_http_scope("10.0.0.1"), _noop_receive, capture_send)
            assert sent[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_active_clients_not_evicted_over_stale(self):
        """When pruning, active clients are kept over stale ones."""
        mw = RateLimitMiddleware(_mock_app, rpm=5, max_clients=2)
        sent = []

        async def capture_send(msg):
            sent.append(msg)

        base_time = 1000.0
        with patch("shyfem_ui.middleware.rate_limit.time") as mock_time:
            # Client A at t=1000
            mock_time.monotonic.return_value = base_time
            await mw(_http_scope("10.0.0.1"), _noop_receive, capture_send)

            # Client B at t=1050 (more recent)
            mock_time.monotonic.return_value = base_time + 50.0
            await mw(_http_scope("10.0.0.2"), _noop_receive, capture_send)

            # Move past window for A but not B
            mock_time.monotonic.return_value = base_time + 61.0

            # Client C — brings count to 3 (A, B, C) after this call
            await mw(_http_scope("10.0.0.3"), _noop_receive, capture_send)

            # Now 3 entries exist; next request triggers pruning
            sent.clear()
            await mw(_http_scope("10.0.0.3"), _noop_receive, capture_send)
            assert sent[0]["status"] == 200

            # A should be evicted (stale), B and C should remain
            assert "10.0.0.1" not in mw._requests
            assert "10.0.0.2" in mw._requests
            assert "10.0.0.3" in mw._requests
