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
