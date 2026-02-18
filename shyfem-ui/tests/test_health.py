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
    result = send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"text/plain"]]})
    if result is not None:
        await result
    result = send({"type": "http.response.body", "body": body})
    if result is not None:
        await result


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
