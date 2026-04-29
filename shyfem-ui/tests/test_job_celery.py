"""Tests for CeleryJobQueue using mocked Redis and Celery."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from shyfem_ui.services.job_celery import (
    CeleryJobQueue,
    _load_job_info,
    _store_job_info,
)
from shyfem_ui.services.job_queue import JobInfo, JobSpec, JobStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job_info(job_id="job-1", status=JobStatus.PENDING, **kwargs):
    """Create a JobInfo with sensible defaults for testing."""
    defaults = dict(
        id=job_id,
        name="test_job",
        tool_name="shyfem",
        args=["input.str"],
        working_dir="/tmp/work",
        status=status,
        created_at=datetime(2026, 2, 19, 12, 0, 0),
        metadata={},
    )
    defaults.update(kwargs)
    return JobInfo(**defaults)


def _job_info_to_json(job_info):
    """Serialize a JobInfo to JSON string (mimics what _store_job_info writes to Redis)."""
    return json.dumps(
        {
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
            "completed_at": job_info.completed_at.isoformat()
            if job_info.completed_at
            else None,
            "return_code": job_info.return_code,
            "error_message": job_info.error_message,
            "stdout_file": job_info.stdout_file,
            "stderr_file": job_info.stderr_file,
            "output_files": job_info.output_files,
            "simulation_id": job_info.simulation_id,
            "metadata": job_info.metadata,
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """A MagicMock standing in for a Redis client."""
    rc = MagicMock()
    rc.ping.return_value = True
    return rc


@pytest.fixture
def mock_task():
    """A MagicMock standing in for a Celery task."""
    task = MagicMock()
    task.apply_async.return_value = MagicMock(id="celery-task-1")
    return task


@pytest.fixture
def mock_celery_app():
    """A MagicMock standing in for the Celery application."""
    app = MagicMock()
    app.control.revoke = MagicMock()
    return app


@pytest.fixture
def queue(tmp_path, mock_redis, mock_celery_app, mock_task):
    """Create a CeleryJobQueue with all external deps mocked out."""
    q = CeleryJobQueue(shyfem_dir=tmp_path, redis_url="redis://fake:6379/0")
    q._redis_client = mock_redis
    q._celery_app = mock_celery_app
    q._task = mock_task
    return q


@pytest.fixture
def job_spec(tmp_path):
    """Create a basic JobSpec for testing."""
    return JobSpec(
        name="test_job",
        tool_name="shyfem",
        args=["input.str"],
        working_dir=tmp_path / "work",
    )


# ---------------------------------------------------------------------------
# TestRedisHelpers
# ---------------------------------------------------------------------------


class TestRedisHelpers:
    """Tests for the module-level _store_job_info and _load_job_info helpers."""

    def test_store_job_info_calls_hset_and_zadd(self, mock_redis):
        """_store_job_info should call hset on the hash and zadd on the sorted set."""
        info = _make_job_info()
        _store_job_info(mock_redis, info)

        mock_redis.hset.assert_called_once()
        args = mock_redis.hset.call_args
        assert args[0][0] == "shyfem:jobs"
        assert args[0][1] == "job-1"

        mock_redis.zadd.assert_called_once()
        zadd_args = mock_redis.zadd.call_args
        assert zadd_args[0][0] == "shyfem:jobs:by_time"

    def test_load_job_info_returns_job_when_data_exists(self, mock_redis):
        """_load_job_info should reconstruct a JobInfo from stored JSON."""
        info = _make_job_info(status=JobStatus.RUNNING)
        mock_redis.hget.return_value = _job_info_to_json(info)

        result = _load_job_info(mock_redis, "job-1")
        assert result is not None
        assert result.id == "job-1"
        assert result.status == JobStatus.RUNNING
        assert result.tool_name == "shyfem"

    def test_load_job_info_returns_none_when_missing(self, mock_redis):
        """_load_job_info should return None when the key does not exist."""
        mock_redis.hget.return_value = None

        result = _load_job_info(mock_redis, "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# TestCelerySubmit
# ---------------------------------------------------------------------------


class TestCelerySubmit:
    """Tests for CeleryJobQueue.submit()."""

    async def test_submit_returns_nonempty_job_id(self, queue, job_spec):
        """submit() should return a non-empty string job ID."""
        job_id = await queue.submit(job_spec)
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    async def test_submit_dispatches_celery_task(self, queue, job_spec, mock_task):
        """submit() should call task.apply_async with the job's arguments."""
        job_id = await queue.submit(job_spec)
        mock_task.apply_async.assert_called_once()
        call_kwargs = mock_task.apply_async.call_args
        assert call_kwargs[1]["task_id"] == job_id

    async def test_submit_stores_in_redis(self, queue, job_spec, mock_redis):
        """submit() should call hset twice (PENDING, then QUEUED)."""
        await queue.submit(job_spec)
        assert mock_redis.hset.call_count == 2

    async def test_submit_mpi_metadata(self, queue, tmp_path, mock_redis):
        """When mpi_enabled=True, metadata should contain mpi settings."""
        spec = JobSpec(
            name="mpi_job",
            tool_name="shyfem",
            args=["test.str"],
            working_dir=tmp_path / "w",
            mpi_enabled=True,
            mpi_np=4,
        )
        await queue.submit(spec)

        # The second hset call contains the QUEUED state; inspect the stored JSON
        last_hset_call = mock_redis.hset.call_args_list[-1]
        stored_json = json.loads(last_hset_call[0][2])
        assert stored_json["metadata"]["mpi_enabled"] is True
        assert stored_json["metadata"]["mpi_np"] == 4


