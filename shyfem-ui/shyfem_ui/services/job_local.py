"""Local multiprocessing job queue implementation."""

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobSpec, JobStatus
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper


class LocalJobQueue(JobQueue):
    """Local job queue using asyncio for concurrent execution.

    Jobs are executed in the same process using asyncio tasks,
    with configurable concurrency limits.
    """

    MAX_STORED_JOBS = 500
    TEMP_FILE_RETENTION_SECS = 3600  # Clean temp files 1 hour after job completion

    def __init__(
        self,
        shyfem_dir: Optional[Path] = None,
        max_workers: int = 4,
    ):
        """Initialize local job queue.

        Args:
            shyfem_dir: Path to SHYFEM installation
            max_workers: Maximum concurrent jobs
        """
        self.shyfem_dir = shyfem_dir or Path(__file__).resolve().parents[3]
        self.max_workers = max_workers
        self.wrapper = ShyfemWrapper(self.shyfem_dir)

        # Job storage (in-memory, capped at MAX_STORED_JOBS)
        self._jobs: OrderedDict[str, JobInfo] = OrderedDict()
        self._tasks: dict[str, asyncio.Task] = {}

        # Concurrency control (semaphore created lazily)
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._running_count = 0

        # Callbacks
        self._progress_callback: Optional[Callable[[str, float, str], None]] = None

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
            job = self._jobs.pop(job_id, None)
            if job:
                for file_path in [job.stdout_file, job.stderr_file]:
                    if file_path:
                        try:
                            Path(file_path).unlink(missing_ok=True)
                        except Exception:
                            pass

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Get or create the semaphore (must be called from async context)."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_workers)
        return self._semaphore

    def _schedule_temp_cleanup(self, job: JobInfo) -> None:
        """Schedule removal of stdout/stderr temp files after retention period."""
        def _cleanup():
            for file_path in [job.stdout_file, job.stderr_file]:
                if file_path:
                    try:
                        Path(file_path).unlink(missing_ok=True)
                    except Exception:
                        pass

        try:
            loop = asyncio.get_event_loop()
            loop.call_later(self.TEMP_FILE_RETENTION_SECS, _cleanup)
        except RuntimeError:
            # No running event loop; clean up immediately
            _cleanup()

    async def submit(self, spec: JobSpec) -> str:
        """Submit a job for execution."""
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

        # Store job
        self._jobs[job_id] = job_info

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

        async with self._get_semaphore():
            self._running_count += 1
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now()

            stdout_lines = []
            stderr_lines = []

            def progress_callback(progress: float, message: str):
                job.progress = progress
                job.progress_message = message
                if self._progress_callback:
                    self._progress_callback(job_id, progress, message)

            def output_callback(line: str):
                stdout_lines.append(line)

            try:
                if spec.tool_name == "shyfem" and spec.mpi_enabled and spec.mpi_np > 1:
                    # MPI execution needs special handling (mpirun wrapper)
                    result = await self.wrapper.run_shyfem(
                        spec.args[-1] if spec.args else "",
                        spec.working_dir,
                        mpi_enabled=True,
                        mpi_np=spec.mpi_np,
                        mpirun_path="mpirun",
                        options=spec.args[:-1] if len(spec.args) > 1 else None,
                        progress_callback=progress_callback,
                        output_callback=output_callback,
                    )
                else:
                    # All tools use run_command uniformly
                    result = await self.wrapper.run_command(
                        spec.tool_name,
                        spec.args,
                        spec.working_dir,
                        progress_callback,
                        output_callback,
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

                # Write output files
                if job.stdout_file:
                    Path(job.stdout_file).write_text(result.stdout)
                if job.stderr_file:
                    Path(job.stderr_file).write_text(result.stderr)

            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                job.error_message = "Job was cancelled"
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
            finally:
                job.completed_at = datetime.now()
                self._running_count -= 1
                # Clean up task reference
                self._tasks.pop(job_id, None)
                # Schedule temp file cleanup after retention period
                self._schedule_temp_cleanup(job)

    async def cancel(self, job_id: str) -> bool:
        """Cancel a running job."""
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
        return True

    async def get_status(self, job_id: str) -> Optional[JobInfo]:
        """Get current status of a job."""
        return self._jobs.get(job_id)

    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        simulation_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[JobInfo]:
        """List jobs with optional filtering."""
        jobs = list(self._jobs.values())

        # Filter by status
        if status:
            jobs = [j for j in jobs if j.status == status]

        # Filter by simulation
        if simulation_id is not None:
            jobs = [j for j in jobs if j.simulation_id == simulation_id]

        # Sort by creation time (newest first)
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        return jobs[:limit]

    async def get_output(
        self, job_id: str, stream: str = "stdout", tail: int = 100
    ) -> str:
        """Get job output."""
        job = self._jobs.get(job_id)
        if not job:
            return ""

        file_path = job.stdout_file if stream == "stdout" else job.stderr_file
        if not file_path:
            return ""

        path = Path(file_path)
        if not path.exists():
            return ""

        try:
            content = path.read_text()
            if tail > 0:
                lines = content.splitlines()
                return "\n".join(lines[-tail:])
            return content
        except Exception:
            return ""

    def set_progress_callback(
        self, callback: Callable[[str, float, str], None]
    ) -> None:
        """Set callback for progress updates."""
        self._progress_callback = callback

    async def cleanup_old_jobs(self, days: int = 7) -> int:
        """Remove jobs older than N days."""
        cutoff = datetime.now() - timedelta(days=days)
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
                                pass

        return len(to_remove)

    @property
    def active_job_count(self) -> int:
        """Get count of active jobs."""
        return sum(1 for j in self._jobs.values() if j.is_active)

    @property
    def running_job_count(self) -> int:
        """Get count of currently running jobs."""
        return self._running_count
