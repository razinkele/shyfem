"""Tests for local job queue implementation."""

import asyncio
from datetime import datetime, timedelta, timezone
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
    # Start each test with a clean in-memory job set. History now loads
    # lazily (F51) rather than in __init__, so clearing alone would just be
    # undone by the first submit()/list_jobs() reloading the shared test
    # DB's rows -- mark history as already "loaded" too, so that reload
    # never fires and prior tests' rows (which can include RUNNING ones,
    # now that persistence is async via to_thread) never leak in and skew
    # things like active_job_count.
    q._jobs.clear()
    q._history_loaded = True
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
        async def mock_run(
            tool,
            args,
            wd,
            progress_callback=None,
            output_callback=None,
            capture_stdout=True,
            detached=None,
        ):
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

    def test_cancelled_job_sends_no_notification(self, queue):
        """L35: a user-cancelled job must NOT route to notify_job_failed — the
        user gets a false 'simulation failed' email otherwise. Neither the
        success nor the failure notifier should fire on cancellation."""
        from unittest.mock import MagicMock

        notif = MagicMock()
        queue.notification_service = notif
        job = JobInfo(
            id="cancel-1",
            name="cancelled job",
            tool_name="shyfem",
            args=[],
            working_dir="/tmp",
            status=JobStatus.CANCELLED,
        )

        queue._send_completion_notification(job)

        notif.notify_job_failed.assert_not_called()
        notif.notify_job_success.assert_not_called()


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
    """If the run cannot be set up (the job's log files cannot be opened: disk
    full, permissions), the job must end FAILED and the running-count must be
    released. Previously touch()/open() ran OUTSIDE the try/finally, so a
    failure left the job stuck RUNNING and leaked _running_count (eventually
    wedging the queue). Since J-01 the files are opened while the supervisor
    is launched, inside the wrapper call, so the failure arrives as an
    exception from that call."""

    @pytest.mark.asyncio
    async def test_stdout_open_failure_marks_failed_and_releases_count(self, queue, job_spec):
        queue.wrapper.run_command = AsyncMock(side_effect=OSError("disk full"))

        job_id = await queue.submit(job_spec)
        for _ in range(50):
            status = await queue.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.05)

        status = await queue.get_status(job_id)
        assert status.status == JobStatus.FAILED
        assert "disk full" in status.error_message
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

    @pytest.mark.asyncio
    async def test_created_at_purge_uses_utc_cutoff(self, tmp_path, monkeypatch):
        """L39: Job.created_at is server_default=func.now() (UTC). The DB purge
        must compare it against a UTC cutoff. Simulate a non-UTC server (local
        clock 15 days ahead of UTC): a row created 3 days ago in UTC, with
        completed_at=NULL so only the created_at branch applies, is WITHIN a
        7-day retention window and must survive. A naive-local cutoff would sit
        ahead of the row and wrongly purge it."""
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb
        import shyfem_ui.services.job_local as job_local_mod

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        from shyfem_ui.models.project import Job

        real_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        class _SkewedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return real_utc + timedelta(days=15)

            @classmethod
            def utcnow(cls):
                return real_utc

        monkeypatch.setattr(job_local_mod, "datetime", _SkewedDateTime)
        monkeypatch.setattr(job_local_mod, "utcnow", lambda: real_utc)

        q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        q._jobs.clear()  # row is outside the in-memory window
        # Skip history reload so the row stays DB-only and is exercised by the
        # _delete_old_db_rows path (the unbounded-growth purge for rows beyond
        # the in-memory cap), not the in-memory pass.
        q._history_loaded = True

        with dbb.db_session() as db:
            db.add(
                Job(
                    job_uuid="created-3d-ago",
                    name="within retention",
                    job_type="shyfem",
                    working_dir="/tmp/x",
                    status=JobStatus.COMPLETED,
                    created_at=real_utc - timedelta(days=3),
                    completed_at=None,
                )
            )
            db.commit()

        await q.cleanup_old_jobs(days=7)

        with dbb.db_session() as db:
            assert db.query(Job).filter(Job.job_uuid == "created-3d-ago").count() == 1

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None


