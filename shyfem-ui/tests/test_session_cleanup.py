"""Tests for session cleanup callback logic (app.py:387-396).

The _on_session_ended callback is a closure inside _build_server, so we
replicate its logic in a standalone async function and test the behavioral
pattern with mocked dependencies.
"""

from unittest.mock import AsyncMock, MagicMock, call

import pytest


async def session_cleanup(job_queue, logger):
    """Replicate _on_session_ended callback logic from app.py:387-396."""
    try:
        jobs = await job_queue.list_jobs(limit=100)
        for job in jobs:
            if job.is_active:
                logger.info("Session ended — cancelling orphaned job %s", job.id)
                await job_queue.cancel(job.id)
    except Exception as exc:
        logger.warning("Session cleanup failed: %s", exc)


def _make_job(job_id, is_active):
    """Create a mock job object with id and is_active attributes."""
    job = MagicMock()
    job.id = job_id
    job.is_active = is_active
    return job


@pytest.fixture
def mock_job_queue():
    """Create a mock job queue with async list_jobs and cancel."""
    q = MagicMock()
    q.list_jobs = AsyncMock(return_value=[])
    q.cancel = AsyncMock()
    return q


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    return MagicMock()


class TestSessionCleanup:
    """Tests for the session cleanup callback pattern."""

    @pytest.mark.asyncio
    async def test_active_jobs_are_cancelled(self, mock_job_queue, mock_logger):
        """Active jobs are cancelled on session end."""
        job_a = _make_job("job-1", is_active=True)
        job_b = _make_job("job-2", is_active=True)
        mock_job_queue.list_jobs.return_value = [job_a, job_b]

        await session_cleanup(mock_job_queue, mock_logger)

        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100)
        assert mock_job_queue.cancel.await_count == 2
        mock_job_queue.cancel.assert_any_await("job-1")
        mock_job_queue.cancel.assert_any_await("job-2")
        assert mock_logger.info.call_count == 2

    @pytest.mark.asyncio
    async def test_inactive_jobs_not_cancelled(self, mock_job_queue, mock_logger):
        """Inactive/completed jobs are not cancelled."""
        job = _make_job("done-1", is_active=False)
        mock_job_queue.list_jobs.return_value = [job]

        await session_cleanup(mock_job_queue, mock_logger)

        mock_job_queue.cancel.assert_not_awaited()
        mock_logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_jobs_only_active_cancelled(self, mock_job_queue, mock_logger):
        """Only active jobs from a mixed list are cancelled."""
        active = _make_job("active-1", is_active=True)
        done = _make_job("done-1", is_active=False)
        queued = _make_job("active-2", is_active=True)
        completed = _make_job("done-2", is_active=False)
        mock_job_queue.list_jobs.return_value = [active, done, queued, completed]

        await session_cleanup(mock_job_queue, mock_logger)

        assert mock_job_queue.cancel.await_count == 2
        mock_job_queue.cancel.assert_any_await("active-1")
        mock_job_queue.cancel.assert_any_await("active-2")
        # Ensure completed jobs were NOT cancelled
        cancelled_ids = [c.args[0] for c in mock_job_queue.cancel.await_args_list]
        assert "done-1" not in cancelled_ids
        assert "done-2" not in cancelled_ids

    @pytest.mark.asyncio
    async def test_empty_job_list_no_cancellations(self, mock_job_queue, mock_logger):
        """Empty job list results in no cancellation calls."""
        mock_job_queue.list_jobs.return_value = []

        await session_cleanup(mock_job_queue, mock_logger)

        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100)
        mock_job_queue.cancel.assert_not_awaited()
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_jobs_exception_logged_as_warning(
        self, mock_job_queue, mock_logger
    ):
        """Exceptions in list_jobs are logged as warning, not raised."""
        mock_job_queue.list_jobs.side_effect = RuntimeError("connection lost")

        # Should not raise
        await session_cleanup(mock_job_queue, mock_logger)

        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "Session cleanup failed" in warning_msg
        mock_job_queue.cancel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_exception_logged_as_warning(
        self, mock_job_queue, mock_logger
    ):
        """If cancelling one job raises, the outer try/except catches it."""
        job = _make_job("fail-1", is_active=True)
        mock_job_queue.list_jobs.return_value = [job]
        mock_job_queue.cancel.side_effect = OSError("cancel failed")

        # Should not raise
        await session_cleanup(mock_job_queue, mock_logger)

        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "Session cleanup failed" in warning_msg


async def session_cleanup_filtered(job_queue, session_id, is_server_mode, logger):
    """Replicate updated _on_session_ended with session filtering."""
    try:
        sid = session_id if is_server_mode else None
        jobs = await job_queue.list_jobs(limit=100, session_id=sid)
        for job in jobs:
            if job.is_active:
                logger.info("Session ended — cancelling orphaned job %s", job.id)
                await job_queue.cancel(job.id)
    except Exception as exc:
        logger.warning("Session cleanup failed: %s", exc)


class TestSessionCleanupFiltered:
    """Tests for session-filtered cleanup (server mode)."""

    @pytest.mark.asyncio
    async def test_server_mode_passes_session_id(self, mock_job_queue, mock_logger):
        """In server mode, list_jobs is called with session_id."""
        mock_job_queue.list_jobs.return_value = []
        await session_cleanup_filtered(
            mock_job_queue, "sess-123", is_server_mode=True, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id="sess-123")

    @pytest.mark.asyncio
    async def test_local_mode_no_session_filter(self, mock_job_queue, mock_logger):
        """In local mode, list_jobs is called without session_id."""
        mock_job_queue.list_jobs.return_value = []
        await session_cleanup_filtered(
            mock_job_queue, "sess-123", is_server_mode=False, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id=None)

    @pytest.mark.asyncio
    async def test_server_mode_cancels_only_session_jobs(
        self, mock_job_queue, mock_logger
    ):
        """In server mode, only active jobs from list_jobs (already filtered) are cancelled."""
        active = _make_job("mine-1", is_active=True)
        done = _make_job("mine-2", is_active=False)
        mock_job_queue.list_jobs.return_value = [active, done]

        await session_cleanup_filtered(
            mock_job_queue, "sess-456", is_server_mode=True, logger=mock_logger
        )

        mock_job_queue.cancel.assert_awaited_once_with("mine-1")
