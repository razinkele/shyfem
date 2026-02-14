"""Tests for CeleryJobQueue health_check/worker_info with mocked Redis/Celery."""

from unittest.mock import MagicMock, patch

import pytest

from shyfem_ui.services.job_celery import CeleryJobQueue


@pytest.fixture
def queue():
    """Create a CeleryJobQueue with test config."""
    return CeleryJobQueue(
        shyfem_dir="/tmp/shyfem",
        redis_url="redis://localhost:6379/0",
    )


class TestHealthCheck:
    """Tests for CeleryJobQueue.health_check()."""

    @pytest.mark.asyncio
    async def test_redis_down(self, queue):
        """health_check returns redis_connected=False when Redis is unavailable."""
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = ConnectionError("Connection refused")

        with patch.object(queue, "_get_redis_client", return_value=mock_redis):
            result = await queue.health_check()

        assert result["redis_connected"] is False
        assert result["workers"] == []

    @pytest.mark.asyncio
    async def test_redis_up_no_workers(self, queue):
        """health_check with Redis up but no Celery workers."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True

        mock_inspect = MagicMock()
        mock_inspect.ping.return_value = None
        mock_inspect.active.return_value = None
        mock_inspect.scheduled.return_value = None
        mock_inspect.reserved.return_value = None

        mock_app = MagicMock()
        mock_app.control.inspect.return_value = mock_inspect

        with (
            patch.object(queue, "_get_redis_client", return_value=mock_redis),
            patch.object(queue, "_get_celery_app", return_value=mock_app),
        ):
            result = await queue.health_check()

        assert result["redis_connected"] is True
        assert result["workers"] == []
        assert result["active_tasks"] == 0

    @pytest.mark.asyncio
    async def test_redis_up_with_workers(self, queue):
        """health_check with active workers and tasks."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True

        mock_inspect = MagicMock()
        mock_inspect.ping.return_value = {"worker1@host": {"ok": "pong"}}
        mock_inspect.active.return_value = {"worker1@host": [{"id": "t1"}, {"id": "t2"}]}
        mock_inspect.scheduled.return_value = {"worker1@host": [{"id": "t3"}]}
        mock_inspect.reserved.return_value = None

        mock_app = MagicMock()
        mock_app.control.inspect.return_value = mock_inspect

        with (
            patch.object(queue, "_get_redis_client", return_value=mock_redis),
            patch.object(queue, "_get_celery_app", return_value=mock_app),
        ):
            result = await queue.health_check()

        assert result["redis_connected"] is True
        assert "worker1@host" in result["workers"]
        assert result["active_tasks"] == 2
        assert result["scheduled_tasks"] == 1
        assert result["reserved_tasks"] == 0


class TestWorkerInfo:
    """Tests for CeleryJobQueue.worker_info()."""

    @pytest.mark.asyncio
    async def test_no_workers(self, queue):
        """worker_info returns empty list when no workers."""
        mock_app = MagicMock()
        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = None
        mock_app.control.inspect.return_value = mock_inspect

        with patch.object(queue, "_get_celery_app", return_value=mock_app):
            result = await queue.worker_info()

        assert result == []

    @pytest.mark.asyncio
    async def test_with_worker_stats(self, queue):
        """worker_info returns structured worker data."""
        mock_app = MagicMock()
        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = {
            "worker1@host": {
                "pool": {
                    "max-concurrency": 4,
                    "implementation": "prefork",
                },
                "total": {"shyfem_ui.execute_job": 15},
                "pid": 1234,
            }
        }
        mock_inspect.active.return_value = {
            "worker1@host": [{"id": "t1"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        with patch.object(queue, "_get_celery_app", return_value=mock_app):
            result = await queue.worker_info()

        assert len(result) == 1
        worker = result[0]
        assert worker["name"] == "worker1@host"
        assert worker["active_tasks"] == 1
        assert worker["processed"] == 15
        assert worker["concurrency"] == 4
        assert worker["pool"] == "prefork"
        assert worker["pid"] == 1234
