"""Tests for CeleryJobQueue using mocked Redis and Celery."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from shyfem_ui.services.job_celery import (
    CELERY_LOST_ERROR,
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
            "completed_at": job_info.completed_at.isoformat() if job_info.completed_at else None,
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

    async def test_submit_records_dispatched_celery_task_id(self, queue, job_spec, mock_redis):
        """The task id returned by apply_async is recorded in metadata (it
        round-trips through Redis to the worker, which persists it). Recorded
        from the AsyncResult — NOT assumed equal to the job id — so it stays
        correct if the task-id scheme ever diverges."""
        await queue.submit(job_spec)
        last_hset_call = mock_redis.hset.call_args_list[-1]
        stored_json = json.loads(last_hset_call[0][2])
        # the mock_task fixture's apply_async returns MagicMock(id="celery-task-1")
        assert stored_json["metadata"]["celery_task_id"] == "celery-task-1"


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
        info1 = _make_job_info(job_id="job-1", metadata={"session_id": "sess-A"})
        info2 = _make_job_info(job_id="job-2", metadata={"session_id": "sess-B"})

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
        infos = {f"job-{i}": _make_job_info(job_id=f"job-{i}") for i in range(5)}

        mock_redis.zrevrange.return_value = [f"job-{i}".encode() for i in range(5)]
        mock_redis.hget.side_effect = lambda key, jid: _job_info_to_json(infos[jid])

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

    async def test_cleanup_deletes_persisted_db_row(self, queue, mock_redis, tmp_path, monkeypatch):
        """cleanup must also delete the persisted SQL Job row (CeleryJobQueue
        writes one via _persist_job_to_db), not just the Redis entry — else the
        jobs table grows unbounded."""
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'celery.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        from shyfem_ui.models.project import Job

        with dbb.db_session() as db:
            db.add(
                Job(
                    job_uuid="old-db-job",
                    name="old",
                    job_type="shyfem",
                    working_dir="/tmp",
                    status=JobStatus.COMPLETED,
                )
            )

        info = _make_job_info(
            job_id="old-db-job",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            completed_at=datetime(2026, 1, 1, 1, 0, 0),
        )
        mock_redis.zrangebyscore.return_value = [b"old-db-job"]
        mock_redis.hget.return_value = _job_info_to_json(info)

        count = await queue.cleanup_old_jobs(days=7)
        assert count == 1
        with dbb.db_session() as db:
            assert db.query(Job).filter(Job.job_uuid == "old-db-job").first() is None

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None

    async def test_cleanup_blocking_work_runs_off_the_event_loop(self, queue, mock_redis):
        """cleanup_old_jobs is awaited directly by maintenance.py. Its Redis
        scan/deletes and the SQL row delete are all blocking calls, so they
        must run in a worker thread -- not on the event-loop thread, where
        they would stall every concurrent session (job_local already
        offloads its delete helpers the same way, L38)."""
        import contextlib
        import threading

        loop_thread = threading.get_ident()
        seen: dict[str, int] = {}

        info = _make_job_info(
            job_id="old-job",
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
            completed_at=datetime(2026, 1, 1, 1, 0, 0),
        )

        def _zrange(*_a, **_k):
            seen["redis"] = threading.get_ident()
            return [b"old-job"]

        mock_redis.zrangebyscore.side_effect = _zrange
        mock_redis.hget.return_value = _job_info_to_json(info)

        @contextlib.contextmanager
        def _fake_db_session():
            seen["db"] = threading.get_ident()
            yield MagicMock()

        with patch("shyfem_ui.db.base.db_session", _fake_db_session):
            count = await queue.cleanup_old_jobs(days=7)

        assert count == 1
        assert seen["redis"] != loop_thread, "Redis scan ran on the event loop"
        assert seen["db"] != loop_thread, "SQL row delete ran on the event loop"


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
        monkeypatch.setattr("shyfem_ui.services.job_celery.get_config", lambda: fake_config)

        # No broker connection happens in __init__ (celery app is created lazily).

        from shyfem_ui.services.job_celery import CeleryJobQueue

        # The CeleryJobQueue __init__ may take other args; adapt to actual signature.
        queue = CeleryJobQueue()  # ← may need: shyfem_dir=None, redis_url=None, etc.

        # The constructor stored shyfem_dir from CONFIG, not from ENV.
        assert "/correct/from/config" in str(queue.shyfem_dir)
        assert "/wrong/path/from/env" not in str(queue.shyfem_dir)


# ---------------------------------------------------------------------------
# TestCeleryParity
# ---------------------------------------------------------------------------


class TestCeleryParity:
    """CeleryJobQueue must have parity with LocalJobQueue for DB persistence
    and notification emails."""

    def _fake_config(self, monkeypatch, tmp_path):
        fake_config = MagicMock()
        fake_config.shyfem_dir = "/usr/local/shyfem"
        fake_config.work_dir = str(tmp_path)
        monkeypatch.setattr("shyfem_ui.services.job_celery.get_config", lambda: fake_config)
        return fake_config

    def test_celery_init_accepts_session_factory_and_notification_service(
        self, monkeypatch, tmp_path
    ):
        """CeleryJobQueue.__init__ must accept the same kwargs as LocalJobQueue."""
        self._fake_config(monkeypatch, tmp_path)

        sf = MagicMock(name="session_factory")
        ns = MagicMock(name="notification_service")
        q = CeleryJobQueue(session_factory=sf, notification_service=ns)
        # Both must be stored on the instance for the task callbacks to use.
        assert q.session_factory is sf
        assert q.notification_service is ns

    def test_factory_passes_session_factory_and_notification_to_celery(self, monkeypatch, tmp_path):
        """JobQueueFactory.create(mode='celery', ...) must propagate both kwargs."""
        from shyfem_ui.services.job_queue import JobQueueFactory

        self._fake_config(monkeypatch, tmp_path)

        sf = MagicMock(name="session_factory")
        ns = MagicMock(name="notification_service")
        cfg = MagicMock(
            work_dir=str(tmp_path),
            shyfem_dir="/usr/local/shyfem",
            redis_url="redis://localhost:6379/0",
        )

        q = JobQueueFactory.create(
            mode="celery",
            config=cfg,
            session_factory=sf,
            notification_service=ns,
        )
        assert q.session_factory is sf
        assert q.notification_service is ns

    def test_celery_persists_job_state_to_db(self, monkeypatch, tmp_path):
        """On terminal status transition, _persist_job must write to the DB."""
        from shyfem_ui.services.job_queue import JobInfo, JobStatus

        self._fake_config(monkeypatch, tmp_path)

        # Build a mock session that acts as a context manager
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        # query chain: session.query(Job).filter(...).first() → None (new row)
        session.query.return_value.filter.return_value.first.return_value = None

        sf = MagicMock(return_value=session)

        q = CeleryJobQueue(session_factory=sf)

        job = JobInfo(
            id="parity-job-1",
            name="parity_test",
            tool_name="shyfem",
            args=["test.str"],
            working_dir=str(tmp_path),
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 4, 28, 10, 0, 0),
        )

        # Patch the Job ORM model so we don't need a real DB schema
        fake_job_cls = MagicMock()
        monkeypatch.setattr("shyfem_ui.models.project.Job", fake_job_cls)

        q._persist_job(job)

        # session_factory was called once (to open the session)
        sf.assert_called_once()
        # add() must have been called (new row path)
        session.add.assert_called_once()

    def test_celery_sends_completion_notification_on_success(self, monkeypatch, tmp_path):
        """notification_service.notify_job_success is called for COMPLETED jobs."""
        import shyfem_ui.services.job_celery as mod
        from shyfem_ui.services.job_queue import JobInfo, JobStatus

        self._fake_config(monkeypatch, tmp_path)

        ns = MagicMock(name="notification_service")
        q = CeleryJobQueue(notification_service=ns)  # noqa: F841 — side effect sets global

        job = JobInfo(
            id="notify-job-1",
            name="notify_test",
            tool_name="shyfem",
            args=[],
            working_dir=str(tmp_path),
            status=JobStatus.COMPLETED,
            created_at=datetime(2026, 4, 28, 10, 0, 0),
            started_at=datetime(2026, 4, 28, 10, 0, 0),
            completed_at=datetime(2026, 4, 28, 10, 0, 5),
        )

        # Call the module-level function directly (as the Celery worker would)
        mod._send_completion_notification(job)
        ns.notify_job_success.assert_called_once()

    def test_celery_sends_failure_notification_on_failure(self, monkeypatch, tmp_path):
        """notification_service.notify_job_failed is called for FAILED jobs."""
        import shyfem_ui.services.job_celery as mod
        from shyfem_ui.services.job_queue import JobInfo, JobStatus

        self._fake_config(monkeypatch, tmp_path)

        ns = MagicMock(name="notification_service")
        q = CeleryJobQueue(notification_service=ns)  # noqa: F841 — side effect sets global

        job = JobInfo(
            id="notify-job-2",
            name="notify_fail_test",
            tool_name="shyfem",
            args=[],
            working_dir=str(tmp_path),
            status=JobStatus.FAILED,
            created_at=datetime(2026, 4, 28, 10, 0, 0),
            error_message="Something went wrong",
        )

        mod._send_completion_notification(job)
        ns.notify_job_failed.assert_called_once()


# ---------------------------------------------------------------------------
# TestPersistJobThreadSafety
# ---------------------------------------------------------------------------


class TestPersistJobThreadSafety:
    """Regression tests for the racy global save/restore pattern removed in
    the thread-safety fix."""

    def test_persist_job_does_not_mutate_global(self, monkeypatch, tmp_path):
        """Regression: _persist_job must not save/swap/restore the global —
        that pattern was racy across concurrent instances."""
        import shyfem_ui.services.job_celery as mod
        from shyfem_ui.services.job_queue import JobInfo, JobStatus

        fake_config = MagicMock()
        fake_config.shyfem_dir = "/usr/local/shyfem"
        fake_config.work_dir = str(tmp_path)
        monkeypatch.setattr("shyfem_ui.services.job_celery.get_config", lambda: fake_config)

        sentinel = MagicMock(name="original_global_factory")
        monkeypatch.setattr(mod, "_queue_session_factory", sentinel)

        q1_sf = MagicMock(name="q1_factory")
        q1 = CeleryJobQueue(session_factory=q1_sf)
        # CeleryJobQueue.__init__ publishes session_factory to the global —
        # record its state *after* construction so we're testing _persist_job.
        pre_persist_global = mod._queue_session_factory

        info = JobInfo(
            id="x",
            name="t",
            tool_name="shyfem",
            args=[],
            working_dir=str(tmp_path),
            status=JobStatus.COMPLETED,
        )

        # Stub _persist_job_to_db to avoid touching a real DB.
        stub = MagicMock()
        monkeypatch.setattr(mod, "_persist_job_to_db", stub)

        q1._persist_job(info)

        post_persist_global = mod._queue_session_factory
        assert (
            post_persist_global is pre_persist_global
        ), "Module global must not be mutated by _persist_job"
        # And the stub must have been called with the instance's own factory.
        stub.assert_called_once_with(info, session_factory=q1_sf)


class TestCeleryCompletionNotificationUserLookup:
    """The Celery backend's completion email must include the user's email —
    same DetachedInstanceError class as the local backend: the User was read
    inside `with db_session()` but accessed after the block closed, dropping
    the email."""

    def test_notification_includes_user_email(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import shyfem_ui.db.base as dbbase
        import shyfem_ui.services.job_celery as jc
        from shyfem_ui.db.base import Base
        from shyfem_ui.models.user import User

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(dbbase, "_SessionLocal", factory)

        db = factory()
        u = User(username="carol", password_hash="x", role="user", email="carol@example.com")
        db.add(u)
        db.commit()
        uid = u.id
        db.close()

        notif = MagicMock()
        monkeypatch.setattr(jc, "_queue_notification_service", notif)

        job = JobInfo(
            id="cj1",
            name="n",
            tool_name="shyfem",
            args=[],
            working_dir="/tmp",
            status=JobStatus.COMPLETED,
            metadata={"user_id": uid},
        )
        jc._send_completion_notification(job)

        notif.notify_job_success.assert_called_once()
        user_dict = notif.notify_job_success.call_args[0][0]
        assert user_dict.get("email") == "carol@example.com"


class TestCeleryTaskIdPersisted:
    """Job.celery_task_id (previously a dead column — never written or read) is
    now populated from the dispatched task id carried in job metadata."""

    async def test_persist_writes_celery_task_id_column(self, tmp_path, monkeypatch):
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'ct.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        from shyfem_ui.models.project import Job
        from shyfem_ui.services.job_celery import _persist_job_to_db

        info = _make_job_info(job_id="ct-job-1", status=JobStatus.QUEUED)
        info.metadata["celery_task_id"] = "celery-task-xyz"
        _persist_job_to_db(info, session_factory=dbb.db_session)

        with dbb.db_session() as db:
            row = db.query(Job).filter(Job.job_uuid == "ct-job-1").first()
            assert row is not None
            assert row.celery_task_id == "celery-task-xyz"

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None


# ---------------------------------------------------------------------------
# TestCeleryPhantomReconcile
# ---------------------------------------------------------------------------


class _DictRedis:
    """The few Redis calls the job store makes, backed by real dicts, so a
    test reads back the state the queue actually wrote. ``pipeline()`` keeps
    WATCH semantics: any write to the hash between ``watch`` and ``execute``
    makes ``execute`` raise; ``before_exec`` lets a test land such a write."""

    def __init__(self):
        self.jobs: dict[str, str] = {}
        self.by_time: dict[str, float] = {}
        self.version = 0
        self.before_exec = None

    def hset(self, key, field, value):
        self.jobs[field] = value
        self.version += 1

    def hget(self, key, field):
        return self.jobs.get(field)

    def hdel(self, key, field):
        self.jobs.pop(field, None)
        self.version += 1

    def zadd(self, key, mapping):
        self.by_time.update(mapping)

    def zrem(self, key, member):
        self.by_time.pop(member, None)

    def zrange(self, key, start, end):
        return [k.encode() for k, _ in sorted(self.by_time.items(), key=lambda kv: kv[1])]

    def zrangebyscore(self, key, lo, hi):
        return [
            k.encode()
            for k, s in sorted(self.by_time.items(), key=lambda kv: kv[1])
            if lo == "-inf" or s >= lo
            if s <= hi
        ]

    def pipeline(self):
        return _DictPipeline(self)


class _DictPipeline:
    def __init__(self, r):
        self.r = r
        self.queued = None
        self.watched = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def watch(self, key):
        self.watched = self.r.version

    def hget(self, key, field):
        return self.r.hget(key, field)

    def multi(self):
        self.queued = []

    def hset(self, *a):
        self.queued.append(("hset", a))

    def zadd(self, *a):
        self.queued.append(("zadd", a))

    def execute(self):
        from shyfem_ui.services import job_celery as jc

        if self.r.before_exec:
            hook, self.r.before_exec = self.r.before_exec, None
            hook()
        if self.r.version != self.watched:
            raise jc._WatchError("watched key changed")
        for name, a in self.queued:
            getattr(self.r, name)(*a)


class TestCeleryPhantomReconcile:
    """A worker killed mid-job (OOM, reboot, kill -9) never runs the task's
    ``finally``: the job stays RUNNING in Redis forever, is shown as running,
    and cleanup_old_jobs skips it as active. The web process restarting proves
    nothing under Celery (workers are separate daemons), so liveness comes
    from the job's own worker: it replied without listing the job, on two
    consecutive passes."""

    PERSIST = "shyfem_ui.services.job_celery.CeleryJobQueue._persist_job"

    @pytest.fixture
    def store(self):
        return _DictRedis()

    @pytest.fixture
    def rqueue(self, queue, store, mock_celery_app):
        queue._redis_client = store
        self.active = {"celery@w1": []}  # worker -> task dicts
        self.raw = None  # a raw broadcast reply list, overriding self.active
        self.during = None  # runs inside the broadcast, before it returns

        def _broadcast(command, **kw):
            assert command == "active" and kw.get("reply") is True
            if self.during:
                self.during()
            if self.raw is not None:
                return self.raw
            if isinstance(self.active, Exception):
                raise self.active
            return [{w: t} for w, t in (self.active or {}).items()]

        mock_celery_app.control.broadcast.side_effect = _broadcast
        return queue

    def _put(self, store, job_id, status, worker="celery@w1", **kw):
        kw.setdefault("created_at", datetime.now())
        if status == JobStatus.RUNNING:
            kw.setdefault("started_at", datetime.now())
            kw.setdefault("metadata", {"celery_worker": worker} if worker else {})
        _store_job_info(store, _make_job_info(job_id=job_id, status=status, **kw))

    def _status(self, store, job_id):
        return _load_job_info(store, job_id).status

    def test_job_its_worker_no_longer_has_fails_on_second_pass(self, rqueue, store):
        """The reboot case: the worker is back under the same node name and
        replies, without the job its previous incarnation was running."""
        self._put(store, "lost", JobStatus.RUNNING)
        self.active = {"celery@w1": [{"id": "something-new"}]}
        with patch(self.PERSIST) as persist:
            assert rqueue.reconcile_phantom_jobs() == 0
            assert self._status(store, "lost") == JobStatus.RUNNING  # one miss is not proof
            assert rqueue.reconcile_phantom_jobs() == 1
        info = _load_job_info(store, "lost")
        assert info.status == JobStatus.FAILED
        assert info.error_message == CELERY_LOST_ERROR
        assert info.completed_at is not None
        assert not info.is_active
        persisted = persist.call_args.args[0]
        assert persisted.id == "lost" and persisted.status == JobStatus.FAILED

    def test_job_its_worker_lists_is_left_alone(self, rqueue, store):
        self._put(store, "live", JobStatus.RUNNING, worker="celery@w2")
        self.active = {"celery@w1": [], "celery@w2": [{"id": "live"}]}
        with patch(self.PERSIST) as persist:
            for _ in range(3):
                assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "live") == JobStatus.RUNNING
        persist.assert_not_called()

    def test_liveness_is_matched_on_the_dispatched_task_id(self, rqueue, store):
        self._put(
            store,
            "j",
            JobStatus.RUNNING,
            metadata={"celery_worker": "celery@w1", "celery_task_id": "task-9"},
        )
        self.active = {"celery@w1": [{"id": "task-9"}]}
        with patch(self.PERSIST):
            for _ in range(3):
                assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "j") == JobStatus.RUNNING

    def test_reappearing_job_resets_its_miss(self, rqueue, store):
        """A worker that missed one reply window (busy, slow) must not get
        its job killed: the two misses have to be consecutive."""
        self._put(store, "slow", JobStatus.RUNNING)
        with patch(self.PERSIST):
            rqueue.reconcile_phantom_jobs()  # miss
            self.active = {"celery@w1": [{"id": "slow"}]}
            rqueue.reconcile_phantom_jobs()  # seen
            self.active = {"celery@w1": []}
            assert rqueue.reconcile_phantom_jobs() == 0  # one miss again
        assert self._status(store, "slow") == JobStatus.RUNNING

    @pytest.mark.parametrize(
        "gap", [None, RuntimeError("broker down")], ids=["no-reply", "broadcast-error"]
    )
    def test_a_pass_without_evidence_breaks_the_run_of_misses(self, rqueue, store, gap):
        """miss, (silence for hours), miss is not two misses in a row."""
        self._put(store, "j", JobStatus.RUNNING)
        with patch(self.PERSIST):
            rqueue.reconcile_phantom_jobs()  # miss
            self.active = gap
            try:
                rqueue.reconcile_phantom_jobs()
            except RuntimeError:
                pass  # cleanup catches it; the count must still be reset
            self.active = {"celery@w1": []}
            assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "j") == JobStatus.RUNNING

    def test_job_whose_worker_is_silent_survives_other_replies(self, rqueue, store):
        """A busy ``--pool=solo`` worker answers no control command while its
        task runs (seen against a real Celery 5.6 worker). Another worker's
        reply says nothing about its job."""
        self._put(store, "busy", JobStatus.RUNNING, worker="celery@solo")
        self.active = {"celery@idle": []}
        with patch(self.PERSIST) as persist:
            for _ in range(4):
                assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "busy") == JobStatus.RUNNING
        persist.assert_not_called()

    def test_job_with_no_recorded_worker_is_never_reconciled(self, rqueue, store):
        """Started by a worker older than this code: its owner is unknown, so
        no reply can speak for it (a busy owner may simply be silent)."""
        self._put(store, "old", JobStatus.RUNNING, worker=None)
        self.active = {"celery@w1": [], "celery@w2": []}
        with patch(self.PERSIST) as persist:
            for _ in range(4):
                assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "old") == JobStatus.RUNNING
        persist.assert_not_called()

    def test_a_node_name_replying_twice_is_no_evidence(self, rqueue, store, caplog):
        """Two workers started without distinct -n share 'celery@host'; the
        idle one's empty list says nothing about the busy one's job. A worker
        with a unique name is still judged."""
        self._put(store, "busy", JobStatus.RUNNING, worker="celery@host")
        self._put(store, "lost", JobStatus.RUNNING, worker="celery@other")
        self.raw = [
            {"celery@host": [{"id": "busy"}]},
            {"celery@host": []},
            {"celery@other": []},
        ]
        with patch(self.PERSIST):
            for _ in range(3):
                rqueue.reconcile_phantom_jobs()
        assert self._status(store, "busy") == JobStatus.RUNNING
        assert self._status(store, "lost") == JobStatus.FAILED
        assert "several Celery workers reply as celery@host" in caplog.text

    @pytest.mark.parametrize("reply", [None, {}])
    def test_no_worker_reply_touches_nothing(self, rqueue, store, caplog, reply):
        """No reply cannot tell 'all workers down' from 'broker unreachable';
        never a wrong FAILED -- the next pass with workers back decides."""
        self._put(store, "j", JobStatus.RUNNING)
        self.active = reply
        with patch(self.PERSIST) as persist:
            for _ in range(3):
                assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "j") == JobStatus.RUNNING
        persist.assert_not_called()
        assert "no usable reply from any Celery worker" in caplog.text

    def test_queued_and_terminal_jobs_are_never_touched(self, rqueue, store):
        """QUEUED may legitimately wait in the broker for hours, and only the
        broker's own message format could tell it from a lost one."""
        self._put(store, "q", JobStatus.QUEUED)
        self._put(store, "p", JobStatus.PENDING)
        self._put(store, "done", JobStatus.COMPLETED)
        self._put(store, "r", JobStatus.RUNNING)  # so the workers are asked
        with patch(self.PERSIST):
            for _ in range(3):
                rqueue.reconcile_phantom_jobs()
        assert self._status(store, "q") == JobStatus.QUEUED
        assert self._status(store, "p") == JobStatus.PENDING
        assert self._status(store, "done") == JobStatus.COMPLETED

    def test_job_finishing_during_the_broadcast_keeps_its_result(self, rqueue, store):
        self._put(store, "j", JobStatus.RUNNING)
        with patch(self.PERSIST) as persist:
            rqueue.reconcile_phantom_jobs()  # first miss
            self.during = lambda: self._put(
                store, "j", JobStatus.COMPLETED, completed_at=datetime.now()
            )
            assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "j") == JobStatus.COMPLETED
        persist.assert_not_called()

    def test_job_finishing_between_reread_and_write_keeps_its_result(self, rqueue, store):
        """The task's finally lands after the CAS re-read: the WATCH aborts
        the FAILED write instead of replacing the real result."""
        self._put(store, "j", JobStatus.RUNNING)
        with patch(self.PERSIST) as persist:
            rqueue.reconcile_phantom_jobs()  # first miss
            store.before_exec = lambda: self._put(
                store, "j", JobStatus.COMPLETED, completed_at=datetime.now()
            )
            assert rqueue.reconcile_phantom_jobs() == 0
        assert self._status(store, "j") == JobStatus.COMPLETED
        persist.assert_not_called()

    def test_another_jobs_write_only_retries_the_cas(self, rqueue, store):
        """The WATCH covers the whole hash: a progress write from some other
        job aborts the write, and the retry (status re-read) still lands."""
        self._put(store, "lost", JobStatus.RUNNING)
        self._put(store, "other", JobStatus.COMPLETED)
        with patch(self.PERSIST):
            rqueue.reconcile_phantom_jobs()  # first miss
            store.before_exec = lambda: self._put(store, "other", JobStatus.COMPLETED)
            assert rqueue.reconcile_phantom_jobs() == 1
        assert self._status(store, "lost") == JobStatus.FAILED

    def test_a_failed_scan_also_breaks_the_run_of_misses(self, rqueue, store):
        self._put(store, "j", JobStatus.RUNNING)
        with patch(self.PERSIST):
            rqueue.reconcile_phantom_jobs()  # miss
            real = store.zrange
            store.zrange = MagicMock(side_effect=ConnectionError("redis blip"))
            with pytest.raises(ConnectionError):
                rqueue.reconcile_phantom_jobs()
            store.zrange = real
            assert rqueue.reconcile_phantom_jobs() == 0  # one miss again
        assert self._status(store, "j") == JobStatus.RUNNING

    def test_no_running_jobs_broadcasts_nothing(self, rqueue, store, mock_celery_app):
        self._put(store, "done", JobStatus.COMPLETED)
        rqueue.reconcile_phantom_jobs()
        mock_celery_app.control.broadcast.assert_not_called()

    async def test_cleanup_reconciles_then_prunes_the_phantom(self, rqueue, store):
        """Maintenance runs cleanup_old_jobs every pass: an old phantom is
        reconciled there and, now terminal, pruned like any finished job."""
        old = datetime(2026, 1, 1)
        self._put(store, "old-lost", JobStatus.RUNNING, created_at=old, started_at=old)
        with patch(self.PERSIST), patch("shyfem_ui.db.base.db_session"):
            assert await rqueue.cleanup_old_jobs(days=7) == 0
            assert "old-lost" in store.jobs
            assert await rqueue.cleanup_old_jobs(days=7) == 1
        assert "old-lost" not in store.jobs

    async def test_reconcile_failure_does_not_block_cleanup(self, rqueue, store):
        old = datetime(2026, 1, 1)
        self._put(store, "old-done", JobStatus.COMPLETED, created_at=old, completed_at=old)
        self._put(store, "r", JobStatus.RUNNING)
        self.active = RuntimeError("broker down")
        with patch("shyfem_ui.db.base.db_session"):
            assert await rqueue.cleanup_old_jobs(days=7) == 1
        assert self._status(store, "r") == JobStatus.RUNNING


