"""Tests for the session-end job-cleanup logic.

Exercises the REAL helper that app.py's _on_session_ended delegates to
(shyfem_ui.services.job_queue.cancel_active_jobs_for_session), not a
re-implemented copy — so these fail if the actual cleanup behaviour (session
filtering, active-only cancellation, swallowing errors) regresses.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from shyfem_ui.services.job_queue import cancel_active_jobs_for_session


def _make_job(job_id, is_active):
    job = MagicMock()
    job.id = job_id
    job.is_active = is_active
    return job


@pytest.fixture
def mock_job_queue():
    q = MagicMock()
    q.list_jobs = AsyncMock(return_value=[])
    q.cancel = AsyncMock()
    return q


@pytest.fixture
def mock_logger():
    return MagicMock()


class TestSessionCleanup:
    """Active-only cancellation and error handling (local mode: session_id=None)."""

    @pytest.mark.asyncio
    async def test_active_jobs_are_cancelled(self, mock_job_queue, mock_logger):
        mock_job_queue.list_jobs.return_value = [
            _make_job("job-1", is_active=True),
            _make_job("job-2", is_active=True),
        ]
        await cancel_active_jobs_for_session(
            mock_job_queue, "sess", is_server_mode=False, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id=None)
        assert mock_job_queue.cancel.await_count == 2
        mock_job_queue.cancel.assert_any_await("job-1")
        mock_job_queue.cancel.assert_any_await("job-2")
        assert mock_logger.info.call_count == 2

    @pytest.mark.asyncio
    async def test_inactive_jobs_not_cancelled(self, mock_job_queue, mock_logger):
        mock_job_queue.list_jobs.return_value = [_make_job("done-1", is_active=False)]
        await cancel_active_jobs_for_session(
            mock_job_queue, "sess", is_server_mode=False, logger=mock_logger
        )
        mock_job_queue.cancel.assert_not_awaited()
        mock_logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_jobs_only_active_cancelled(self, mock_job_queue, mock_logger):
        mock_job_queue.list_jobs.return_value = [
            _make_job("active-1", is_active=True),
            _make_job("done-1", is_active=False),
            _make_job("active-2", is_active=True),
            _make_job("done-2", is_active=False),
        ]
        await cancel_active_jobs_for_session(
            mock_job_queue, "sess", is_server_mode=False, logger=mock_logger
        )
        assert mock_job_queue.cancel.await_count == 2
        cancelled_ids = [c.args[0] for c in mock_job_queue.cancel.await_args_list]
        assert cancelled_ids == ["active-1", "active-2"]
        assert "done-1" not in cancelled_ids
        assert "done-2" not in cancelled_ids

    @pytest.mark.asyncio
    async def test_empty_job_list_no_cancellations(self, mock_job_queue, mock_logger):
        mock_job_queue.list_jobs.return_value = []
        await cancel_active_jobs_for_session(
            mock_job_queue, "sess", is_server_mode=False, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id=None)
        mock_job_queue.cancel.assert_not_awaited()
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_jobs_exception_logged_as_warning(self, mock_job_queue, mock_logger):
        mock_job_queue.list_jobs.side_effect = RuntimeError("connection lost")
        await cancel_active_jobs_for_session(  # must not raise
            mock_job_queue, "sess", is_server_mode=False, logger=mock_logger
        )
        mock_logger.warning.assert_called_once()
        assert "Session cleanup failed" in mock_logger.warning.call_args[0][0]
        mock_job_queue.cancel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_exception_logged_as_warning(self, mock_job_queue, mock_logger):
        mock_job_queue.list_jobs.return_value = [_make_job("fail-1", is_active=True)]
        mock_job_queue.cancel.side_effect = OSError("cancel failed")
        await cancel_active_jobs_for_session(  # must not raise
            mock_job_queue, "sess", is_server_mode=True, logger=mock_logger
        )
        mock_logger.warning.assert_called_once()
        assert "Session cleanup failed" in mock_logger.warning.call_args[0][0]


class TestSessionCleanupFiltering:
    """The session-id passed to list_jobs depends on deployment mode."""

    @pytest.mark.asyncio
    async def test_server_mode_passes_session_id(self, mock_job_queue, mock_logger):
        await cancel_active_jobs_for_session(
            mock_job_queue, "sess-123", is_server_mode=True, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id="sess-123")

    @pytest.mark.asyncio
    async def test_local_mode_no_session_filter(self, mock_job_queue, mock_logger):
        await cancel_active_jobs_for_session(
            mock_job_queue, "sess-123", is_server_mode=False, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id=None)
