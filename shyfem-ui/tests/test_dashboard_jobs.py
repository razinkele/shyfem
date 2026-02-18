"""Tests for Dashboard recent jobs session filtering."""

from unittest.mock import AsyncMock, MagicMock

import pytest


async def dashboard_refresh_jobs(job_queue, session_id, is_server_mode):
    """Replicate Dashboard _refresh_jobs with session filtering."""
    sid = session_id if is_server_mode else None
    return await job_queue.list_jobs(limit=5, session_id=sid)


class TestDashboardJobFiltering:
    """Dashboard recent jobs should filter by session in server mode."""

    @pytest.mark.asyncio
    async def test_server_mode_filters_by_session(self):
        q = MagicMock()
        q.list_jobs = AsyncMock(return_value=[])
        await dashboard_refresh_jobs(q, "sess-abc", is_server_mode=True)
        q.list_jobs.assert_awaited_once_with(limit=5, session_id="sess-abc")

    @pytest.mark.asyncio
    async def test_local_mode_no_filter(self):
        q = MagicMock()
        q.list_jobs = AsyncMock(return_value=[])
        await dashboard_refresh_jobs(q, "sess-abc", is_server_mode=False)
        q.list_jobs.assert_awaited_once_with(limit=5, session_id=None)