class TestCeleryWorkerRecordsItself:
    """The reconcile pass asks a job's own worker about it, so the worker
    must record its node name on the job before it marks it RUNNING."""

    def test_running_job_carries_the_worker_hostname(self, tmp_path):
        from types import SimpleNamespace

        from shyfem_ui.services.job_celery import execute_shyfem_job

        store = _DictRedis()
        _store_job_info(
            store,
            _make_job_info(
                job_id="j", status=JobStatus.QUEUED, tool_name="shybas", working_dir=str(tmp_path)
            ),
        )
        seen: list[tuple[str, str | None]] = []
        real_hset = store.hset

        def _hset(key, field, value):
            d = json.loads(value)
            seen.append((d["status"], d["metadata"].get("celery_worker")))
            real_hset(key, field, value)

        store.hset = _hset

        async def _run(*_a, **_k):
            return SimpleNamespace(
                success=True, return_code=0, output_files=[], stdout="", stderr=""
            )

        wrapper = MagicMock()
        wrapper.run_command.side_effect = _run
        with (
            patch("shyfem_ui.services.job_celery._get_redis_client", return_value=store),
            patch("shyfem_ui.services.shyfem_wrapper.ShyfemWrapper", return_value=wrapper),
            patch("shyfem_ui.services.job_celery._persist_job_to_db"),
        ):
            execute_shyfem_job("j", "redis://x", str(tmp_path), hostname="celery@w7")

        assert seen[0] == ("running", "celery@w7")
        assert all(worker == "celery@w7" for _, worker in seen)
        assert _load_job_info(store, "j").status == JobStatus.COMPLETED

    def test_registered_task_passes_its_request_hostname(self):
        from types import SimpleNamespace

        from shyfem_ui.services.job_celery import _register_celery_task

        app = MagicMock()
        app.task.return_value = lambda fn: fn
        task = _register_celery_task(app)
        with patch("shyfem_ui.services.job_celery.execute_shyfem_job") as run:
            task(SimpleNamespace(request=SimpleNamespace(hostname="celery@w3")), "j", "u", "d")
        run.assert_called_once_with("j", "u", "d", hostname="celery@w3")