# ---------------------------------------------------------------------------
# TestCeleryCancel
# ---------------------------------------------------------------------------


class TestCeleryCancel:
    """Tests for CeleryJobQueue.cancel()."""

    async def test_cancel_active_job(self, queue, mock_redis, mock_celery_app):
        """Cancelling an active job should return True and call revoke."""
        info = _make_job_info(status=JobStatus.RUNNING)
        mock_redis.hget.return_value = _job_info_to_json(info)

        result = await queue.cancel("job-1")
        assert result is True
        mock_celery_app.control.revoke.assert_called_once_with("job-1", terminate=True)

    async def test_cancel_completed_job(self, queue, mock_redis):
        """Cancelling a completed job should return False."""
        info = _make_job_info(status=JobStatus.COMPLETED)
        mock_redis.hget.return_value = _job_info_to_json(info)

        result = await queue.cancel("job-1")
        assert result is False

    async def test_cancel_nonexistent_job(self, queue, mock_redis):
        """Cancelling a nonexistent job should return False."""
        mock_redis.hget.return_value = None

        result = await queue.cancel("no-such-job")
        assert result is False


# ---------------------------------------------------------------------------
# TestCeleryGetStatus
# ---------------------------------------------------------------------------


class TestCeleryGetStatus:
    """Tests for CeleryJobQueue.get_status()."""

    async def test_get_status_existing(self, queue, mock_redis):
        """get_status() should return JobInfo with correct status."""
        info = _make_job_info(status=JobStatus.QUEUED)
        mock_redis.hget.return_value = _job_info_to_json(info)

        result = await queue.get_status("job-1")
        assert result is not None
        assert result.id == "job-1"
        assert result.status == JobStatus.QUEUED

    async def test_get_status_nonexistent(self, queue, mock_redis):
        """get_status() should return None for an unknown job."""
        mock_redis.hget.return_value = None

        result = await queue.get_status("missing")
        assert result is None


# ---------------------------------------------------------------------------
# TestCeleryListJobs
# ---------------------------------------------------------------------------


