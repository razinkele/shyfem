"""Tests for job ownership: no disconnect-cancel coupling, orphan reconciliation
at startup, and per-user job listing in server mode.

Covers three review findings (2026-07-18 full codebase deep review):

- N13 (jobs belong to users, not WebSocket sessions — a session ending must
  never cancel a still-running job).
- N46 (phantom RUNNING/QUEUED/PENDING rows left behind by a previous process
  must be reconciled to FAILED at startup, not left "active" forever).
- F17 (server-mode job listing must be scoped by the server-validated user
  identity, not the ephemeral per-WS-connection session id).
"""

from datetime import datetime

import pytest


class TestNoDisconnectCancelCoupling:
    """N13: jobs are owned by users, not WebSocket sessions. A session ending
    (browser refresh, network blip, laptop sleep) must never cancel a running
    job — jobs only end by completing, explicit cancel, or reconciliation.

    N13's fix is a deletion (the disconnect->cancel wiring), so it cannot be
    proven by driving app.py's session.on_ended closure behaviorally — that
    closure lives inside _build_server and requires a live Shiny session
    (confirmed empirically: constructing it outside a real session raises
    RuntimeError / cascades into Shiny's module-scope internals). Instead we
    assert, structurally, that the coupling is gone — the same pattern
    test_app_wiring.py uses for wiring regressions.
    """

    def test_cancel_active_jobs_for_session_removed_from_job_queue(self):
        """The disconnect->cancel helper must no longer exist in job_queue —
        nothing else needs it once its only caller (app.py's session-end hook)
        is removed."""
        import shyfem_ui.services.job_queue as job_queue_mod

        assert not hasattr(job_queue_mod, "cancel_active_jobs_for_session"), (
            "cancel_active_jobs_for_session must be deleted — no session-end "
            "code path may cancel jobs (N13)"
        )

    def test_app_does_not_import_cancel_active_jobs_for_session(self):
        """app.py must not import the (deleted) disconnect->cancel helper."""
        import shyfem_ui.app as app_mod

        assert not hasattr(app_mod, "cancel_active_jobs_for_session"), (
            "app.py must not import cancel_active_jobs_for_session — the "
            "session-end hook that called it must be removed (N13)"
        )

    def test_app_source_has_no_session_end_cancel_coupling(self):
        """Belt-and-suspenders against re-introduction under a different name:
        app.py's source must not call job_queue.cancel(...) or list_jobs(...)
        from a session.on_ended-registered callback."""
        import inspect

        import shyfem_ui.app as app_mod

        source = inspect.getsource(app_mod)
        assert "cancel_active_jobs_for_session" not in source