class TestCeleryWorkerEntryPoint:
    """``celery -A shyfem_ui.services.job_celery worker`` needs a module
    attribute ``app`` carrying the job task; the module had none, so the
    documented command (README, docker-compose) could not start a worker."""

    def test_app_attribute_is_the_configured_app_with_the_task(self, monkeypatch):
        import shyfem_ui.config as cfg
        import shyfem_ui.services.job_celery as jc

        monkeypatch.setenv("SHYFEM_UI_REDIS_URL", "redis://broker.example:6380/2")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(jc, "_worker_task", None)
        fake_app = MagicMock(name="celery-app")
        with (
            patch.object(jc, "get_celery_app", return_value=fake_app) as get_app,
            patch.object(jc, "_register_celery_task") as register,
        ):
            assert jc.app is fake_app
            assert jc.app is fake_app
        get_app.assert_called_with("redis://broker.example:6380/2")
        register.assert_called_once_with(fake_app)
        cfg._config = None

    def test_import_and_other_attributes_need_no_celery(self):
        """Celery is optional: importing the module and probing any other
        attribute must not build an app."""
        import shyfem_ui.services.job_celery as jc

        with patch.object(jc, "get_celery_app") as get_app:
            assert not hasattr(jc, "celery")
            with pytest.raises(AttributeError):
                jc.no_such_thing  # noqa: B018
        get_app.assert_not_called()