class TestCeleryListJobs:
    """Tests for CeleryJobQueue.list_jobs()."""

    async def test_list_jobs_empty(self, queue, mock_redis):
        """list_jobs() should return [] when there are no jobs."""
        mock_redis.zrevrange.return_value = []

        jobs = await queue.list_jobs()
        assert jobs == []

    async def test_list_jobs_multiple(self, queue, mock_redis):
        """list_jobs() should return all stored jobs."""
        info1 = _make_job_info(job_id="job-1", status=JobStatus.COMPLETED)
        info2 = _make_job_info(job_id="job-2", status=JobStatus.RUNNING)

        mock_redis.zrevrange.return_value = [b"job-1", b"job-2"]
        mock_redis.hget.side_effect = lambda key, jid: {
            "job-1": _job_info_to_json(info1),
            "job-2": _job_info_to_json(info2),
        }.get(jid)

        jobs = await queue.list_jobs()
        assert len(jobs) == 2
        assert {j.id for j in jobs} == {"job-1", "job-2"}

    async def test_list_jobs_filter_by_status(self, queue, mock_redis):
        """list_jobs(status=...) should only return matching jobs."""
        info1 = _make_job_info(job_id="job-1", status=JobStatus.COMPLETED)
        info2 = _make_job_info(job_id="job-2", status=JobStatus.RUNNING)

        mock_redis.zrevrange.return_value = [b"job-1", b"job-2"]
        mock_redis.hget.side_effect = lambda key, jid: {
            "job-1": _job_info_to_json(info1),
            "job-2": _job_info_to_json(info2),
        }.get(jid)

        jobs = await queue.list_jobs(status=JobStatus.RUNNING)
        assert len(jobs) == 1
        assert jobs[0].id == "job-2"

    async def test_list_jobs_filter_by_session_id(self, queue, mock_redis):
        """list_jobs(session_id=...) should only return matching jobs."""
        info1 = _make_job_info(
            job_id="job-1", metadata={"session_id": "sess-A"}
        )
        info2 = _make_job_info(
            job_id="job-2", metadata={"session_id": "sess-B"}
        )

        mock_redis.zrevrange.return_value = [b"job-1", b"job-2"]
        mock_redis.hget.side_effect = lambda key, jid: {
            "job-1": _job_info_to_json(info1),
            "job-2": _job_info_to_json(info2),
        }.get(jid)

        jobs = await queue.list_jobs(session_id="sess-A")
        assert len(jobs) == 1
        assert jobs[0].id == "job-1"

    async def test_list_jobs_respects_limit(self, queue, mock_redis):
        """list_jobs(limit=N) should return at most N jobs."""
        infos = {
            f"job-{i}": _make_job_info(job_id=f"job-{i}")
            for i in range(5)
        }

        mock_redis.zrevrange.return_value = [
            f"job-{i}".encode() for i in range(5)
        ]
        mock_redis.hget.side_effect = lambda key, jid: _job_info_to_json(
            infos[jid]
        )

        jobs = await queue.list_jobs(limit=2)
        assert len(jobs) == 2


# ---------------------------------------------------------------------------
# TestCeleryGetOutput
# ---------------------------------------------------------------------------


class TestCeleryGetOutput:
    """Tests for CeleryJobQueue.get_output()."""

    async def test_get_output_nonexistent_job(self, queue, mock_redis):
        """get_output() for a nonexistent job should return empty string."""
        mock_redis.hget.return_value = None

        result = await queue.get_output("no-such-job")
        assert result == ""

    async def test_get_output_no_output_file(self, queue, mock_redis):
        """get_output() when no stdout_file is set should return empty string."""
        info = _make_job_info(stdout_file=None, stderr_file=None)
        mock_redis.hget.return_value = _job_info_to_json(info)

        result = await queue.get_output("job-1")
        assert result == ""

    @patch("shyfem_ui.services.file_utils.tail_file")
    async def test_get_output_with_file(self, mock_tail, queue, mock_redis):
        """get_output() should call tail_file when stdout_file is set."""
        mock_tail.return_value = "line 1\nline 2\n"

        info = _make_job_info(stdout_file="/tmp/work/job-1.stdout")
        mock_redis.hget.return_value = _job_info_to_json(info)

        result = await queue.get_output("job-1", stream="stdout", tail=50)
        assert result == "line 1\nline 2\n"
        mock_tail.assert_called_once_with("/tmp/work/job-1.stdout", tail=50)


# ---------------------------------------------------------------------------
# TestCeleryHealthCheck
# ---------------------------------------------------------------------------


