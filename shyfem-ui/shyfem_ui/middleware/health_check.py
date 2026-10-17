"""ASGI middleware for the /health JSON endpoint."""

import asyncio
import json
import time

# Seconds /health waits for a job queue's async probe (Celery: a Redis scan)
# before reporting the queue as failed. The probe runs off the event loop;
# this bounds the response, never the loop.
QUEUE_PROBE_TIMEOUT_S = 3.0


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
            # A queue whose count needs I/O (CeleryJobQueue: Redis) offers an
            # async probe; the in-memory LocalJobQueue count stays a plain
            # attribute read on the loop thread, the only thread allowed to
            # iterate its job dict.
            probe = getattr(self._job_queue, "active_job_count_async", None)
            if probe is not None:
                active_jobs = await asyncio.wait_for(probe(), timeout=QUEUE_PROBE_TIMEOUT_S)
            else:
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
        # 503 when degraded so load balancers / monitoring detect a failed
        # dependency (a 200 with status:"degraded" reads as healthy to them).
        http_status = 200 if status == "ok" else 503
        result = send(
            {
                "type": "http.response.start",
                "status": http_status,
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