class TestDbRowToJobInfoOutputFiles:
    """_db_row_to_job_info must restore output_files from the ``jobs.output_files``
    column (migration 7e41388e2c8d), tolerating NULL or non-list values as []
    (N40 -- the column was added but never read back)."""

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
            session_id=None,
            user_id=None,
            project_id=None,
            output_files=None,
        )
        base.update(over)
        return SimpleNamespace(**base)

    def test_null_output_files_becomes_empty_list(self):
        info = LocalJobQueue._db_row_to_job_info(self._row(output_files=None))
        assert info.output_files == []

    def test_invalid_output_files_becomes_empty_list(self):
        info = LocalJobQueue._db_row_to_job_info(self._row(output_files="not-a-list"))
        assert info.output_files == []

    def test_valid_output_files_round_trip(self):
        info = LocalJobQueue._db_row_to_job_info(
            self._row(output_files=["/tmp/a.shy", "/tmp/b.ext"])
        )
        assert info.output_files == ["/tmp/a.shy", "/tmp/b.ext"]


class TestOutputFilesPersistence:
    """jobs.output_files (migration 7e41388e2c8d) must round-trip through
    _persist_job and survive a fresh LocalJobQueue reload (simulated server
    restart) -- previously the column existed but was never written (N40),
    so restarts silently lost every job's output-file list."""

    @pytest.mark.asyncio
    async def test_output_files_persist_and_reload(self, tmp_path, monkeypatch, mock_wrapper):
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        expected_files = [str(tmp_path / "out.shy"), str(tmp_path / "out.ext")]
        mock_wrapper.run_command.return_value = CommandResult(
            success=True,
            return_code=0,
            stdout="",
            stderr="",
            command="test",
            working_dir=str(tmp_path),
            duration=1.0,
            output_files=expected_files,
        )

        q1 = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        q1.wrapper = mock_wrapper
        q1._jobs.clear()

        spec = JobSpec(name="out", tool_name="shypre", args=[], working_dir=tmp_path / "w")
        job_id = await q1.submit(spec)
        for _ in range(50):
            status = await q1.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.05)

        status = await q1.get_status(job_id)
        assert status.status == JobStatus.COMPLETED
        assert sorted(status.output_files) == sorted(expected_files)

        # The persisted DB row itself must carry output_files (not just the
        # in-memory JobInfo) -- assert directly against the ORM column.
        from shyfem_ui.models.project import Job

        with dbb.db_session() as db:
            row = db.query(Job).filter(Job.job_uuid == job_id).first()
            assert row is not None
            assert sorted(row.output_files) == sorted(expected_files)

        # Simulate a server restart: a brand-new LocalJobQueue reloading from
        # the same DB must restore output_files, not silently drop them.
        # History now loads lazily (F51) -- get_status is the guaranteed
        # trigger, not raw attribute access on the fresh instance.
        q2 = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        reloaded = await q2.get_status(job_id)
        assert reloaded is not None
        assert sorted(reloaded.output_files) == sorted(expected_files)

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None

    @pytest.mark.asyncio
    async def test_no_output_files_persists_as_empty_list(
        self, tmp_path, monkeypatch, mock_wrapper
    ):
        """A job that produced no output files persists (and reloads) as []
        rather than NULL, keeping downstream consumers (workflow chaining,
        run.py's output-file list) list-shaped."""
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs2.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        q.wrapper = mock_wrapper
        q._jobs.clear()

        spec = JobSpec(name="empty", tool_name="shypre", args=[], working_dir=tmp_path / "w")
        job_id = await q.submit(spec)
        for _ in range(50):
            status = await q.get_status(job_id)
            if status and not status.is_active:
                break
            await asyncio.sleep(0.05)

        from shyfem_ui.models.project import Job

        with dbb.db_session() as db:
            row = db.query(Job).filter(Job.job_uuid == job_id).first()
            assert row.output_files == []

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None


