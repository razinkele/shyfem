"""Abstract job queue interface and job management."""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class JobStatus(Enum):
    """Job execution status."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobSpec:
    """Specification for a job to be submitted."""

    name: str
    tool_name: str  # shypre, shybas, shyparts, shyfem, shyelab, shyplot
    args: list[str]
    working_dir: Path
    simulation_id: int | None = None
    mpi_enabled: bool = False
    mpi_np: int = 1
    env: dict[str, str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobInfo:
    """Information about a job."""

    id: str
    name: str
    tool_name: str
    args: list[str]
    working_dir: str
    status: JobStatus
    progress: float = 0.0
    progress_message: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    return_code: int | None = None
    error_message: str | None = None
    stdout_file: str | None = None
    stderr_file: str | None = None
    output_files: list[str] = field(default_factory=list)
    simulation_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Check if job is currently active."""
        return self.status in (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)

    @property
    def duration(self) -> float | None:
        """Calculate job duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class JobQueue(ABC):
    """Abstract base class for job queues."""

    @abstractmethod
    async def submit(self, spec: JobSpec) -> str:
        """Submit a job and return job ID."""
        pass

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Cancel a job. Returns True if successful."""
        pass

    @abstractmethod
    async def get_status(self, job_id: str) -> JobInfo | None:
        """Get current status of a job."""
        pass

    @abstractmethod
    async def list_jobs(
        self,
        status: JobStatus | None = None,
        simulation_id: int | None = None,
        limit: int = 100,
        session_id: str | None = None,
    ) -> list[JobInfo]:
        """List jobs, optionally filtered by status, simulation, or session."""
        pass

    @abstractmethod
    async def get_output(self, job_id: str, stream: str = "stdout", tail: int = 100) -> str:
        """Get job output (stdout or stderr), optionally limited to last N lines."""
        pass

    @abstractmethod
    def set_progress_callback(self, callback: Callable[[str, float, str], None]) -> None:
        """Set callback for progress updates: callback(job_id, progress, message).

        Deprecated: Use add_progress_callback/remove_progress_callback for
        multi-session support.  This still works but overwrites all previous
        callbacks registered via add_progress_callback.
        """
        pass

    def add_progress_callback(
        self,
        callback_id: str,
        callback: Callable[[str, float, str], None],
    ) -> None:
        """Register a named progress callback (multi-session safe).

        Args:
            callback_id: Unique identifier (e.g. session id).
            callback: Called with (job_id, progress, message).
        """
        if not hasattr(self, "_progress_callbacks"):
            self._progress_callbacks: dict[str, Callable[[str, float, str], None]] = {}
        self._progress_callbacks[callback_id] = callback

    def remove_progress_callback(self, callback_id: str) -> None:
        """Remove a previously registered progress callback."""
        if hasattr(self, "_progress_callbacks"):
            self._progress_callbacks.pop(callback_id, None)

    def _notify_progress(self, job_id: str, progress: float, message: str) -> None:
        """Invoke all registered progress callbacks."""
        if hasattr(self, "_progress_callbacks"):
            for cb in list(self._progress_callbacks.values()):
                try:
                    cb(job_id, progress, message)
                except Exception:
                    pass

    @abstractmethod
    async def cleanup_old_jobs(self, days: int = 7) -> int:
        """Remove jobs older than N days. Returns count removed."""
        pass

    @staticmethod
    def generate_job_id() -> str:
        """Generate a unique job ID."""
        return str(uuid.uuid4())


class JobQueueFactory:
    """Factory for creating job queue instances."""

    @staticmethod
    def create(
        mode: str = "local",
        shyfem_dir: Path | None = None,
        max_workers: int = 4,
        redis_url: str | None = None,
        notification_service=None,
    ) -> JobQueue:
        """Create a job queue instance.

        Args:
            mode: "local" or "celery"
            shyfem_dir: Path to SHYFEM installation
            max_workers: Max concurrent jobs (local mode)
            redis_url: Redis URL (celery mode)
            notification_service: Optional NotificationService for job completion emails
        """
        if mode == "local":
            from shyfem_ui.services.job_local import LocalJobQueue

            return LocalJobQueue(
                shyfem_dir=shyfem_dir,
                max_workers=max_workers,
                notification_service=notification_service,
            )
        elif mode == "celery":
            from shyfem_ui.services.job_celery import CeleryJobQueue

            return CeleryJobQueue(shyfem_dir=shyfem_dir, redis_url=redis_url)
        else:
            raise ValueError(f"Unknown job queue mode: {mode}")
