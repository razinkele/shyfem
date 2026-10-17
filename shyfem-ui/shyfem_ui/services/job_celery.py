"""Celery/Redis job queue implementation for server mode.

This module provides a distributed job queue using Celery and Redis,
suitable for multi-user server deployments.

Requirements:
    pip install celery redis

Start workers with:
    celery -A shyfem_ui.services.job_celery worker --loglevel=info -n worker1@%h

Give each worker on a host a distinct node name (``-n``). The lost-job
reconcile (``CeleryJobQueue.reconcile_phantom_jobs``) asks each worker for
its running tasks, so it needs a pool whose main process answers control
commands while a task runs: prefork (the default), threads or gevent, not
``solo``. A busy solo worker is silent, and workers sharing a name are
indistinguishable, so their jobs are simply left alone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from shyfem_ui.config import get_config
from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobSpec, JobStatus

# The optional session_factory / notification_service a CeleryJobQueue was
# built with. Only a process that builds a queue (the web process, tests) sets
# them: a real Celery worker never does, so the worker-side helpers below fall
# back to what the worker's own config provides (_persist_job_to_db: the
# app-wide db_session; _send_completion_notification: _worker_notifier).
_queue_session_factory: Callable | None = None
_queue_notification_service: Any | None = None
# The job-email service a worker process builds from its own config, once.
_worker_notifier: Any | None = None

logger = logging.getLogger(__name__)

try:  # redis is optional (server mode only); the reconcile's CAS needs its WatchError
    from redis.exceptions import WatchError as _WatchError
except ImportError:  # pragma: no cover - exercised only without redis installed

    class _WatchError(Exception):
        """Stand-in so ``except _WatchError`` is valid without redis."""


# error_message of a RUNNING job its worker lost (killed, OOM, host reboot):
# the task's ``finally`` never ran, so the reconcile pass writes this instead.
CELERY_LOST_ERROR = "lost: its Celery worker stopped while the job ran"

# Seconds a reconcile pass waits for workers to answer the ``active`` query.
INSPECT_TIMEOUT_S = 5.0

# Web-side Redis client timeouts (s): connecting, and any single command.
REDIS_CONNECT_TIMEOUT_S = 5.0
REDIS_SOCKET_TIMEOUT_S = 10.0

# Seconds an active-job count is reused by /health probes.
ACTIVE_COUNT_CACHE_S = 2.0

_ACTIVE_STATUS_VALUES = frozenset(
    s.value for s in (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)
)

# Module-level Celery app (created lazily, shared across imports)
_celery_app = None


def get_celery_app(redis_url: str = "redis://localhost:6379/0") -> Any:
    """Get or create the module-level Celery application."""
    global _celery_app
    if _celery_app is None:
        try:
            from celery import Celery
        except ImportError as exc:
            raise ImportError(
                "Celery is required for server mode. Install with: pip install celery redis"
            ) from exc

        _celery_app = Celery(
            "shyfem_ui",
            broker=redis_url,
            backend=redis_url,
        )
        _celery_app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            result_extended=True,
        )
    return _celery_app


def _get_redis_client(redis_url: str = "redis://localhost:6379/0", *, bounded: bool = False) -> Any:
    """Create a Redis client.

    ``bounded`` (the web side) adds connect and per-command timeouts, so a
    blackholed or stalled Redis fails a call instead of parking a thread of
    the shared to_thread pool. A worker's client stays unbounded: it rides
    out a Redis stall rather than lose a job's terminal write (a timeout in
    the task's ``finally`` would skip the SQL row and the email, and the
    reconcile would later call a finished job lost) or fail a running job
    over one slow progress write.
    """
    try:
        import redis
    except ImportError as exc:
        raise ImportError(
            "Redis is required for server mode. Install with: pip install redis"
        ) from exc
    if not bounded:
        return redis.from_url(redis_url)
    return redis.from_url(
        redis_url,
        socket_connect_timeout=REDIS_CONNECT_TIMEOUT_S,
        socket_timeout=REDIS_SOCKET_TIMEOUT_S,
    )


def _store_job_info(redis_client, job_info: JobInfo) -> None:
    """Store job info in Redis."""
    data = {
        "id": job_info.id,
        "name": job_info.name,
        "tool_name": job_info.tool_name,
        "args": job_info.args,
        "working_dir": job_info.working_dir,
        "status": job_info.status.value,
        "progress": job_info.progress,
        "progress_message": job_info.progress_message,
        "created_at": job_info.created_at.isoformat() if job_info.created_at else None,
        "queued_at": job_info.queued_at.isoformat() if job_info.queued_at else None,
        "started_at": job_info.started_at.isoformat() if job_info.started_at else None,
        "completed_at": job_info.completed_at.isoformat() if job_info.completed_at else None,
        "return_code": job_info.return_code,
        "error_message": job_info.error_message,
        "stdout_file": job_info.stdout_file,
        "stderr_file": job_info.stderr_file,
        "output_files": job_info.output_files,
        "simulation_id": job_info.simulation_id,
        "metadata": job_info.metadata,
    }

    redis_client.hset("shyfem:jobs", job_info.id, json.dumps(data))
    redis_client.zadd(
        "shyfem:jobs:by_time",
        {job_info.id: job_info.created_at.timestamp()},
    )


def _load_job_info(redis_client, job_id: str) -> JobInfo | None:
    """Load job info from Redis."""
    data = redis_client.hget("shyfem:jobs", job_id)
    if not data:
        return None

    d = json.loads(data)

    return JobInfo(
        id=d["id"],
        name=d["name"],
        tool_name=d["tool_name"],
        args=d["args"],
        working_dir=d["working_dir"],
        status=JobStatus(d["status"]),
        progress=d.get("progress", 0.0),
        progress_message=d.get("progress_message", ""),
        created_at=(
            datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now()
        ),
        queued_at=datetime.fromisoformat(d["queued_at"]) if d.get("queued_at") else None,
        started_at=datetime.fromisoformat(d["started_at"]) if d.get("started_at") else None,
        completed_at=datetime.fromisoformat(d["completed_at"]) if d.get("completed_at") else None,
        return_code=d.get("return_code"),
        error_message=d.get("error_message"),
        stdout_file=d.get("stdout_file"),
        stderr_file=d.get("stderr_file"),
        output_files=d.get("output_files", []),
        simulation_id=d.get("simulation_id"),
        metadata=d.get("metadata", {}),
    )


# ---------------------------------------------------------------------------
# Celery task: runs synchronously in a worker process
# ---------------------------------------------------------------------------


def execute_shyfem_job(
    job_id: str, redis_url: str, shyfem_dir: str, hostname: str | None = None
) -> None:
    """Execute a SHYFEM job (called by Celery worker).

    This runs synchronously using asyncio.run() since Celery workers
    are separate processes with their own event loops. ``hostname`` is the
    worker's node name, recorded on the job so the reconcile pass can ask
    that worker whether it still runs it.
    """
    import asyncio

    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

    rc = _get_redis_client(redis_url)
    job_info = _load_job_info(rc, job_id)
    if not job_info:
        return

    # Mark as running
    if hostname:
        job_info.metadata["celery_worker"] = hostname
    job_info.status = JobStatus.RUNNING
    job_info.started_at = datetime.now()
    _store_job_info(rc, job_info)

    wrapper = ShyfemWrapper(shyfem_dir)
    working_dir = Path(job_info.working_dir)
    working_dir.mkdir(parents=True, exist_ok=True)

    # Setup output files
    job_info.stdout_file = str(working_dir / f"{job_id}.stdout")
    job_info.stderr_file = str(working_dir / f"{job_id}.stderr")
    _store_job_info(rc, job_info)

    def progress_callback(progress: float, message: str):
        job_info.progress = progress
        job_info.progress_message = message
        _store_job_info(rc, job_info)

    try:
        mpi_enabled = job_info.metadata.get("mpi_enabled", False)
        mpi_np = job_info.metadata.get("mpi_np", 1)
        solver = job_info.metadata.get("solver", "sparskit")

        if job_info.tool_name == "shyfem" and mpi_enabled and mpi_np > 1:
            result = asyncio.run(
                wrapper.run_shyfem(
                    job_info.args[-1] if job_info.args else "",
                    working_dir,
                    mpi_enabled=True,
                    mpi_np=mpi_np,
                    mpirun_path=get_config().mpirun_path,
                    options=job_info.args[:-1] if len(job_info.args) > 1 else None,
                    solver=solver,
                    progress_callback=progress_callback,
                )
            )
        elif job_info.tool_name == "shyfem":
            result = asyncio.run(
                wrapper.run_shyfem(
                    job_info.args[-1] if job_info.args else "",
                    working_dir,
                    solver=solver,
                    progress_callback=progress_callback,
                )
            )
        else:
            result = asyncio.run(
                wrapper.run_command(
                    job_info.tool_name,
                    job_info.args,
                    working_dir,
                    progress_callback=progress_callback,
                )
            )

        job_info.return_code = result.return_code
        job_info.output_files = result.output_files
        job_info.progress = 1.0

        if result.success:
            job_info.status = JobStatus.COMPLETED
        else:
            job_info.status = JobStatus.FAILED
            job_info.error_message = result.stderr[:1000] if result.stderr else "Unknown error"

        # Write output files
        if job_info.stdout_file:
            Path(job_info.stdout_file).write_text(result.stdout)
        if job_info.stderr_file:
            Path(job_info.stderr_file).write_text(result.stderr)

    except Exception as e:
        job_info.status = JobStatus.FAILED
        job_info.error_message = str(e)
    finally:
        job_info.completed_at = datetime.now()
        _store_job_info(rc, job_info)
        # Persist terminal state to DB if a session_factory is available
        _persist_job_to_db(job_info)
        # Send completion notification if a notification_service is available
        _send_completion_notification(job_info)


# ---------------------------------------------------------------------------
# DB persistence + notification helpers (worker-side, module-level)
# ---------------------------------------------------------------------------


def _persist_job_to_db(
    job_info: JobInfo,
    session_factory: Callable[[], Any] | None = None,
) -> None:
    """Write or update a job row in the database.

    If ``session_factory`` is provided it is used directly.  Otherwise
    falls back to the module-level ``_queue_session_factory`` (set by the
    most recent ``CeleryJobQueue`` construction), and finally to the
    app-wide ``db_session`` context manager if neither is available.
    """
    factory = session_factory or _queue_session_factory
    try:
        from shyfem_ui.models.project import Job

        if factory is not None:
            ctx = factory()
        else:
            try:
                from shyfem_ui.db.base import db_session

                ctx = db_session()
            except Exception:
                # No factory injected and the app-wide db_session() can't be
                # constructed (e.g. DATABASE_URL misconfigured). Log so the
                # operator can diagnose; persistence is skipped for this job.
                logger.warning(
                    "Cannot persist job %s: no session_factory and " "db_session() failed",
                    job_info.id,
                    exc_info=True,
                )
                return

        with ctx as db:
            row = db.query(Job).filter(Job.job_uuid == job_info.id).first()
            if row is None:
                row = Job(
                    job_uuid=job_info.id,
                    name=job_info.name,
                    job_type=job_info.tool_name,
                    command=" ".join(job_info.args),
                    working_dir=job_info.working_dir,
                    simulation_id=job_info.simulation_id,
                    session_id=job_info.metadata.get("session_id"),
                    user_id=job_info.metadata.get("user_id"),
                    project_id=job_info.metadata.get("project_id"),
                )
                db.add(row)

            row.status = job_info.status
            row.celery_task_id = job_info.metadata.get("celery_task_id")
            row.progress = job_info.progress
            row.progress_message = job_info.progress_message
            row.queued_at = job_info.queued_at
            row.started_at = job_info.started_at
            row.completed_at = job_info.completed_at
            row.return_code = job_info.return_code
            row.error_message = job_info.error_message
            row.stdout_file = job_info.stdout_file
            row.stderr_file = job_info.stderr_file
    except Exception:
        logger.error("Could not persist job %s to DB", job_info.id, exc_info=True)


def _redacted_db_url(url: str) -> str:
    """Where ``url`` points (driver, host, port, database), for logs: no
    username, password or query string, any of which may hold credentials."""
    try:
        from sqlalchemy.engine import make_url

        u = make_url(url)
    except Exception:
        return "(unparseable database URL)"
    where = f"{u.host}:{u.port}" if u.port else (u.host or "")
    return f"{u.drivername}://{where}/{u.database or ''}"


def _worker_notification_service() -> Any | None:
    """The job-email service for a process no ``CeleryJobQueue`` injected one
    into -- a Celery worker. Built once from this process's config, as the web
    app builds its own (``NotificationService`` itself skips sending when no
    SMTP host is configured). None if it cannot be built."""
    global _worker_notifier
    if _worker_notifier is None:
        try:
            from shyfem_ui.services.notification_service import NotificationService

            config = get_config()
            _worker_notifier = NotificationService(config)
            # Recipients are looked up in this process's DB and mailed via its
            # SMTP: both come from the worker's own config (.env in its cwd), so
            # say which ones -- a worker started elsewhere may resolve another.
            logger.info(
                "Worker job emails: SMTP host %r, users from %s",
                config.smtp_host or "(none: emails off)",
                _redacted_db_url(config.database_url),
            )
        except Exception:
            logger.warning("Cannot build the job email service in this worker", exc_info=True)
            return None
    return _worker_notifier


def _send_completion_notification(job_info: JobInfo) -> None:
    """Send email notification for job completion.

    Uses ``_queue_notification_service`` if set (injected by
    ``CeleryJobQueue``), else the worker's own service built from its config:
    the task runs in a worker process, where no queue injected one, so without
    the fallback a Celery job never emailed anyone.
    """
    notification_service = _queue_notification_service or _worker_notification_service()
    if notification_service is None:
        return
    try:
        user_id = job_info.metadata.get("user_id")
        user_dict: dict = {}
        if user_id:
            try:
                from shyfem_ui.db.base import db_session
                from shyfem_ui.models.user import User

                with db_session() as db:
                    user = db.query(User).filter_by(id=user_id).first()
                    # Read scalar fields INSIDE the session — after the block the
                    # instance is expired (expire_on_commit) and attribute access
                    # raises DetachedInstanceError, dropping the email.
                    if user:
                        user_dict = {"username": user.username, "email": user.email}
            except Exception:
                logger.debug("Could not look up user %s for notification", user_id, exc_info=True)

        duration = None
        if job_info.started_at and job_info.completed_at:
            duration = (job_info.completed_at - job_info.started_at).total_seconds()
        job_dict = {
            "name": job_info.name,
            "duration": duration,
            "working_dir": job_info.working_dir,
            "stderr": job_info.error_message or "",
        }
        if job_info.status == JobStatus.CANCELLED:
            # A user-cancelled job is not a failure — sending a
            # "simulation failed" email on a deliberate cancel is wrong.
            return
        if job_info.status == JobStatus.COMPLETED:
            notification_service.notify_job_success(user_dict, job_dict)
        else:
            notification_service.notify_job_failed(user_dict, job_dict)
    except Exception:
        logger.warning(
            "Failed to send completion notification for job %s", job_info.id, exc_info=True
        )


# Register the task with Celery when the module is imported by a worker
def _register_celery_task(app: Any) -> Any:
    """Register the execute task with the Celery app."""

    @app.task(bind=True, name="shyfem_ui.execute_job")
    def _execute_job_task(self, job_id: str, redis_url: str, shyfem_dir: str):
        execute_shyfem_job(job_id, redis_url, shyfem_dir, hostname=self.request.hostname)

    return _execute_job_task


# The task registered on the worker-side app, once (see __getattr__).
_worker_task = None


def __getattr__(name: str) -> Any:
    """Module attribute ``app``: the Celery app with the job task registered.

    ``celery -A shyfem_ui.services.job_celery worker`` looks this module up
    for an ``app`` attribute; without one it finds no app and cannot start a
    worker. It is built on first access only (PEP 562), so importing the
    module never needs Celery installed: local mode and the tests import it
    without. Asking for ``app`` itself (``hasattr`` included) does, and raises
    ImportError without it -- kept so ``celery -A`` says "install celery"
    rather than "no app". The broker URL is ``SHYFEM_UI_REDIS_URL``, as on the
    web side; a worker reads ``.env`` from its working directory.
    """
    if name == "app":
        global _worker_task
        app = get_celery_app(get_config().redis_url)
        if _worker_task is None:
            _worker_task = _register_celery_task(app)
        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class CeleryJobQueue(JobQueue):
    """Celery-based job queue for distributed execution.

    Stores job state in Redis, dispatches execution to Celery workers.

    Requires:
        - celery>=5.3
        - redis>=4.5
        - A running Redis server
        - Celery workers started with: celery -A shyfem_ui.services.job_celery worker
    """

    def __init__(
        self,
        shyfem_dir: Path | None = None,
        redis_url: str | None = None,
        *,
        session_factory: Callable | None = None,
        notification_service: Any | None = None,
    ):
        self.shyfem_dir = shyfem_dir or Path(str(get_config().shyfem_dir))
        self.redis_url = redis_url or "redis://localhost:6379/0"
        self.session_factory = session_factory
        self.notification_service = notification_service
        self._celery_app = None
        self._redis_client = None
        self._task = None
        # RUNNING jobs found missing on the last reconcile pass; a job is only
        # declared lost on its second consecutive miss.
        self._missing_last_pass: set[str] = set()
        # The reconcile reaches the Celery app from cleanup's worker thread.
        self._celery_app_lock = threading.Lock()
        # /health's active-job count: one Redis scan in flight, shared by
        # every concurrent probe, and its result reused briefly.
        self._count_task: asyncio.Future | None = None
        self._count_cache: tuple[float, int] | None = None

        # Publish to module-level globals so Celery task callbacks
        # (running in the same process) can reach these services.
        global _queue_session_factory, _queue_notification_service
        if session_factory is not None:
            _queue_session_factory = session_factory
        if notification_service is not None:
            _queue_notification_service = notification_service

    # ------------------------------------------------------------------
    # Database persistence and notification helpers (instance-level)
    # Mirror the same method names used by LocalJobQueue so callers
    # can treat both queues uniformly.
    # ------------------------------------------------------------------

    def _persist_job(self, job: JobInfo) -> None:
        """Write or update a job row in the database.

        Thread-safe — passes ``session_factory`` explicitly and does not
        mutate module-level globals.
        """
        _persist_job_to_db(job, session_factory=self.session_factory)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_celery_app(self):
        with self._celery_app_lock:
            if self._celery_app is None:
                self._celery_app = get_celery_app(self.redis_url)
                self._task = _register_celery_task(self._celery_app)
        return self._celery_app

    def _get_redis_client(self):
        if self._redis_client is None:
            self._redis_client = _get_redis_client(self.redis_url, bounded=True)
        return self._redis_client

    async def submit(self, spec: JobSpec) -> str:
        """Submit a job to Celery for execution."""
        job_id = self.generate_job_id()

        job_info = JobInfo(
            id=job_id,
            name=spec.name,
            tool_name=spec.tool_name,
            args=spec.args.copy(),
            working_dir=str(spec.working_dir),
            status=JobStatus.PENDING,
            created_at=datetime.now(),
            simulation_id=spec.simulation_id,
            metadata=spec.metadata.copy(),
        )

        if spec.mpi_enabled:
            job_info.metadata["mpi_enabled"] = True
            job_info.metadata["mpi_np"] = spec.mpi_np

        rc = self._get_redis_client()
        _store_job_info(rc, job_info)

        # Dispatch to Celery worker
        self._get_celery_app()
        result = self._task.apply_async(
            args=[job_id, self.redis_url, str(self.shyfem_dir)],
            task_id=job_id,
        )
        # Record the ACTUAL dispatched task id (today task_id=job_id, but read
        # it from the AsyncResult so the persisted column stays correct if the
        # task-id scheme ever diverges). Carried via metadata: it round-trips
        # through Redis to the worker, whose _persist_job_to_db writes the row.
        job_info.metadata["celery_task_id"] = result.id

        job_info.status = JobStatus.QUEUED
        job_info.queued_at = datetime.now()
        _store_job_info(rc, job_info)

        return job_id

    async def active_job_count_async(self) -> int:
        """Number of PENDING/QUEUED/RUNNING jobs in the Redis job store, for
        /health. Counted in a worker thread: it is a Redis round trip.

        /health is unauthenticated and ahead of rate limiting, so a flood of
        probes must not each take a thread from the shared to_thread pool
        (with Redis blackholed, each would hold one for the connect timeout):
        at most one scan runs at a time, every concurrent caller awaits that
        one, and a successful count is reused for ``ACTIVE_COUNT_CACHE_S``.
        The scan is shielded, so a caller giving up (``wait_for`` timeout)
        does not cancel it for the others; an error is never cached.
        """
        cached = self._count_cache
        if cached is not None and time.monotonic() - cached[0] < ACTIVE_COUNT_CACHE_S:
            return cached[1]
        loop = asyncio.get_running_loop()
        task = self._count_task
        if task is None or task.done() or task.get_loop() is not loop:
            task = self._count_task = loop.create_task(asyncio.to_thread(self._count_active_jobs))
            task.add_done_callback(self._harvest_count)
        count = await asyncio.shield(task)
        self._count_cache = (time.monotonic(), count)
        return count

    def _harvest_count(self, task: asyncio.Future) -> None:
        """Done-callback of the shared scan: cache its count even when every
        waiter already timed out (a slow but working Redis would otherwise
        never get a count to /health), and read its exception so asyncio
        does not log "exception was never retrieved" for a scan no one
        awaited to the end."""
        if task.cancelled():
            return
        if task.exception() is None:
            self._count_cache = (time.monotonic(), task.result())

    def _count_active_jobs(self) -> int:
        count = 0
        for raw in self._get_redis_client().hvals("shyfem:jobs"):
            try:
                status = json.loads(raw).get("status")
            except (TypeError, ValueError, AttributeError):
                continue  # an unreadable row is not an active job
            if status in _ACTIVE_STATUS_VALUES:
                count += 1
        return count

    async def cancel(self, job_id: str) -> bool:
        """Cancel a job."""
        rc = self._get_redis_client()
        job_info = _load_job_info(rc, job_id)
        if not job_info or not job_info.is_active:
            return False

        app = self._get_celery_app()
        app.control.revoke(job_id, terminate=True)

        job_info.status = JobStatus.CANCELLED
        job_info.completed_at = datetime.now()
        _store_job_info(rc, job_info)
        return True

    async def get_status(self, job_id: str) -> JobInfo | None:
        """Get current status of a job."""
        return _load_job_info(self._get_redis_client(), job_id)

    async def list_jobs(
        self,
        status: JobStatus | None = None,
        simulation_id: int | None = None,
        limit: int = 100,
        session_id: str | None = None,
        user_id: int | None = None,
    ) -> list[JobInfo]:
        """List jobs with optional filtering."""
        rc = self._get_redis_client()
        job_ids = rc.zrevrange("shyfem:jobs:by_time", 0, -1)

        jobs = []
        for job_id in job_ids:
            if isinstance(job_id, bytes):
                job_id = job_id.decode()

            job_info = _load_job_info(rc, job_id)
            if not job_info:
                continue

            if status and job_info.status != status:
                continue

            if simulation_id is not None and job_info.simulation_id != simulation_id:
                continue

            if session_id is not None and job_info.metadata.get("session_id") != session_id:
                continue

            if user_id is not None and job_info.metadata.get("user_id") != user_id:
                continue

            jobs.append(job_info)
            if len(jobs) >= limit:
                break

        return jobs

    async def get_output(self, job_id: str, stream: str = "stdout", tail: int = 100) -> str:
        """Get job output."""
        rc = self._get_redis_client()
        job_info = _load_job_info(rc, job_id)
        if not job_info:
            return ""

        file_path = job_info.stdout_file if stream == "stdout" else job_info.stderr_file
        if not file_path:
            return ""

        from shyfem_ui.services.file_utils import tail_file

        return tail_file(file_path, tail=tail)

    async def cleanup_old_jobs(self, days: int = 7) -> int:
        """Remove jobs older than N days.

        Awaited directly by maintenance.py; every step (Redis scan/deletes,
        file unlinks, SQL row delete) is blocking, so the whole pass runs in a
        worker thread instead of stalling the event loop.
        """
        return await asyncio.to_thread(self._cleanup_old_jobs_sync, days)

    def reconcile_phantom_jobs(self) -> int:
        """Mark RUNNING jobs whose worker is gone as FAILED; return how many.

        A worker killed mid-job (OOM, reboot, ``kill -9``) never runs the
        task's ``finally``, so the job stays RUNNING in Redis for good: shown
        as running, and skipped by cleanup as active. Unlike
        ``LocalJobQueue``'s reconcile, a fresh web process proves nothing
        here -- workers are separate daemons and keep running jobs across a
        web restart -- so the evidence is the workers' own ``active`` lists.

        A RUNNING job is missing when the worker that took it (recorded on the
        job as ``celery_worker``) replied without listing it, and lost after
        two misses on consecutive passes; a pass with no usable reply resets
        the count, so a worker that missed one reply window keeps its job. A
        worker that does not reply is no evidence: it may be dead, unreachable,
        or a busy ``solo`` worker. Neither is a node name that replied more
        than once (two workers started without distinct ``-n``): Celery would
        keep only one of their replies. A worker killed and restarted under the
        same node name (the usual reboot) replies and frees its jobs; one that
        never returns under that name leaves them RUNNING, as before this pass
        existed, and so does a job with no recorded worker (started by a worker
        older than this code: restart workers to cover their jobs). The write
        is a compare-and-set on the job store (WATCH/MULTI): if anything wrote
        to it after the status was re-read, the job is left for a later pass,
        so a job that finished meanwhile keeps its result. The reconciled job
        gets what the task's ``finally`` would have written (FAILED,
        ``completed_at``, a SQL row), but no email, as in the local reconcile.

        QUEUED jobs are not reconciled. One whose message a dying worker had
        already taken is lost too, but telling it from one still waiting in
        the broker would mean reading kombu's Redis message format.
        """
        # Only misses seen on the previous pass count; anything that ends
        # this pass early (a Redis error, no reply) leaves the count reset.
        previous, self._missing_last_pass = self._missing_last_pass, set()
        rc = self._get_redis_client()
        running = []
        for job_id in rc.zrange("shyfem:jobs:by_time", 0, -1):
            if isinstance(job_id, bytes):
                job_id = job_id.decode()
            info = _load_job_info(rc, job_id)
            if info is not None and info.status == JobStatus.RUNNING:
                running.append(info)
        if not running:
            return 0

        live_on = self._active_tasks_by_worker()
        if not live_on:
            logger.warning(
                "Job reconcile: no usable reply from any Celery worker; %d RUNNING job(s) "
                "left as they are",
                len(running),
            )
            return 0

        def _missing(info: JobInfo) -> bool:
            meta = info.metadata or {}
            worker = meta.get("celery_worker")
            if worker not in live_on:
                return False  # no worker recorded, or it did not (usably) reply
            return (meta.get("celery_task_id") or info.id) not in live_on[worker]

        missing = {info.id for info in running if _missing(info)}
        lost = missing & previous
        self._missing_last_pass = missing - lost

        count = 0
        for job_id in sorted(lost):
            info = self._fail_if_still_running(rc, job_id)
            if info is not None:
                self._persist_job(info)
                count += 1
        if count:
            logger.warning("Reconciled %d lost RUNNING Celery job(s) to FAILED", count)
        return count

    def _active_tasks_by_worker(self) -> dict[str, set[str]]:
        """``{worker node name: ids of the tasks it is running}``, from the
        workers that replied once each.

        Uses the raw broadcast rather than ``inspect().active()``, which merges
        replies by node name: two workers sharing a name would show as one,
        possibly the idle one. A name that replied more than once is dropped.
        """
        raw = self._get_celery_app().control.broadcast(
            "active", arguments={}, reply=True, timeout=INSPECT_TIMEOUT_S
        )
        live_on: dict[str, set[str]] = {}
        dupes: set[str] = set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            for worker, tasks in item.items():
                if worker in live_on:
                    dupes.add(worker)
                live_on[worker] = {
                    t.get("id")
                    for t in (tasks if isinstance(tasks, list) else [])
                    if isinstance(t, dict)
                }
        if dupes:
            logger.warning(
                "Job reconcile: several Celery workers reply as %s; their jobs are left as they "
                "are (start workers with distinct names, e.g. -n worker%%i@%%h)",
                ", ".join(sorted(dupes)),
            )
        return {w: ids for w, ids in live_on.items() if w not in dupes}

    CAS_ATTEMPTS = 3

    @classmethod
    def _fail_if_still_running(cls, rc, job_id: str) -> JobInfo | None:
        """Write FAILED for ``job_id`` only if it is RUNNING and the job store
        is untouched from that read to the write; the written job, else None.

        The WATCH covers the whole hash, so any job's write aborts it; each
        retry re-reads the status, so one that finished is never overwritten.
        """
        for _ in range(cls.CAS_ATTEMPTS):
            with rc.pipeline() as pipe:
                try:
                    pipe.watch("shyfem:jobs")
                    info = _load_job_info(pipe, job_id)
                    if info is None or info.status != JobStatus.RUNNING:
                        return None  # finished (or removed) since the scan
                    info.status = JobStatus.FAILED
                    info.error_message = CELERY_LOST_ERROR
                    if info.completed_at is None:
                        info.completed_at = datetime.now()
                    pipe.multi()
                    _store_job_info(pipe, info)
                    pipe.execute()
                    return info
                except _WatchError:
                    continue
        logger.info(
            "Job reconcile: job store kept changing under %s; left for a later pass", job_id
        )
        return None

    def _cleanup_old_jobs_sync(self, days: int) -> int:
        """Blocking body of cleanup_old_jobs (run via asyncio.to_thread).

        Reconciles lost jobs first, so an old one is pruned in the same pass
        that finds it lost.
        """
        try:
            self.reconcile_phantom_jobs()
        except Exception:
            logger.warning("Job reconcile failed; cleanup continues", exc_info=True)
        rc = self._get_redis_client()
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_timestamp = cutoff.timestamp()

        old_job_ids = rc.zrangebyscore("shyfem:jobs:by_time", "-inf", cutoff_timestamp)

        count = 0
        removed_uuids: list[str] = []
        for job_id in old_job_ids:
            if isinstance(job_id, bytes):
                job_id = job_id.decode()

            job_info = _load_job_info(rc, job_id)
            if job_info and not job_info.is_active:
                rc.hdel("shyfem:jobs", job_id)
                rc.zrem("shyfem:jobs:by_time", job_id)

                for fp in [job_info.stdout_file, job_info.stderr_file]:
                    if fp:
                        try:
                            Path(fp).unlink(missing_ok=True)
                        except Exception:
                            logger.debug("Failed to clean up file %s", fp)

                removed_uuids.append(job_id)
                count += 1

        # Also delete the persisted SQL rows (written by _persist_job_to_db),
        # else the jobs table grows unbounded alongside the cleaned Redis store.
        if removed_uuids:
            try:
                from shyfem_ui.db.base import db_session
                from shyfem_ui.models.project import Job

                with db_session() as db:
                    db.query(Job).filter(Job.job_uuid.in_(removed_uuids)).delete(
                        synchronize_session=False
                    )
            except Exception:
                logger.error(
                    "Could not delete %d job row(s) from DB", len(removed_uuids), exc_info=True
                )

        return count
