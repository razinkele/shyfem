"""Tests for the JobQueue abstract base class and factory."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from shyfem_ui.services.job_queue import (
    JobInfo,
    JobQueue,
    JobQueueFactory,
    JobSpec,
    JobStatus,
)


def _make_job_info(**overrides) -> JobInfo:
    """Build a valid JobInfo for tests; defaults are minimal but legal."""
    base = dict(
        id="x",
        name="t",
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=JobStatus.PENDING,
    )
    base.update(overrides)
    return JobInfo(**base)


class TestJobInfo:

    def test_is_active_pending(self):
        """PENDING is active."""
        assert _make_job_info(status=JobStatus.PENDING).is_active

    def test_is_active_queued(self):
        """QUEUED is active."""
        assert _make_job_info(status=JobStatus.QUEUED).is_active

    def test_is_active_running(self):
        """RUNNING is active."""
        assert _make_job_info(status=JobStatus.RUNNING).is_active

    def test_is_active_completed_false(self):
        """COMPLETED is terminal, not active."""
        assert not _make_job_info(status=JobStatus.COMPLETED).is_active

    def test_is_active_failed_false(self):
        """FAILED is terminal, not active."""
        assert not _make_job_info(status=JobStatus.FAILED).is_active

    def test_duration_completed(self):
        """duration returns elapsed seconds for completed jobs."""
        start = datetime.now() - timedelta(seconds=10)
        end = datetime.now()
        info = _make_job_info(
            status=JobStatus.COMPLETED,
            started_at=start,
            completed_at=end,
        )
        assert info.duration is not None
        assert abs(info.duration - 10.0) < 0.5

    def test_duration_no_start_returns_none(self):
        """A pending job that never started has no duration."""
        info = _make_job_info(status=JobStatus.PENDING)
        assert info.duration is None


class _StubQueue(JobQueue):
    """Minimal concrete subclass for testing base-class methods.

    The real JobQueue ABC declares 7 abstract methods (verified at
    services/job_queue.py:80-153). All 7 MUST be implemented or
    instantiation raises TypeError. cleanup_old_jobs MUST be async.
    """

    async def submit(self, spec: JobSpec) -> str:
        return "stub-job-id"

    async def cancel(self, job_id: str) -> bool:
        return True

    async def get_status(self, job_id: str) -> JobInfo | None:
        return None

    async def list_jobs(
        self,
        status: JobStatus | None = None,
        simulation_id: int | None = None,
        limit: int = 100,
        session_id: str | None = None,
        user_id: int | None = None,
    ) -> list[JobInfo]:
        return []

    async def get_output(
        self,
        job_id: str,
        stream: str = "stdout",
        tail: int = 100,
    ) -> str:
        return ""

    async def cleanup_old_jobs(self, days: int = 7) -> int:
        # MUST be async — ABC declares async; sync override would TypeError
        # when awaited at runtime (sync ints can't be awaited).
        return 0


class TestProgressCallbacks:

    def test_add_and_notify(self):
        """A registered callback fires when _notify_progress is called."""
        q = _StubQueue()
        cb = MagicMock()
        q.add_progress_callback("session-1", cb)
        q._notify_progress("job1", 50.0, "halfway")
        cb.assert_called_once_with("job1", 50.0, "halfway")

    def test_remove_callback(self):
        """A removed callback no longer fires."""
        q = _StubQueue()
        cb = MagicMock()
        q.add_progress_callback("session-1", cb)
        q.remove_progress_callback("session-1")
        q._notify_progress("job1", 50.0, "halfway")
        cb.assert_not_called()

    def test_remove_unknown_id_is_noop(self):
        """remove_progress_callback for an unregistered id must not raise."""
        q = _StubQueue()
        q.remove_progress_callback("never-added")  # must not raise

    def test_multiple_callbacks_routed_to_all(self):
        """Multiple registered callbacks all fire on a single notify."""
        q = _StubQueue()
        cb_a = MagicMock()
        cb_b = MagicMock()
        q.add_progress_callback("a", cb_a)
        q.add_progress_callback("b", cb_b)
        q._notify_progress("job1", 25.0, "quarter")
        cb_a.assert_called_once()
        cb_b.assert_called_once()


class TestGenerateJobId:

    def test_unique_per_call(self):
        """Each call returns a unique ID."""
        ids = {JobQueue.generate_job_id() for _ in range(50)}
        assert len(ids) == 50

    def test_format(self):
        """The ID is a non-empty str (UUID4 form is 36 chars)."""
        jid = JobQueue.generate_job_id()
        assert isinstance(jid, str) and len(jid) >= 8


class TestJobQueueFactory:

    def test_create_local(self, tmp_path):
        """Factory dispatches to LocalJobQueue for mode='local'."""
        q = JobQueueFactory.create(mode="local", shyfem_dir=tmp_path)
        from shyfem_ui.services.job_local import LocalJobQueue

        assert isinstance(q, LocalJobQueue)

    def test_create_celery(self, tmp_path):
        """Factory dispatches to CeleryJobQueue for mode='celery'."""
        with patch("shyfem_ui.services.job_celery.get_celery_app"):
            q = JobQueueFactory.create(
                mode="celery",
                shyfem_dir=tmp_path,
                redis_url="redis://localhost:6379/0",
            )
        from shyfem_ui.services.job_celery import CeleryJobQueue

        assert isinstance(q, CeleryJobQueue)

    def test_create_unknown_mode_raises(self):
        """Unknown mode raises ValueError."""
        with pytest.raises(ValueError, match="mode"):
            JobQueueFactory.create(mode="quantum-tunnel")


class TestEventCallbacks:
    """Job events: the push counterpart of the progress callbacks (Shiny 1.9
    sessions subscribe instead of polling)."""

    @staticmethod
    def _event(**overrides):
        from shyfem_ui.services import job_queue as jq

        fields = dict(
            job_id="job1",
            name="sim",
            status=JobStatus.RUNNING,
            previous=JobStatus.QUEUED,
            user_id=None,
            project_id=None,
        )
        fields.update(overrides)
        return jq.JobEvent(**fields)

    def test_supports_events_is_off_by_default(self):
        assert _StubQueue().supports_events is False

    def test_add_and_notify(self):
        q = _StubQueue()
        cb = MagicMock()
        q.add_event_callback("session-1", cb)
        ev = self._event()
        q._notify_event(ev)
        cb.assert_called_once_with(ev)

    def test_remove_callback(self):
        q = _StubQueue()
        cb = MagicMock()
        q.add_event_callback("session-1", cb)
        q.remove_event_callback("session-1")
        q._notify_event(self._event())
        cb.assert_not_called()

    def test_remove_unknown_id_is_noop(self):
        _StubQueue().remove_event_callback("never-added")

    def test_a_failing_callback_does_not_stop_the_others(self):
        q = _StubQueue()
        cb_a = MagicMock(side_effect=RuntimeError("boom"))
        cb_b = MagicMock()
        q.add_event_callback("a", cb_a)
        q.add_event_callback("b", cb_b)
        q._notify_event(self._event())
        cb_b.assert_called_once()

    def test_an_event_knows_whether_it_is_terminal(self):
        assert self._event(status=JobStatus.COMPLETED).is_terminal
        assert not self._event(status=JobStatus.RUNNING).is_terminal