class TestOrphanReconciliation:
    """N46: rows persisted in an active status (PENDING/QUEUED/RUNNING) by a
    previous process are phantoms in a freshly constructed queue — by
    definition there is no live asyncio task for them. _load_history_from_db
    must reconcile them to FAILED with error "orphaned at server restart" and
    persist the correction back to the DB.
    """

    @pytest.fixture
    def db_factory(self, tmp_path, monkeypatch):
        """A real (temp, file-backed) SQLite DB wired into shyfem_ui.db.base,
        so _load_history_from_db exercises the actual persistence path."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import shyfem_ui.db.base as dbbase
        from shyfem_ui.db.base import Base

        # Import every model module BEFORE create_all — SQLAlchemy only
        # registers a declarative class's table on Base.metadata when its
        # module is imported, so Job's table (and its user_id/project_id FK
        # targets) would silently be missing from a bare Base.metadata if
        # shyfem_ui.models.project/user were not yet loaded in this process.
        from shyfem_ui.models import project, user  # noqa: F401

        engine = create_engine(f"sqlite:///{tmp_path / 'reconcile.db'}")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(dbbase, "_SessionLocal", factory)
        return factory

    def _make_row(self, factory, **overrides):
        from shyfem_ui.models.project import Job
        from shyfem_ui.services.job_queue import JobStatus

        db = factory()
        base = dict(
            job_uuid="row-1",
            name="a job",
            job_type="shyfem",
            command="shyfem x.str",
            working_dir="/tmp/work",
            status=JobStatus.RUNNING,
        )
        base.update(overrides)
        row = Job(**base)
        db.add(row)
        db.commit()
        db.close()

    @pytest.mark.asyncio
    async def test_active_rows_reconciled_to_failed_on_load(self, tmp_path, db_factory):
        from shyfem_ui.services.job_local import LocalJobQueue
        from shyfem_ui.services.job_queue import JobStatus

        self._make_row(db_factory, job_uuid="running-1", status=JobStatus.RUNNING)
        self._make_row(db_factory, job_uuid="queued-1", status=JobStatus.QUEUED)
        self._make_row(db_factory, job_uuid="pending-1", status=JobStatus.PENDING)
        self._make_row(
            db_factory,
            job_uuid="completed-1",
            status=JobStatus.COMPLETED,
            completed_at=datetime.now(),
        )

        queue = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)

        # History now loads lazily (F51) -- list_jobs is the guaranteed
        # trigger, and it must actually surface the (reconciled) history.
        jobs = {j.id: j for j in await queue.list_jobs()}

        for uuid in ("running-1", "queued-1", "pending-1"):
            job = jobs.get(uuid)
            assert job is not None, f"{uuid} was not loaded"
            assert job.status == JobStatus.FAILED, f"{uuid} was not reconciled"
            assert job.error_message == "orphaned at server restart"
            assert not job.is_active

        # A genuinely-completed row must be left untouched.
        completed = jobs.get("completed-1")
        assert completed is not None
        assert completed.status == JobStatus.COMPLETED
        assert completed.error_message is None

    @pytest.mark.asyncio
    async def test_reconciliation_is_persisted_back_to_db(self, tmp_path, db_factory):
        from shyfem_ui.models.project import Job
        from shyfem_ui.services.job_local import LocalJobQueue
        from shyfem_ui.services.job_queue import JobStatus

        self._make_row(db_factory, job_uuid="orphan-1", status=JobStatus.RUNNING)

        queue = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        await queue.list_jobs()  # triggers the (now-lazy) history load

        db = db_factory()
        row = db.query(Job).filter_by(job_uuid="orphan-1").first()
        assert row.status == JobStatus.FAILED
        assert row.error_message == "orphaned at server restart"
        assert row.completed_at is not None
        db.close()


class TestPerUserJobListing:
    """F17: server-mode job listing must filter by the server-validated
    user_id, not the ephemeral per-WS-connection session_id — two different
    users must never see each other's jobs."""

    @pytest.mark.asyncio
    async def test_list_jobs_filters_by_user_id(self, tmp_path):
        from shyfem_ui.services.job_local import LocalJobQueue
        from shyfem_ui.services.job_queue import JobSpec

        queue = LocalJobQueue(shyfem_dir=tmp_path, max_workers=2)
        # Isolate from the shared test DB (F51: history loads lazily, so
        # the clear alone would just be undone by submit()'s first-use
        # load) -- mark it already "loaded" so that never fires.
        queue._jobs.clear()
        queue._history_loaded = True

        from unittest.mock import AsyncMock

        from shyfem_ui.services.shyfem_wrapper import CommandResult

        queue.wrapper = AsyncMock()
        queue.wrapper.run_command = AsyncMock(
            return_value=CommandResult(
                success=True,
                return_code=0,
                stdout="",
                stderr="",
                command="test",
                working_dir=str(tmp_path),
                duration=0.1,
                output_files=[],
            )
        )

        spec_a = JobSpec(
            name="job-a",
            tool_name="shypre",
            args=[],
            working_dir=tmp_path,
            metadata={"user_id": 1},
        )
        spec_b = JobSpec(
            name="job-b",
            tool_name="shypre",
            args=[],
            working_dir=tmp_path,
            metadata={"user_id": 2},
        )
        job_a = await queue.submit(spec_a)
        job_b = await queue.submit(spec_b)

        import asyncio

        for _ in range(50):
            a = await queue.get_status(job_a)
            b = await queue.get_status(job_b)
            if a and not a.is_active and b and not b.is_active:
                break
            await asyncio.sleep(0.05)

        jobs_for_user_1 = await queue.list_jobs(user_id=1)
        ids = {j.id for j in jobs_for_user_1}
        assert job_a in ids
        assert job_b not in ids

        jobs_for_user_2 = await queue.list_jobs(user_id=2)
        ids2 = {j.id for j in jobs_for_user_2}
        assert job_b in ids2
        assert job_a not in ids2