class TestAsyncHygieneF22F51:
    """F22: every persistence write reachable from an async def must be
    offloaded via asyncio.to_thread -- a bare synchronous call blocks the
    event loop (and every other concurrent session) for the duration of the
    DB write. F51: __init__ must not run the (also synchronous) history-load
    query either -- it may run before any event loop exists (app startup) or
    on one (async tests/sessions), and either way a bare call there blocks
    whoever is waiting on construction. Both are locked so a future edit
    can't quietly reintroduce a blocking call on an async path."""

    def test_no_bare_persist_job_call_on_async_paths(self):
        """Source-scan (AST) lock, mirroring tests/test_dead_controls_wired.py's
        style: walk job_local.py's AST and flag every `self._persist_job(...)`
        CALL node (parens directly after the attribute) that is textually
        inside an `async def`. The offloaded form -- `await asyncio.to_thread(
        self._persist_job, job)` -- passes `self._persist_job` as a bare
        attribute reference (an argument, not a call), so it never produces a
        Call node here; only a genuine straggler does."""
        import ast
        import inspect

        import shyfem_ui.services.job_local as job_local_mod

        source = inspect.getsource(job_local_mod)
        tree = ast.parse(source)

        # Functions allowed to call _persist_job synchronously because they
        # only ever run fully off the event loop already (e.g. a sync-only
        # helper invoked exclusively via asyncio.to_thread, never awaited
        # directly). Empty today -- kept so a legitimate future sync-only
        # helper doesn't have to fight this lock.
        SYNC_ALLOWLIST: set[str] = set()

        violations = []

        class _Visitor(ast.NodeVisitor):
            def __init__(self):
                self.stack: list[ast.AST] = []

            def _enter(self, node):
                self.stack.append(node)
                self.generic_visit(node)
                self.stack.pop()

            def visit_AsyncFunctionDef(self, node):
                self._enter(node)

            def visit_FunctionDef(self, node):
                self._enter(node)

            def visit_Call(self, node):
                func = node.func
                is_persist_job_call = (
                    isinstance(func, ast.Attribute)
                    and func.attr == "_persist_job"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "self"
                )
                if is_persist_job_call and self.stack:
                    enclosing = self.stack[-1]
                    if (
                        isinstance(enclosing, ast.AsyncFunctionDef)
                        and enclosing.name not in SYNC_ALLOWLIST
                    ):
                        violations.append((enclosing.name, node.lineno))
                self.generic_visit(node)

        _Visitor().visit(tree)
        assert not violations, (
            "bare self._persist_job(...) call(s) inside async def, not "
            f"offloaded via asyncio.to_thread: {violations}"
        )

    def test_no_bare_db_purge_call_on_async_paths(self):
        """L38: cleanup_old_jobs is awaited directly by maintenance.py (unlike
        the sibling cleanups, which use to_thread). Its synchronous DB-purge
        helpers (_delete_old_db_rows / _delete_job_rows) do an unbounded scan +
        per-row delete and must run off the event loop. The offloaded form
        ``await asyncio.to_thread(self._delete_old_db_rows, ...)`` passes the
        method as a bare attribute (an argument, not a Call), so only a
        straggler direct call produces a Call node here."""
        import ast
        import inspect

        import shyfem_ui.services.job_local as job_local_mod

        source = inspect.getsource(job_local_mod)
        tree = ast.parse(source)
        targets = {"_delete_old_db_rows", "_delete_job_rows"}
        violations = []

        class _Visitor(ast.NodeVisitor):
            def __init__(self):
                self.stack: list[ast.AST] = []

            def _enter(self, node):
                self.stack.append(node)
                self.generic_visit(node)
                self.stack.pop()

            def visit_AsyncFunctionDef(self, node):
                self._enter(node)

            def visit_FunctionDef(self, node):
                self._enter(node)

            def visit_Call(self, node):
                func = node.func
                is_target = (
                    isinstance(func, ast.Attribute)
                    and func.attr in targets
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "self"
                )
                if is_target and self.stack and isinstance(self.stack[-1], ast.AsyncFunctionDef):
                    violations.append((self.stack[-1].name, func.attr, node.lineno))
                self.generic_visit(node)

        _Visitor().visit(tree)
        assert not violations, (
            "bare synchronous DB-purge call(s) inside async def, not offloaded "
            f"via asyncio.to_thread: {violations}"
        )

    @pytest.mark.asyncio
    async def test_construction_and_first_history_load_do_not_block_event_loop(
        self, tmp_path, monkeypatch
    ):
        """F51: simulate a slow synchronous DB by monkeypatching
        _load_history_from_db to sleep. Prove (a) __init__ returns near-
        instantly regardless (it must not call the slow method at all), and
        (b) the eventual load -- triggered by the first public call that
        needs job history -- still lets a concurrently scheduled coroutine
        keep ticking, i.e. the slow work runs off the event loop
        (asyncio.to_thread), not inline on it."""
        import time

        def slow_load(self):
            time.sleep(0.4)  # simulate a slow synchronous DB query
            return []

        monkeypatch.setattr(LocalJobQueue, "_load_history_from_db", slow_load)

        t0 = time.monotonic()
        queue = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        construction_time = time.monotonic() - t0
        assert construction_time < 0.1, (
            f"constructor blocked for {construction_time:.3f}s -- history "
            "load must not run synchronously in __init__ (F51)"
        )

        ticks = []

        async def ticker():
            for _ in range(30):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        ticker_task = asyncio.create_task(ticker())
        await queue.list_jobs()  # first public entry -- triggers the deferred load
        ticker_task.cancel()
        try:
            await ticker_task
        except asyncio.CancelledError:
            pass

        assert len(ticks) >= 5, (
            "the event loop was starved while history loaded -- the slow "
            "DB query must run via asyncio.to_thread, not inline on the "
            "loop (F51)"
        )

    def test_load_history_from_db_does_not_mutate_jobs_dict(self, tmp_path, monkeypatch):
        """Cross-thread race guard: _load_history_from_db runs on a worker
        thread (via _ensure_history_loaded's asyncio.to_thread) while an
        unlocked sync reader such as active_job_count can be iterating
        self._jobs.values() concurrently on the event-loop thread. If
        _load_history_from_db wrote self._jobs directly (as it did before
        this task), that would race and could raise "dictionary changed
        size during iteration". It must only READ the DB and RETURN the
        rows; the merge into self._jobs happens back on the event-loop
        thread in _ensure_history_loaded.

        Uses its own fresh temp DB (seeded with one row) rather than the
        shared session DB: against a possibly-empty shared DB this test
        would pass vacuously (nothing loaded => nothing to detect) even
        with the old, mutating implementation. Seeding a row makes the
        assertion have teeth -- if _load_history_from_db still wrote
        self._jobs directly, `queue._jobs == before` below would fail.
        """
        import shyfem_ui.config as cfg
        import shyfem_ui.db.base as dbb

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'race.db'}")
        monkeypatch.setattr(cfg, "_config", None)
        monkeypatch.setattr(dbb, "_engine", None)
        monkeypatch.setattr(dbb, "_SessionLocal", None)
        dbb.init_db()

        from shyfem_ui.models.project import Job

        with dbb.db_session() as db:
            db.add(
                Job(
                    job_uuid="seed-1",
                    name="seeded",
                    job_type="shypre",
                    working_dir="/tmp/w",
                    status=JobStatus.COMPLETED,
                    completed_at=datetime.now(),
                )
            )

        queue = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        before = dict(queue._jobs)

        result = queue._load_history_from_db()

        assert [info.id for info in result] == ["seed-1"], "seeded row was not returned"
        assert all(isinstance(info, JobInfo) for info in result)
        assert queue._jobs == before, "_load_history_from_db must not touch self._jobs itself"

        dbb._engine = None
        dbb._SessionLocal = None
        cfg._config = None


