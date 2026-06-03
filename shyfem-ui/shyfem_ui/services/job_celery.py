"""Celery/Redis job queue implementation for server mode.

This module provides a distributed job queue using Celery and Redis,
suitable for multi-user server deployments.

Requirements:
    pip install celery redis

Start workers with:
    celery -A shyfem_ui.services.job_celery worker --loglevel=info
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from shyfem_ui.config import get_config
from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobSpec, JobStatus

# Module-level sentinel for the optional session_factory / notification_service
# injected at queue-construction time.  Celery task functions run in worker
# processes and cannot reach the queue object directly; see _persist_job_standalone
# / _send_notification_standalone for the worker-side equivalents.
_queue_session_factory: Callable | None = None
_queue_notification_service: Any | None = None

logger = logging.getLogger(__name__)

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


def _get_redis_client(redis_url: str = "redis://localhost:6379/0") -> Any:
    """Create a Redis client."""
    try:
        import redis
    except ImportError as exc:
        raise ImportError(
            "Redis is required for server mode. Install with: pip install redis"
        ) from exc
    return redis.from_url(redis_url)


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


def execute_shyfem_job(job_id: str, redis_url: str, shyfem_dir: str) -> None:
    """Execute a SHYFEM job (called by Celery worker).

    This runs synchronously using asyncio.run() since Celery workers
    are separate processes with their own event loops.
    """
    import asyncio

    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

    rc = _get_redis_client(redis_url)
    job_info = _load_job_info(rc, job_id)
    if not job_info:
        return

    # Mark as running
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
                    mpirun_path="mpirun",
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


def _send_completion_notification(job_info: JobInfo) -> None:
    """Send email notification for job completion.

    Uses ``_queue_notification_service`` if set (injected by
    ``CeleryJobQueue``).  Skips silently if not configured.
    """
    notification_service = _queue_notification_service
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
        execute_shyfem_job(job_id, redis_url, shyfem_dir)

    return _execute_job_task


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
        self._progress_callback: Callable[[str, float, str], None] | None = None
        self._celery_app = None
        self._redis_client = None
        self._task = None

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
        if self._celery_app is None:
            self._celery_app = get_celery_app(self.redis_url)
            self._task = _register_celery_task(self._celery_app)
        return self._celery_app

    def _get_redis_client(self):
        if self._redis_client is None:
            self._redis_client = _get_redis_client(self.redis_url)
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
        self._task.apply_async(
            args=[job_id, self.redis_url, str(self.shyfem_dir)],
            task_id=job_id,
        )

        job_info.status = JobStatus.QUEUED
        job_info.queued_at = datetime.now()
        _store_job_info(rc, job_info)

        return job_id

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

    def set_progress_callback(self, callback: Callable[[str, float, str], None]) -> None:
        """Set callback for progress updates."""
        self._progress_callback = callback

    async def cleanup_old_jobs(self, days: int = 7) -> int:
        """Remove jobs older than N days."""
        rc = self._get_redis_client()
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_timestamp = cutoff.timestamp()

        old_job_ids = rc.zrangebyscore("shyfem:jobs:by_time", "-inf", cutoff_timestamp)

        count = 0
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

                count += 1

        return count

    async def health_check(self) -> dict[str, bool | list[str] | int]:
        """Check Redis connectivity and Celery worker health.

        Returns:
            Dict with health info:
            - redis_connected: bool
            - workers: list of active worker names
            - active_tasks: total active tasks across workers
            - scheduled_tasks: total scheduled tasks
            - reserved_tasks: total reserved (prefetched) tasks
        """
        result = {
            "redis_connected": False,
            "workers": [],
            "active_tasks": 0,
            "scheduled_tasks": 0,
            "reserved_tasks": 0,
        }

        # Check Redis
        try:
            rc = self._get_redis_client()
            rc.ping()
            result["redis_connected"] = True
        except Exception:
            logger.warning("Redis health check failed", exc_info=True)
            return result

        # Check Celery workers
        try:
            app = self._get_celery_app()
            inspect = app.control.inspect(timeout=3)

            ping = inspect.ping()
            if ping:
                result["workers"] = list(ping.keys())

            active = inspect.active()
            if active:
                result["active_tasks"] = sum(len(t) for t in active.values())

            scheduled = inspect.scheduled()
            if scheduled:
                result["scheduled_tasks"] = sum(len(t) for t in scheduled.values())

            reserved = inspect.reserved()
            if reserved:
                result["reserved_tasks"] = sum(len(t) for t in reserved.values())

        except Exception:
            logger.debug("Failed to inspect Celery workers", exc_info=True)

        return result

    async def worker_info(self) -> list[dict]:
        """Get detailed info about active Celery workers.

        Returns:
            List of dicts, one per worker:
            - name: worker name
            - active_tasks: number of active tasks
            - processed: total tasks processed
            - concurrency: worker concurrency setting
            - pool: pool type (prefork, eventlet, etc.)
        """
        workers = []
        try:
            app = self._get_celery_app()
            inspect = app.control.inspect(timeout=3)

            stats = inspect.stats()
            if not stats:
                return workers

            active = inspect.active() or {}

            for name, stat in stats.items():
                pool = stat.get("pool", {})
                workers.append(
                    {
                        "name": name,
                        "active_tasks": len(active.get(name, [])),
                        "processed": stat.get("total", {}).get("shyfem_ui.execute_job", 0),
                        "concurrency": pool.get("max-concurrency", "?"),
                        "pool": pool.get("implementation", "unknown"),
                        "pid": stat.get("pid", "?"),
                    }
                )

        except Exception:
            logger.debug("Failed to fetch worker stats", exc_info=True)

        return workers
