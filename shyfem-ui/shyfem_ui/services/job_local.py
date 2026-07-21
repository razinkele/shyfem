"""Local multiprocessing job queue implementation."""

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

from shyfem_ui.config import get_config
from shyfem_ui.services.job_queue import (
    JobInfo,
    JobQueue,
    JobSpec,
    JobStatus,
    job_identity_metadata,
)

logger = logging.getLogger(__name__)


def write_output_line(stdout_fh, line: str) -> None:
    """Append ``line`` (with a trailing newline) to the open stdout file handle
    and flush immediately, so the log viewer sees output as it streams.

    A no-op when ``stdout_fh`` is None — the handle may be None if opening the
    stdout file failed (disk full / permissions), in which case the job still
    runs and this must not raise.
    """
    if stdout_fh:
        stdout_fh.write(line + "\n")
        stdout_fh.flush()


class LocalJobQueue(JobQueue):
    """Local job queue using asyncio for concurrent execution.

    Jobs are executed in the same process using asyncio tasks,
    with configurable concurrency limits.  Completed jobs are
    persisted to the database so they survive server restarts.
    """

    MAX_STORED_JOBS = 500
    TEMP_FILE_RETENTION_SECS = 3600  # Clean temp files 1 hour after job completion
    ORPHANED_ERROR = "orphaned at server restart"

    def __init__(
        self,
        shyfem_dir: Path | None = None,
        max_workers: int = 4,
        notification_service=None,
    ):
        """Initialize local job queue.

        Args:
            shyfem_dir: Path to SHYFEM installation
            max_workers: Maximum concurrent jobs
            notification_service: Optional NotificationService for job completion emails
        """
        from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

        self.shyfem_dir = shyfem_dir or Path(__file__).resolve().parents[3]
        self.max_workers = max_workers
        self.notification_service = notification_service
        self.wrapper = ShyfemWrapper(self.shyfem_dir)

        # Job storage (in-memory for active jobs, DB for history)
        self._jobs: OrderedDict[str, JobInfo] = OrderedDict()
        self._tasks: dict[str, asyncio.Task] = {}

        # Concurrency control (semaphore created lazily)
        self._semaphore: asyncio.Semaphore | None = None
        self._running_count = 0

        # Job history is loaded lazily, NOT here (F51). __init__ may run
        # before any event loop exists (app startup builds the App object
        # before uvicorn/ASGI takes over) or while one is already running
        # (an async test/session constructing a queue directly) -- either
        # way it cannot itself await, so calling the synchronous DB query
        # inline would either be impossible or would block the loop for
        # everyone else. A freshly constructed queue has no live task for
        # any job anyway, so nothing is lost by deferring the read: the
        # first public method that needs self._jobs triggers the load via
        # _ensure_history_loaded(), off the loop via asyncio.to_thread.
        self._history_loaded = False
        self._history_load_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # Database persistence helpers
    # ------------------------------------------------------------------

    def _load_history_from_db(self) -> list[JobInfo]:
        """Load recent jobs from the database, oldest first.

        Runs off the event loop (via _ensure_history_loaded's
        asyncio.to_thread), on a worker thread. It therefore returns the
        loaded rows rather than writing self._jobs directly: self._jobs
        must only ever be mutated on the event-loop thread (the merge
        happens back in _ensure_history_loaded) -- writing it here too
        would race an unlocked sync reader such as active_job_count
        against this worker thread (RuntimeError: dictionary changed size
        during iteration).

        A freshly constructed queue has no live asyncio task for ANY job by
        definition — so rows persisted in an active status (PENDING/QUEUED/
        RUNNING) are phantoms left behind by a previous process (crash,
        deploy, restart). They are reconciled to FAILED with error
        ``ORPHANED_ERROR`` and the correction is persisted back, so they stop
        being reported "active" forever (which previously inflated /health's
        active_job_count and made them immune to cleanup_old_jobs).
        """
        loaded: list[JobInfo] = []
        try:
            from shyfem_ui.db.base import db_session
            from shyfem_ui.models.project import Job

            active_statuses = (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)
            reconciled = 0
            with db_session() as db:
                rows = (
                    db.query(Job).order_by(Job.created_at.desc()).limit(self.MAX_STORED_JOBS).all()
                )
                for row in rows:
                    if row.status in active_statuses:
                        row.status = JobStatus.FAILED
                        row.error_message = self.ORPHANED_ERROR
                        if row.completed_at is None:
                            row.completed_at = datetime.now()
                        reconciled += 1
                for row in reversed(rows):  # oldest first so OrderedDict order is correct
                    loaded.append(self._db_row_to_job_info(row))
            if reconciled:
                logger.warning(
                    "Reconciled %d phantom active job row(s) to FAILED at startup", reconciled
                )
        except Exception:
            # DB may not be initialised yet at import time — that's fine
            logger.warning("Could not load job history from DB", exc_info=True)
        return loaded

    async def _ensure_history_loaded(self) -> None:
        """Load job history from the DB on first use (F51).

        Every public method that reads/writes self._jobs calls this first.
        The (synchronous) query runs in a worker thread via
        asyncio.to_thread so it never blocks the event loop. Concurrent
        callers serialize on a lock: only one of them actually performs the
        load (a racing caller waits on the lock, then sees the flag already
        set and returns immediately).

        _load_history_from_db only READS the DB and RETURNS the rows -- it
        never touches self._jobs itself, because it runs on a worker
        thread. The merge below runs back on the event-loop thread (after
        the await returns), which is the only thread ever allowed to
        mutate self._jobs: an unlocked sync reader like active_job_count
        iterates self._jobs.values() with no lock, and self._jobs is a
        plain OrderedDict, so a worker thread mutating it concurrently
        could raise "dictionary changed size during iteration".
        self._jobs is guaranteed empty of these rows until this point
        (every writer awaits this method first), so setdefault is just a
        defensive no-clobber, not a real merge.
        """
        if self._history_loaded:
            return
        if self._history_load_lock is None:
            self._history_load_lock = asyncio.Lock()
        async with self._history_load_lock:
            if self._history_loaded:
                return
            loaded = await asyncio.to_thread(self._load_history_from_db)
            for info in loaded:
                self._jobs.setdefault(info.id, info)
            self._history_loaded = True

    @staticmethod
    def _db_row_to_job_info(row) -> JobInfo:
        """Convert a Job ORM row to a JobInfo dataclass."""
        output_files = getattr(row, "output_files", None)
        if not isinstance(output_files, list):
            # NULL (column added by migration 7e41388e2c8d, never written on
            # older rows) or any non-list value -- never surface it as-is,
            # tolerate as an empty list (N40).
            output_files = []
        return JobInfo(
            id=row.job_uuid,
            name=row.name,
            tool_name=row.job_type,
            args=[],
            working_dir=row.working_dir,
            status=row.status,
            progress=row.progress or 0.0,
            progress_message=row.progress_message or "",
            created_at=row.created_at,
            queued_at=row.queued_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            return_code=row.return_code,
            error_message=row.error_message,
            stdout_file=row.stdout_file,
            stderr_file=row.stderr_file,
            output_files=output_files,
            simulation_id=row.simulation_id,
            metadata=job_identity_metadata(row),
        )

    def _persist_job(self, job: JobInfo) -> None:
        """Write or update a job row in the database."""
        try:
            from shyfem_ui.db.base import db_session
            from shyfem_ui.models.project import Job

            with db_session() as db:
                row = db.query(Job).filter(Job.job_uuid == job.id).first()
                if row is None:
                    row = Job(
                        job_uuid=job.id,
                        name=job.name,
                        job_type=job.tool_name,
                        command=" ".join(job.args),
                        working_dir=job.working_dir,
                        simulation_id=job.simulation_id,
                        session_id=job.metadata.get("session_id"),
                        user_id=job.metadata.get("user_id"),
                        project_id=job.metadata.get("project_id"),
                    )
                    db.add(row)

                row.status = job.status
                row.progress = job.progress
                row.progress_message = job.progress_message
                row.queued_at = job.queued_at
                row.started_at = job.started_at
                row.completed_at = job.completed_at
                row.return_code = job.return_code
                row.error_message = job.error_message
                row.stdout_file = job.stdout_file
                row.stderr_file = job.stderr_file
                row.output_files = list(job.output_files) if job.output_files else []
        except Exception:
            logger.error("Could not persist job %s to DB", job.id, exc_info=True)

    def _send_completion_notification(self, job: "JobInfo") -> None:
        """Send email notification for job completion. Skips if not configured."""
        if self.notification_service is None:
            return
        try:
            from shyfem_ui.services.job_queue import JobStatus

            user_id = job.metadata.get("user_id")
            user_dict: dict = {}
            if user_id:
                try:
                    from shyfem_ui.db.base import db_session
                    from shyfem_ui.models.user import User

                    with db_session() as db:
                        user = db.query(User).filter_by(id=user_id).first()
                        # Read scalar fields INSIDE the session — after the block
                        # the instance is expired (expire_on_commit) and attribute
                        # access raises DetachedInstanceError, dropping the email.
                        if user:
                            user_dict = {"username": user.username, "email": user.email}
                except Exception:
                    logger.debug(
                        "Could not look up user %s for notification", user_id, exc_info=True
                    )

            duration = None
            if job.started_at and job.completed_at:
                duration = (job.completed_at - job.started_at).total_seconds()
            job_dict = {
                "name": job.name,
                "duration": duration,
                "working_dir": job.working_dir,
                "stderr": job.error_message or "",
            }
            if job.status == JobStatus.CANCELLED:
                # A user-cancelled job is not a failure — sending a
                # "simulation failed" email on a deliberate cancel is wrong.
                return
            if job.status == JobStatus.COMPLETED:
                self.notification_service.notify_job_success(user_dict, job_dict)
            else:
                self.notification_service.notify_job_failed(user_dict, job_dict)
        except Exception:
            logger.warning(
                "Failed to send completion notification for job %s", job.id, exc_info=True
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_old_jobs(self) -> None:
        """Remove oldest completed jobs when storage exceeds MAX_STORED_JOBS."""
        if len(self._jobs) <= self.MAX_STORED_JOBS:
            return

        to_remove = []
        for job_id, job in self._jobs.items():
            if not job.is_active:
                to_remove.append(job_id)
            if len(self._jobs) - len(to_remove) <= self.MAX_STORED_JOBS:
                break

        for job_id in to_remove:
            self._jobs.pop(job_id, None)

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Get or create the semaphore (must be called from async context)."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_workers)
        return self._semaphore

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(self, spec: JobSpec) -> str:
        """Submit a job for execution."""
        await self._ensure_history_loaded()
        self._evict_old_jobs()
        job_id = self.generate_job_id()

        # Create job info
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

        # Store MPI settings in metadata
        if spec.mpi_enabled:
            job_info.metadata["mpi_enabled"] = True
            job_info.metadata["mpi_np"] = spec.mpi_np

        # Ensure output directory exists
        output_dir = Path(spec.working_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Setup output files
        job_info.stdout_file = str(output_dir / f"{job_id}.stdout")
        job_info.stderr_file = str(output_dir / f"{job_id}.stderr")

        # Store job in memory and persist to DB (offloaded: this is a
        # synchronous DB write and must not block the event loop, F22).
        self._jobs[job_id] = job_info
        await asyncio.to_thread(self._persist_job, job_info)

        # Start execution task
        task = asyncio.create_task(self._execute_job(job_id, spec))
        self._tasks[job_id] = task

        return job_id

    async def _execute_job(self, job_id: str, spec: JobSpec) -> None:
        """Execute a job with concurrency control."""
        job = self._jobs.get(job_id)
        if not job:
            return

        # Wait for available slot
        job.status = JobStatus.QUEUED
        job.queued_at = datetime.now()
        await asyncio.to_thread(self._persist_job, job)

        async with self._get_semaphore():
            self._running_count += 1
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now()
            await asyncio.to_thread(self._persist_job, job)

            stdout_fh = None

            def progress_callback(progress: float, message: str):
                job.progress = progress
                job.progress_message = message
                self._notify_progress(job_id, progress, message)

            def output_callback(line: str):
                write_output_line(stdout_fh, line)

            try:
                # Open the stdout log INSIDE the try so a touch/open failure
                # (disk full, permissions) marks the job FAILED and releases
                # _running_count via the finally — instead of leaking both.
                if job.stdout_file:
                    Path(job.stdout_file).touch()
                    stdout_fh = open(job.stdout_file, "a")

                solver = spec.metadata.get("solver", "sparskit")
                if spec.tool_name == "shyfem" and spec.mpi_enabled and spec.mpi_np > 1:
                    # MPI execution
                    result = await self.wrapper.run_shyfem(
                        spec.args[-1] if spec.args else "",
                        spec.working_dir,
                        mpi_enabled=True,
                        mpi_np=spec.mpi_np,
                        mpirun_path=get_config().mpirun_path,
                        options=spec.args[:-1] if len(spec.args) > 1 else None,
                        solver=solver,
                        progress_callback=progress_callback,
                        output_callback=output_callback,
                        # Stdout is streamed to the job log file via
                        # output_callback; don't also buffer it all in RAM.
                        capture_stdout=False,
                    )
                elif spec.tool_name == "shyfem":
                    # Serial shyfem (may use petsc solver)
                    result = await self.wrapper.run_shyfem(
                        spec.args[-1] if spec.args else "",
                        spec.working_dir,
                        solver=solver,
                        progress_callback=progress_callback,
                        output_callback=output_callback,
                        capture_stdout=False,
                    )
                else:
                    result = await self.wrapper.run_command(
                        spec.tool_name,
                        spec.args,
                        spec.working_dir,
                        progress_callback,
                        output_callback,
                        capture_stdout=False,
                    )

                # Update job with result
                job.return_code = result.return_code
                job.output_files = result.output_files
                job.progress = 1.0

                if result.success:
                    job.status = JobStatus.COMPLETED
                else:
                    job.status = JobStatus.FAILED
                    job.error_message = result.stderr[:1000] if result.stderr else "Unknown error"

                # Write stderr (small, captured at end by wrapper)
                if job.stderr_file and result.stderr:
                    Path(job.stderr_file).write_text(result.stderr)

            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                job.error_message = "Job was cancelled"
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
            finally:
                if stdout_fh:
                    stdout_fh.close()
                job.completed_at = datetime.now()
                self._running_count -= 1
                # Clean up task reference
                self._tasks.pop(job_id, None)
                # Persist final state to DB
                await asyncio.to_thread(self._persist_job, job)
                # Send completion notification (best-effort, never raises).
                # Offload to a worker thread: it does blocking SMTP I/O (now
                # bounded by smtp_timeout_seconds) which must not block the
                # asyncio event loop / other sessions on job completion.
                await asyncio.to_thread(self._send_completion_notification, job)

    async def cancel(self, job_id: str) -> bool:
        """Cancel a running job."""
        await self._ensure_history_loaded()
        job = self._jobs.get(job_id)
        if not job:
            return False

        if not job.is_active:
            return False

        task = self._tasks.get(job_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now()
        await asyncio.to_thread(self._persist_job, job)
        return True

    async def get_status(self, job_id: str) -> JobInfo | None:
        """Get current status of a job."""
        await self._ensure_history_loaded()
        return self._jobs.get(job_id)

    async def list_jobs(
        self,
        status: JobStatus | None = None,
        simulation_id: int | None = None,
        limit: int = 100,
        session_id: str | None = None,
        user_id: int | None = None,
    ) -> list[JobInfo]:
        """List jobs with optional filtering."""
        await self._ensure_history_loaded()
        jobs = list(self._jobs.values())

        # Filter by status
        if status:
            jobs = [j for j in jobs if j.status == status]

        # Filter by simulation
        if simulation_id is not None:
            jobs = [j for j in jobs if j.simulation_id == simulation_id]

        # Filter by session (legacy / non-ownership scoping, e.g. progress polling)
        if session_id is not None:
            jobs = [j for j in jobs if j.metadata.get("session_id") == session_id]

        # Filter by owning user (server-mode per-user isolation, F17)
        if user_id is not None:
            jobs = [j for j in jobs if j.metadata.get("user_id") == user_id]

        # Sort by creation time (newest first)
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        return jobs[:limit]

    async def get_output(self, job_id: str, stream: str = "stdout", tail: int = 100) -> str:
        """Get job output."""
        await self._ensure_history_loaded()
        job = self._jobs.get(job_id)
        if not job:
            return ""

        file_path = job.stdout_file if stream == "stdout" else job.stderr_file
        if not file_path:
            return ""

        from shyfem_ui.services.file_utils import tail_file

        return tail_file(file_path, tail=tail)

    async def cleanup_old_jobs(self, days: int = 7) -> int:
        """Remove jobs older than N days."""
        await self._ensure_history_loaded()
        # Local cutoff for the in-memory pass and for Job.completed_at, which is
        # persisted from job.completed_at = datetime.now() (naive LOCAL).
        cutoff = datetime.now() - timedelta(days=days)
        # UTC cutoff for Job.created_at, which is populated by
        # server_default=func.now() (SQLite CURRENT_TIMESTAMP = UTC) and never
        # written from Python. Comparing it against a local cutoff prunes the
        # wrong window by the local offset on a non-UTC server.
        utc_cutoff = datetime.utcnow() - timedelta(days=days)
        to_remove = []

        for job_id, job in self._jobs.items():
            if job.completed_at and job.completed_at < cutoff:
                to_remove.append(job_id)
            elif job.created_at < cutoff and not job.is_active:
                to_remove.append(job_id)

        for job_id in to_remove:
            job = self._jobs.pop(job_id, None)
            if job:
                # Clean up output files
                for file_path in [job.stdout_file, job.stderr_file]:
                    if file_path:
                        path = Path(file_path)
                        if path.exists():
                            try:
                                path.unlink()
                            except Exception:
                                # Best-effort cleanup — never fail eviction if a
                                # stale output file can't be removed, but log it.
                                logger.debug(
                                    "Could not remove job output file %s", path, exc_info=True
                                )

        # Also delete the persisted rows, else the jobs table grows unbounded
        # (eviction from the in-memory dict alone left thousands of stale rows).
        # Offloaded to a thread: both are synchronous DB work (unbounded scan +
        # per-row delete) that would otherwise block the event loop — this is
        # awaited directly from maintenance.py, unlike the sibling cleanups.
        await asyncio.to_thread(self._delete_job_rows, to_remove)

        # Purge OLD rows that are no longer in the in-memory window. The loop
        # above only sees self._jobs (capped at MAX_STORED_JOBS), so once that
        # cap is exceeded the evicted rows were never deleted and the jobs table
        # grew without bound. Delete them directly by timestamp.
        db_purged = await asyncio.to_thread(self._delete_old_db_rows, cutoff, utc_cutoff, to_remove)

        return len(to_remove) + db_purged

    def _delete_old_db_rows(
        self, cutoff: datetime, utc_cutoff: datetime, exclude: list[str]
    ) -> int:
        """Delete persisted Job rows older than the retention window regardless
        of whether they are still tracked in memory, returning the number
        removed. Each timestamp column is compared against a cutoff in ITS OWN
        zone: ``completed_at`` is naive-LOCAL (persisted from datetime.now()) so
        it uses ``cutoff``, while ``created_at`` is UTC (server_default
        func.now(), never written from Python) so it uses ``utc_cutoff``. Output
        files are unlinked best-effort. Rows in ``exclude`` are skipped (already
        handled by the in-memory pass). Best-effort: a DB failure must not abort
        cleanup."""
        try:
            from sqlalchemy import and_, or_

            from shyfem_ui.db.base import db_session
            from shyfem_ui.models.project import Job

            active = (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)
            old_filter = or_(
                and_(Job.completed_at.isnot(None), Job.completed_at < cutoff),
                and_(Job.created_at < utc_cutoff, Job.status.notin_(active)),
            )
            with db_session() as db:
                query = db.query(Job).filter(old_filter)
                if exclude:
                    query = query.filter(Job.job_uuid.notin_(exclude))
                rows = query.all()
                for row in rows:
                    for file_path in (row.stdout_file, row.stderr_file):
                        if file_path:
                            path = Path(file_path)
                            if path.exists():
                                try:
                                    path.unlink()
                                except Exception:
                                    logger.debug(
                                        "Could not remove job output file %s",
                                        path,
                                        exc_info=True,
                                    )
                count = len(rows)
                if count:
                    query.delete(synchronize_session=False)
                return count
        except Exception:
            logger.error("DB cleanup of old job rows failed", exc_info=True)
            return 0

    def _delete_job_rows(self, job_uuids: list[str]) -> None:
        """Delete persisted Job rows by uuid. Best-effort — a DB failure must
        not abort in-memory eviction."""
        if not job_uuids:
            return
        try:
            from shyfem_ui.db.base import db_session
            from shyfem_ui.models.project import Job

            with db_session() as db:
                db.query(Job).filter(Job.job_uuid.in_(job_uuids)).delete(synchronize_session=False)
        except Exception:
            logger.error("Could not delete %d job row(s) from DB", len(job_uuids), exc_info=True)

    @property
    def active_job_count(self) -> int:
        """Get count of active jobs."""
        return sum(1 for j in self._jobs.values() if j.is_active)