class TestJobEvents:
    """The local queue publishes every status change, so sessions push
    instead of polling (Shiny 1.9)."""

    _TERMINAL = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    @staticmethod
    async def _settle(queue, job_id):
        """Wait for the job's own task to end (submit stores it before returning)."""
        task = queue._tasks.get(job_id)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)

    @pytest.mark.asyncio
    async def test_the_local_queue_supports_events(self, queue):
        assert queue.supports_events is True

    @pytest.mark.asyncio
    async def test_a_job_reports_queued_running_and_exactly_one_terminal_event(
        self, queue, job_spec
    ):
        seen = []
        queue.add_event_callback("s", seen.append)
        job_spec.metadata = {"user_id": 7, "project_id": 3}
        job_id = await queue.submit(job_spec)
        await self._settle(queue, job_id)
        mine = [e for e in seen if e.job_id == job_id and e.kind == "status"]
        statuses = [e.status for e in mine]
        assert statuses.index(JobStatus.QUEUED) < statuses.index(JobStatus.RUNNING)
        assert statuses.index(JobStatus.RUNNING) < statuses.index(JobStatus.COMPLETED)
        terminal = [e for e in mine if e.status in self._TERMINAL]
        assert len(terminal) == 1
        ev = terminal[0]
        assert ev.status == JobStatus.COMPLETED and ev.previous == JobStatus.RUNNING
        assert (ev.name, ev.user_id, ev.project_id) == ("test_job", 7, 3)

    @pytest.mark.asyncio
    async def test_a_cancel_reports_exactly_one_cancelled_event(self, queue, tmp_path):
        started = asyncio.Event()

        async def slow_command(*args, **kwargs):
            started.set()
            await asyncio.sleep(10)
            return CommandResult(
                success=True,
                return_code=0,
                stdout="",
                stderr="",
                command="t",
                working_dir=str(tmp_path),
            )

        queue.wrapper.run_command = slow_command
        seen = []
        queue.add_event_callback("s", seen.append)
        spec = JobSpec(name="slow", tool_name="shypre", args=["t.str"], working_dir=tmp_path / "w")
        job_id = await queue.submit(spec)
        await asyncio.wait_for(started.wait(), timeout=5.0)
        assert await queue.cancel(job_id) is True
        await self._settle(queue, job_id)
        terminal = [e for e in seen if e.job_id == job_id and e.status in self._TERMINAL]
        assert [e.status for e in terminal] == [JobStatus.CANCELLED]

    @pytest.mark.asyncio
    async def test_progress_is_an_event_too(self, queue, tmp_path):
        async def mock_run(
            tool,
            args,
            wd,
            progress_callback=None,
            output_callback=None,
            capture_stdout=True,
            detached=None,
        ):
            if progress_callback:
                progress_callback(0.5, "halfway")
            return CommandResult(
                success=True, return_code=0, stdout="", stderr="", command="t", working_dir=str(wd)
            )

        queue.wrapper.run_command = mock_run
        seen = []
        queue.add_event_callback("s", seen.append)
        spec = JobSpec(name="p", tool_name="shypre", args=["t.str"], working_dir=tmp_path / "w")
        job_id = await queue.submit(spec)
        await self._settle(queue, job_id)
        progress = [e for e in seen if e.job_id == job_id and e.kind == "progress"]
        assert progress and progress[0].progress == 0.5 and progress[0].message == "halfway"


