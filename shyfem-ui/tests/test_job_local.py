"""Tests for local job queue implementation."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from shyfem_ui.services.job_local import LocalJobQueue
from shyfem_ui.services.job_queue import JobInfo, JobSpec, JobStatus
from shyfem_ui.services.shyfem_wrapper import CommandResult


@pytest.fixture
def mock_wrapper():
    """Create a mock ShyfemWrapper."""
    wrapper = MagicMock()
    wrapper.run_command = AsyncMock(
        return_value=CommandResult(
            success=True,
            return_code=0,
            stdout="mock output",
            stderr="",
            command="test",
            working_dir="/tmp",
            duration=1.0,
            output_files=[],
        )
    )
    wrapper.run_shyfem = AsyncMock(
        return_value=CommandResult(
            success=True,
            return_code=0,
            stdout="mock mpi output",
            stderr="",
            command="mpirun shyfem",
            working_dir="/tmp",
            duration=2.0,
            output_files=[],
        )
    )
    return wrapper


@pytest.fixture
def queue(tmp_path, mock_wrapper):
    """Create a LocalJobQueue with mock wrapper."""
    q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=2)
    q.wrapper = mock_wrapper
    # Start each test with a clean in-memory job set. The constructor loads any
    # rows from the shared test DB; prior tests can leave RUNNING rows (now that
    # persistence is async via to_thread), which would skew active_job_count.
    q._jobs.clear()
    return q


@pytest.fixture
def job_spec(tmp_path):
    """Create a basic job spec."""
    return JobSpec(
        name="test_job",
        tool_name="shypre",
        args=["input.grd"],
        working_dir=tmp_path / "work",
    )


class TestLocalJobQueue:
    """Tests for LocalJobQueue."""

    @pytest.mark.asyncio
    async def test_submit_returns_job_id(self, queue, job_spec):
        """Test that submit returns a valid job ID."""
        job_id = await queue.submit(job_spec)
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    @pytest.mark.asyncio
    async def test_get_status_after_submit(self, queue, job_spec):
        """Test getting job status after submission."""
        job_id = await queue.submit(job_spec)
        # Give the task a moment to start
        await asyncio.sleep(0.1)

        status = await queue.get_status(job_id)
        assert status is not None
        assert status.id == job_id
        assert status.name == "test_job"
        assert status.tool_name == "shypre"

    @pytest.mark.asyncio
    async def test_get_status_nonexistent(self, queue):
        """Test getting status for nonexistent job returns None."""
        status = await queue.get_status("nonexistent-id")
        assert status is None

    @pytest.mark.asyncio
    async def test_job_completes(self, queue, job_spec):
        """Test that a job eventually completes."""
        job_id = await queue.submit(job_spec)
        # Wait for completion
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        status = await queue.get_status(job_id)
        assert status.status == JobStatus.COMPLETED
        assert status.return_code == 0

    @pytest.mark.asyncio
    async def test_job_stores_output_files(self, queue, job_spec, tmp_path):
        """Test that stdout/stderr files are set."""
        job_id = await queue.submit(job_spec)
        await asyncio.sleep(0.1)

        status = await queue.get_status(job_id)
        assert status.stdout_file is not None
        assert status.stderr_file is not None
        assert job_id in status.stdout_file

    @pytest.mark.asyncio
    async def test_list_jobs_all(self, queue, job_spec):
        """Test listing all jobs."""
        id1 = await queue.submit(job_spec)
        id2 = await queue.submit(
            JobSpec(
                name="job2", tool_name="shyfem", args=["test.str"], working_dir=job_spec.working_dir
            )
        )
        await asyncio.sleep(0.1)

        jobs = await queue.list_jobs()
        assert len(jobs) >= 2
        ids = [j.id for j in jobs]
        assert id1 in ids
        assert id2 in ids

    @pytest.mark.asyncio
    async def test_list_jobs_filter_status(self, queue, job_spec):
        """Test listing jobs filtered by status."""
        job_id = await queue.submit(job_spec)
        # Wait for completion
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        completed = await queue.list_jobs(status=JobStatus.COMPLETED)
        assert any(j.id == job_id for j in completed)

        running = await queue.list_jobs(status=JobStatus.RUNNING)
        assert not any(j.id == job_id for j in running)

    @pytest.mark.asyncio
    async def test_list_jobs_filter_simulation_id(self, queue, tmp_path):
        """Test listing jobs filtered by simulation ID."""
        spec1 = JobSpec(
            name="sim1",
            tool_name="shyfem",
            args=["t.str"],
            working_dir=tmp_path / "w1",
            simulation_id=42,
        )
        spec2 = JobSpec(
            name="sim2",
            tool_name="shyfem",
            args=["t.str"],
            working_dir=tmp_path / "w2",
            simulation_id=99,
        )

        await queue.submit(spec1)
        await queue.submit(spec2)
        await asyncio.sleep(0.1)

        filtered = await queue.list_jobs(simulation_id=42)
        assert all(j.simulation_id == 42 for j in filtered)

    @pytest.mark.asyncio
    async def test_list_jobs_limit(self, queue, tmp_path):
        """Test list_jobs respects limit parameter."""
        for i in range(5):
            spec = JobSpec(
                name=f"job{i}", tool_name="shypre", args=[], working_dir=tmp_path / f"w{i}"
            )
            await queue.submit(spec)

        await asyncio.sleep(0.1)
        jobs = await queue.list_jobs(limit=2)
        assert len(jobs) <= 2

    @pytest.mark.asyncio
    async def test_cancel_running_job(self, queue, tmp_path):
        """Test cancelling a running job — deterministic via an asyncio.Event
        that the mock coroutine sets as soon as it begins executing.
        No fixed sleep on the critical path."""
        started_event = asyncio.Event()

        async def slow_command(*args, **kwargs):
            started_event.set()  # signal that we are now running
            await asyncio.sleep(10)
            return CommandResult(
                success=True,
                return_code=0,
                stdout="",
                stderr="",
                command="test",
                working_dir=str(tmp_path),
            )

        queue.wrapper.run_command = slow_command

        # Use tool_name != "shyfem" so the queue routes through run_command.
        spec = JobSpec(
            name="slow_job", tool_name="shypre", args=["test.str"], working_dir=tmp_path / "w"
        )
        job_id = await queue.submit(spec)

        # Wait deterministically for the mock to start; bound at 5s.
        try:
            await asyncio.wait_for(started_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("Mock command did not start within 5s")

        result = await queue.cancel(job_id)
        assert result is True

        # Status should reach CANCELLED (with a short bounded wait for the
        # state machine to update after task cancellation).
        for _ in range(20):
            info = await queue.get_status(job_id)
            if info and info.status == JobStatus.CANCELLED:
                break
            await asyncio.sleep(0.1)
        else:
            info = await queue.get_status(job_id)
            pytest.fail(f"Expected CANCELLED status; got {info.status if info else 'None'}")

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self, queue):
        """Test cancelling a nonexistent job returns False."""
        result = await queue.cancel("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_completed_job(self, queue, job_spec):
        """Test cancelling an already-completed job returns False."""
        job_id = await queue.submit(job_spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        result = await queue.cancel(job_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_output(self, queue, job_spec, tmp_path):
        """Test reading job output."""
        job_id = await queue.submit(job_spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        stdout = await queue.get_output(job_id, "stdout")
        assert isinstance(stdout, str)

    @pytest.mark.asyncio
    async def test_get_output_nonexistent(self, queue):
        """Test reading output for nonexistent job returns empty."""
        result = await queue.get_output("nonexistent-id")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_output_tail(self, queue, job_spec, tmp_path):
        """Test tail parameter on get_output."""
        job_id = await queue.submit(job_spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        result = await queue.get_output(job_id, "stdout", tail=5)
        lines = result.splitlines()
        assert len(lines) <= 5

    @pytest.mark.asyncio
    async def test_mpi_metadata_stored(self, queue, tmp_path):
        """Test MPI settings are stored in job metadata."""
        spec = JobSpec(
            name="mpi_job",
            tool_name="shyfem",
            args=["test.str"],
            working_dir=tmp_path / "w",
            mpi_enabled=True,
            mpi_np=8,
        )
        job_id = await queue.submit(spec)
        status = await queue.get_status(job_id)

        assert status.metadata.get("mpi_enabled") is True
        assert status.metadata.get("mpi_np") == 8

    @pytest.mark.asyncio
    async def test_progress_callback(self, queue, tmp_path):
        """Test progress callback is called."""
        progress_data = []

        def on_progress(job_id, progress, message):
            progress_data.append((job_id, progress, message))

        queue.add_progress_callback("test-session", on_progress)

        # Simulate wrapper calling progress_callback
        async def mock_run(tool, args, wd, progress_callback=None, output_callback=None):
            if progress_callback:
                progress_callback(0.5, "halfway")
            return CommandResult(
                success=True,
                return_code=0,
                stdout="",
                stderr="",
                command="test",
                working_dir=str(wd),
            )

        queue.wrapper.run_command = mock_run

        spec = JobSpec(name="prog_job", tool_name="shypre", args=[], working_dir=tmp_path / "w")
        job_id = await queue.submit(spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        assert len(progress_data) > 0
        assert progress_data[0][1] == 0.5

    @pytest.mark.asyncio
    async def test_active_job_count(self, queue, tmp_path):
        """Test active_job_count property — deterministic via an asyncio.Event
        that the mock coroutine sets as soon as it begins executing."""
        assert queue.active_job_count == 0

        started_event = asyncio.Event()

        # Submit with slow command that actually blocks
        async def slow_command(*args, **kwargs):
            started_event.set()  # signal that we are now running
            await asyncio.sleep(10)
            return CommandResult(
                success=True,
                return_code=0,
                stdout="",
                stderr="",
                command="test",
                working_dir=str(tmp_path),
            )

        queue.wrapper.run_command = slow_command

        spec = JobSpec(name="active", tool_name="shypre", args=[], working_dir=tmp_path / "w")
        job_id = await queue.submit(spec)

        # Wait deterministically for the mock to start; bound at 5s.
        try:
            await asyncio.wait_for(started_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("Mock command did not start within 5s")

        assert queue.active_job_count >= 1

        # Clean up
        await queue.cancel(job_id)

    @pytest.mark.asyncio
    async def test_cleanup_old_jobs(self, queue, job_spec):
        """Test cleanup removes old completed jobs."""
        job_id = await queue.submit(job_spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        # Backdate the job
        job = queue._jobs[job_id]
        job.completed_at = datetime.now() - timedelta(days=30)
        job.created_at = datetime.now() - timedelta(days=30)

        removed = await queue.cleanup_old_jobs(days=7)
        assert removed >= 1
        assert await queue.get_status(job_id) is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent_jobs(self, queue, job_spec):
        """Test cleanup keeps recently completed jobs."""
        # Clear any jobs loaded from a shared DB to isolate this test
        queue._jobs.clear()

        job_id = await queue.submit(job_spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        removed = await queue.cleanup_old_jobs(days=7)
        assert removed == 0
        assert await queue.get_status(job_id) is not None


class TestJobUserIdAndNotifications:

    @pytest.mark.asyncio
    async def test_user_id_saved_from_metadata(self, queue, job_spec):
        """Job submitted with user_id in metadata is accessible after execution."""
        job_spec.metadata["user_id"] = 42
        job_id = await queue.submit(job_spec)
        await asyncio.sleep(0.3)
        jobs = await queue.list_jobs()
        job = next((j for j in jobs if j.id == job_id), None)
        assert job is not None
        assert job.metadata.get("user_id") == 42

    @pytest.mark.asyncio
    async def test_notification_called_on_success(self, queue, job_spec):
        """NotificationService.notify_job_success is called when job succeeds."""
        from unittest.mock import MagicMock

        mock_notif = MagicMock()
        mock_notif.notify_job_success = MagicMock()
        queue.notification_service = mock_notif

        await queue.submit(job_spec)
        await asyncio.sleep(0.3)
        mock_notif.notify_job_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_offloaded_to_thread(self, queue, job_spec):
        """The (blocking) SMTP send must run via asyncio.to_thread, not on the
        event loop — a slow/dead relay must not freeze other sessions."""
        from unittest.mock import MagicMock, patch

        queue.notification_service = MagicMock()
        real_to_thread = asyncio.to_thread
        offloaded = []

        async def _spy(fn, *a, **k):
            offloaded.append(getattr(fn, "__name__", str(fn)))
            return await real_to_thread(fn, *a, **k)

        with patch("asyncio.to_thread", side_effect=_spy):
            await queue.submit(job_spec)
            await asyncio.sleep(0.3)
        assert "_send_completion_notification" in offloaded

    @pytest.mark.asyncio
    async def test_notification_called_on_failure(self, queue, job_spec, mock_wrapper):
        """NotificationService.notify_job_failed is called when job fails."""
        from unittest.mock import AsyncMock, MagicMock

        from shyfem_ui.services.shyfem_wrapper import CommandResult

        mock_wrapper.run_command = AsyncMock(
            return_value=CommandResult(
                success=False,
                return_code=1,
                stdout="",
                stderr="error",
                command="test",
                working_dir="/tmp",
                duration=0.1,
                output_files=[],
            )
        )
        mock_notif = MagicMock()
        mock_notif.notify_job_failed = MagicMock()
        queue.notification_service = mock_notif

        await queue.submit(job_spec)
        await asyncio.sleep(0.3)
        mock_notif.notify_job_failed.assert_called_once()


class TestLocalJobQueueEviction:
    """Tests for job eviction when storage exceeds limit."""

    @pytest.mark.asyncio
    async def test_evict_old_jobs(self, tmp_path):
        """Test eviction of old completed jobs."""
        mock_wrapper = MagicMock()
        mock_wrapper.run_command = AsyncMock(
            return_value=CommandResult(
                success=True,
                return_code=0,
                stdout="",
                stderr="",
                command="test",
                working_dir="/tmp",
            )
        )

        q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=2)
        q.wrapper = mock_wrapper
        # Lower the cap for testing
        q.MAX_STORED_JOBS = 3

        # Submit 5 jobs and let them complete
        ids = []
        for i in range(5):
            spec = JobSpec(
                name=f"j{i}", tool_name="shypre", args=[], working_dir=tmp_path / f"w{i}"
            )
            job_id = await q.submit(spec)
            ids.append(job_id)
            await asyncio.sleep(0.15)

        # Wait for all to complete
        await asyncio.sleep(1.0)

        # Eviction should have capped storage
        assert len(q._jobs) <= q.MAX_STORED_JOBS + 2  # allow some slack for timing


class TestDbRowToJobInfo:
    """The DB->JobInfo conversion must restore user_id AND project_id into
    metadata (not just session_id) so cancel authorization survives a reload /
    server restart."""

    def _row(self, **over):
        from types import SimpleNamespace

        base = dict(
            job_uuid="u1",
            name="n",
            job_type="shyfem",
            working_dir="/tmp",
            status=JobStatus.RUNNING,
            progress=0.0,
            progress_message="",
            created_at=datetime.now(),
            queued_at=None,
            started_at=None,
            completed_at=None,
            return_code=None,
            error_message=None,
            stdout_file=None,
            stderr_file=None,
            simulation_id=None,
            session_id="sess",
            user_id=42,
            project_id=7,
        )
        base.update(over)
        return SimpleNamespace(**base)

    def test_restores_owner_and_project_into_metadata(self):
        info = LocalJobQueue._db_row_to_job_info(self._row())
        assert info.metadata.get("user_id") == 42
        assert info.metadata.get("project_id") == 7
        assert info.metadata.get("session_id") == "sess"

    def test_omits_absent_owner_and_project(self):
        info = LocalJobQueue._db_row_to_job_info(
            self._row(user_id=None, project_id=None, session_id=None)
        )
        assert "user_id" not in info.metadata
        assert "project_id" not in info.metadata


class TestCompletionNotificationUserLookup:
    """The job-completion email must include the user's email. The lookup
    queried the User inside a `with db_session()` block but read user.email
    AFTER the block closed -> DetachedInstanceError (expire_on_commit) swallowed
    at debug -> user_dict={} -> email silently dropped for every server job."""

    @pytest.mark.asyncio
    async def test_notification_includes_user_email(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import shyfem_ui.db.base as dbbase
        from shyfem_ui.db.base import Base
        from shyfem_ui.models.user import User

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(dbbase, "_SessionLocal", factory)

        db = factory()
        u = User(username="bob", password_hash="x", role="user", email="bob@example.com")
        db.add(u)
        db.commit()
        uid = u.id
        db.close()

        q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        q.notification_service = MagicMock()
        job = JobInfo(
            id="j1",
            name="n",
            tool_name="shyfem",
            args=[],
            working_dir="/tmp",
            status=JobStatus.COMPLETED,
            metadata={"user_id": uid},
        )
        q._send_completion_notification(job)

        q.notification_service.notify_job_success.assert_called_once()
        user_dict = q.notification_service.notify_job_success.call_args[0][0]
        assert user_dict.get("email") == "bob@example.com"
        assert user_dict.get("username") == "bob"


class TestStdoutOpenFailureNoLeak:
    """If opening the stdout log fails, the job must end FAILED and the
    running-count must be released. Previously touch()/open() ran OUTSIDE the
    try/finally, so a failure left the job stuck RUNNING and leaked
    _running_count (eventually wedging the queue)."""

    @pytest.mark.asyncio
    async def test_stdout_open_failure_marks_failed_and_releases_count(
        self, queue, job_spec, monkeypatch
    ):
        from pathlib import Path as _P

        def _boom(self):
            raise OSError("disk full")

        monkeypatch.setattr(_P, "touch", _boom)

        job_id = await queue.submit(job_spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.05)

        status = await queue.get_status(job_id)
        assert status.status == JobStatus.FAILED
        assert queue._running_count == 0


class TestCleanupDeletesDbRows:
    """cleanup_old_jobs must delete the persisted Job rows too, not just evict
    the in-memory dict + output files. Leaving rows behind grew the jobs table
    unbounded (thousands of stale rows had to be purged from prod)."""

    @pytest.mark.asyncio
    async def test_cleanup_deletes_persisted_rows(self, tmp_path, monkeypatch):
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        from shyfem_ui.models.project import Job

        q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        q._jobs.clear()

        spec = JobSpec(name="old", tool_name="shypre", args=[], working_dir=tmp_path / "w")
        job_id = await q.submit(spec)
        for _ in range(50):
            status = await q.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.1)

        # The row is persisted while the job is retained.
        with dbb.db_session() as db:
            assert db.query(Job).filter(Job.job_uuid == job_id).first() is not None

        # Backdate so cleanup evicts it, then verify the DB row is gone too.
        job = q._jobs[job_id]
        job.completed_at = datetime.now() - timedelta(days=30)
        job.created_at = datetime.now() - timedelta(days=30)
        removed = await q.cleanup_old_jobs(days=7)
        assert removed >= 1

        with dbb.db_session() as db:
            assert db.query(Job).filter(Job.job_uuid == job_id).first() is None

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None

    @pytest.mark.asyncio
    async def test_cleanup_deletes_evicted_db_rows(self, tmp_path, monkeypatch):
        """An old job row that was evicted from the in-memory window (so it is
        NOT in self._jobs) must still be deleted from the DB. This is the
        unbounded-growth bug: cleanup only iterated self._jobs, so once the
        in-memory cap was exceeded the older rows were never purged."""
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        from shyfem_ui.models.project import Job

        q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        q._jobs.clear()  # the old job is NOT in the in-memory window

        old = datetime.now() - timedelta(days=30)
        with dbb.db_session() as db:
            db.add(
                Job(
                    job_uuid="evicted-old-1",
                    name="old job",
                    job_type="shyfem",
                    working_dir="/tmp/x",
                    status=JobStatus.COMPLETED,
                    created_at=old,
                    completed_at=old,
                )
            )
            # A recent row that must survive.
            recent = datetime.now() - timedelta(hours=1)
            db.add(
                Job(
                    job_uuid="recent-db-1",
                    name="recent job",
                    job_type="shyfem",
                    working_dir="/tmp/x",
                    status=JobStatus.COMPLETED,
                    created_at=recent,
                    completed_at=recent,
                )
            )
            db.commit()

        assert "evicted-old-1" not in q._jobs
        removed = await q.cleanup_old_jobs(days=7)
        assert removed >= 1

        with dbb.db_session() as db:
            assert db.query(Job).filter(Job.job_uuid == "evicted-old-1").count() == 0
            assert db.query(Job).filter(Job.job_uuid == "recent-db-1").count() == 1

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None