class TestCeleryHealthCheck:
    """Tests for CeleryJobQueue.health_check()."""

    async def test_health_check_all_ok(self, queue, mock_redis, mock_celery_app):
        """health_check() with healthy Redis and workers should return populated result."""
        inspect_mock = MagicMock()
        inspect_mock.ping.return_value = {
            "worker-1@host": {"ok": "pong"},
            "worker-2@host": {"ok": "pong"},
        }
        inspect_mock.active.return_value = {
            "worker-1@host": [{"id": "t1"}, {"id": "t2"}],
            "worker-2@host": [{"id": "t3"}],
        }
        inspect_mock.scheduled.return_value = {"worker-1@host": []}
        inspect_mock.reserved.return_value = {"worker-1@host": [{"id": "r1"}]}
        mock_celery_app.control.inspect.return_value = inspect_mock

        result = await queue.health_check()
        assert result["redis_connected"] is True
        assert len(result["workers"]) == 2
        assert result["active_tasks"] == 3
        assert result["reserved_tasks"] == 1

    async def test_health_check_redis_down(self, queue, mock_redis):
        """health_check() when Redis is down should return redis_connected=False."""
        mock_redis.ping.side_effect = ConnectionError("Connection refused")

        result = await queue.health_check()
        assert result["redis_connected"] is False
        assert result["workers"] == []

    async def test_health_check_active_task_counting(
        self, queue, mock_redis, mock_celery_app
    ):
        """health_check() should correctly sum active tasks across workers."""
        inspect_mock = MagicMock()
        inspect_mock.ping.return_value = {"w1": {"ok": "pong"}}
        inspect_mock.active.return_value = {
            "w1": [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        }
        inspect_mock.scheduled.return_value = None
        inspect_mock.reserved.return_value = None
        mock_celery_app.control.inspect.return_value = inspect_mock

        result = await queue.health_check()
        assert result["active_tasks"] == 3
        assert result["scheduled_tasks"] == 0
        assert result["reserved_tasks"] == 0


# ---------------------------------------------------------------------------
# TestCeleryCleanup
# ---------------------------------------------------------------------------


class TestCeleryCleanup:
    """Tests for CeleryJobQueue.cleanup_old_jobs()."""

    async def test_cleanup_removes_old_inactive(self, queue, mock_redis):
        """cleanup_old_jobs() should remove old completed jobs."""
        info = _make_job_info(
            job_id="old-job",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            completed_at=datetime(2026, 1, 1, 1, 0, 0),
        )
        mock_redis.zrangebyscore.return_value = [b"old-job"]
        mock_redis.hget.return_value = _job_info_to_json(info)

        count = await queue.cleanup_old_jobs(days=7)
        assert count == 1
        mock_redis.hdel.assert_called_once_with("shyfem:jobs", "old-job")
        mock_redis.zrem.assert_called_once_with("shyfem:jobs:by_time", "old-job")

    async def test_cleanup_skips_active_jobs(self, queue, mock_redis):
        """cleanup_old_jobs() should not remove active (RUNNING) jobs."""
        info = _make_job_info(
            job_id="running-job",
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1),
        )
        mock_redis.zrangebyscore.return_value = [b"running-job"]
        mock_redis.hget.return_value = _job_info_to_json(info)

        count = await queue.cleanup_old_jobs(days=7)
        assert count == 0
        mock_redis.hdel.assert_not_called()

    async def test_cleanup_empty_returns_zero(self, queue, mock_redis):
        """cleanup_old_jobs() with no old jobs should return 0."""
        mock_redis.zrangebyscore.return_value = []

        count = await queue.cleanup_old_jobs(days=7)
        assert count == 0


# ---------------------------------------------------------------------------
# TestCeleryReadsConfigShyfemDir
# ---------------------------------------------------------------------------


class TestCeleryReadsConfigShyfemDir:

    def test_init_reads_shyfem_dir_from_config_not_env(self, monkeypatch, tmp_path):
        """Regression: CeleryJobQueue.__init__ must resolve shyfem_dir via
        get_config(), not via os.environ.get directly. If env and config
        disagree, config wins."""
        from unittest.mock import MagicMock

        # Env says one thing
        monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", "/wrong/path/from/env")

        # Config says another — stub get_config() so we don't need a full Config
        fake_config = MagicMock()
        fake_config.shyfem_dir = "/correct/from/config"
        fake_config.work_dir = str(tmp_path)
        # Add any other attributes CeleryJobQueue.__init__ reads from config.
        monkeypatch.setattr(
            "shyfem_ui.services.job_celery.get_config", lambda: fake_config
        )

        # No broker connection happens in __init__ (celery app is created lazily).

        from shyfem_ui.services.job_celery import CeleryJobQueue
        # The CeleryJobQueue __init__ may take other args; adapt to actual signature.
        queue = CeleryJobQueue()  # ← may need: shyfem_dir=None, redis_url=None, etc.

        # The constructor stored shyfem_dir from CONFIG, not from ENV.
        assert "/correct/from/config" in str(queue.shyfem_dir)
        assert "/wrong/path/from/env" not in str(queue.shyfem_dir)