@pytest.mark.asyncio
async def test_a_cancel_that_lost_the_race_announces_the_status_that_stands(queue, tmp_path):
    """The supervisor recorded the end first: cancel() adopts it and the one
    terminal event says what the job ended as, not 'cancelled'."""
    started = asyncio.Event()

    async def slow_command(*args, **kwargs):
        started.set()
        await asyncio.sleep(10)

    queue.wrapper.run_command = slow_command
    seen = []
    queue.add_event_callback("s", seen.append)
    spec = JobSpec(name="race", tool_name="shypre", args=["t.str"], working_dir=tmp_path / "w")
    job_id = await queue.submit(spec)
    await asyncio.wait_for(started.wait(), timeout=5.0)

    def adopt_completed(job):
        job.status = JobStatus.COMPLETED

    queue._finalize_row = lambda job: False
    queue._adopt_row = adopt_completed
    assert await queue.cancel(job_id) is False
    await asyncio.sleep(0.05)
    ended = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
    terminal = [e.status for e in seen if e.job_id == job_id and e.status in ended]
    assert terminal == [JobStatus.COMPLETED]


def test_a_job_announces_its_end_once_whatever_races_to_announce_it(queue):
    from shyfem_ui.services.job_queue import JobInfo

    seen = []
    queue.add_event_callback("s", seen.append)
    job = JobInfo(
        id="j", name="n", tool_name="t", args=[], working_dir="/w", status=JobStatus.CANCELLED
    )
    queue._emit(job, JobStatus.RUNNING)
    queue._emit(job, JobStatus.QUEUED)  # a stale transition after an await
    job.status = JobStatus.COMPLETED
    queue._emit(job, JobStatus.RUNNING)  # the other side of a race
    assert [(e.status, e.previous) for e in seen] == [(JobStatus.CANCELLED, JobStatus.RUNNING)]


def test_progress_events_are_throttled_per_job(queue):
    from shyfem_ui.services.job_queue import JobInfo

    seen = []
    queue.add_event_callback("s", seen.append)
    job = JobInfo(
        id="p", name="n", tool_name="t", args=[], working_dir="/w", status=JobStatus.RUNNING
    )
    for i in range(50):
        queue._emit(job, kind="progress", progress=i / 50)
    assert len(seen) == 1
