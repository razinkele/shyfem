"""ASGI middleware for the /health JSON endpoint."""

import json
import time


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

        if scope.get("path") != "/health" or scope["method"] != "GET":
            return await self.app(scope, receive, send)

        from shyfem_ui import __version__

        # Probe database
        db_ok = True
        db_response_time_ms = -1.0
        try:
            if self._db_check:
                result = self._db_check()
                if isinstance(result, (int, float)):
                    db_response_time_ms = result
        except Exception:
            db_ok = False

        # Probe job queue (active_jobs and queue_depth are the same value)
        active_jobs = -1
        queue_ok = True
        try:
            val = getattr(self._job_queue, "active_job_count", -1)
            active_jobs = val() if callable(val) else val
        except Exception:
            active_jobs = -1
            queue_ok = False
        queue_depth = active_jobs

        worker_count = -1
        try:
            wc = getattr(self._job_queue, "max_workers", -1)
            worker_count = wc() if callable(wc) else wc
        except Exception:
            worker_count = -1

        status = "ok" if db_ok and queue_ok else "degraded"

        payload = {
            "status": status,
            "version": __version__,
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "database": "ok" if db_ok else "error",
            "db_response_time_ms": db_response_time_ms,
            "active_jobs": active_jobs,
            "queue_depth": queue_depth,
            "worker_count": worker_count,
        }

        body = json.dumps(payload).encode()
        result = send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        if result is not None:
            await result
        result = send({"type": "http.response.body", "body": body})
        if result is not None:
            await result
