"""Workflow lifecycle: startup reconciliation + retention pruning (L37).

2026-07-18 deep review (L37): "workflows table has no retention/pruning
anywhere, and RUNNING workflow rows are never reconciled after a restart".

Mirrors the job lifecycle:

- N46 (LocalJobQueue._load_history_from_db): rows left PENDING/RUNNING by a
  previous process are phantoms -- the asyncio task that drove them died with
  that process. They become FAILED with the same "orphaned at server restart"
  wording jobs use.
- cleanup_old_jobs: finished rows older than ``job_retention_days`` are
  deleted. Workflows reuse that same retention setting.

A workflow whose step job is still live is never pruned.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models import project as _p  # noqa: F401 -- register models
from shyfem_ui.models import user as _u  # noqa: F401 -- register models
from shyfem_ui.models.project import Job
from shyfem_ui.models.workflow import Workflow, WorkflowStatus
from shyfem_ui.services.job_queue import JobStatus
from shyfem_ui.services.workflow import (
    WorkflowEngine,
    WorkflowInstance,
    WorkflowStep,
    _pack_steps,
    _row_to_instance,
)
from shyfem_ui.timeutil import utcnow


@pytest.fixture()
def session_factory():
    """Fresh in-memory DB per test; each call opens a NEW session on it, like
    the production sessionmaker (the code under test closes what it opens)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def _add_workflow(
    factory,
    status: WorkflowStatus,
    *,
    age_days: float = 0.0,
    completed: bool = True,
    step_job_ids: dict | None = None,
) -> int:
    """Insert a workflow row whose timestamps are ``age_days`` old (UTC)."""
    ts = utcnow() - timedelta(days=age_days)
    inst = WorkflowInstance(
        id="",
        name=f"wf-{status.value}",
        steps=[WorkflowStep(name="Grid prep", tool_name="shypre")],
        working_dir="",
        status=status,
        step_job_ids=step_job_ids or {},
        metadata={"template": "grid_only", "params": {}},
    )
    with factory() as s:
        row = Workflow(
            name=inst.name,
            template="grid_only",
            status=status,
            steps=_pack_steps(inst),
            created_at=ts,
            updated_at=ts,
            completed_at=ts if completed else None,
        )
        s.add(row)
        s.commit()
        return row.id


def _add_job(factory, job_uuid: str, status: JobStatus) -> None:
    with factory() as s:
        s.add(Job(job_uuid=job_uuid, name="j", job_type="shypre", working_dir="/x", status=status))
        s.commit()


def _get(factory, pk: int) -> Workflow | None:
    with factory() as s:
        row = s.get(Workflow, pk)
        if row is not None:
            s.expunge(row)
        return row


class TestStartupReconciliation:
    """N46 analogue: phantom active workflow rows become FAILED at startup."""

    def test_orphaned_wording_is_shared_with_jobs(self):
        from shyfem_ui.services.job_local import LocalJobQueue
        from shyfem_ui.services.workflow import ORPHANED_ERROR

        assert ORPHANED_ERROR == LocalJobQueue.ORPHANED_ERROR == "orphaned at server restart"

    @pytest.mark.parametrize("status", [WorkflowStatus.RUNNING, WorkflowStatus.PENDING])
    def test_phantom_active_workflow_reconciled_to_failed(self, session_factory, status):
        pk = _add_workflow(session_factory, status, completed=False)

        n = WorkflowEngine.reconcile_orphaned_workflows(session_factory=session_factory)

        assert n == 1
        row = _get(session_factory, pk)
        assert row.status == WorkflowStatus.FAILED
        assert row.completed_at is not None
        # completed_at is UTC like every other workflow timestamp.
        assert abs((row.completed_at - utcnow()).total_seconds()) < 60
        assert _row_to_instance(row).error_message == "orphaned at server restart"
        # Steps survive the rewrite of the JSON column.
        assert [s.name for s in _row_to_instance(row).steps] == ["Grid prep"]

    def test_finished_workflows_untouched(self, session_factory):
        pks = {
            st: _add_workflow(session_factory, st)
            for st in (
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
                WorkflowStatus.PAUSED,
            )
        }
        before = {st: _get(session_factory, pk).completed_at for st, pk in pks.items()}

        assert WorkflowEngine.reconcile_orphaned_workflows(session_factory=session_factory) == 0

        for st, pk in pks.items():
            row = _get(session_factory, pk)
            assert row.status == st
            assert row.completed_at == before[st]

    def test_reconcile_never_raises_on_broken_db(self):
        def broken():
            raise RuntimeError("no db")

        assert WorkflowEngine.reconcile_orphaned_workflows(session_factory=broken) == 0

    def test_create_app_reconciles_at_startup(self, monkeypatch):
        """The reconcile runs once per PROCESS from create_app -- never per
        WorkflowEngine, which pages/run.py builds per Shiny session (a second
        session would otherwise kill another session's live workflow)."""
        calls = []
        monkeypatch.setattr(
            WorkflowEngine,
            "reconcile_orphaned_workflows",
            staticmethod(lambda session_factory=None: calls.append(1) or 0),
        )
        from shyfem_ui.app import create_app
        from shyfem_ui.config import Config

        create_app(Config(deployment_mode="local"))
        assert calls == [1]

    def test_create_app_reconciles_real_db_end_to_end(self):
        """Un-mocked: a phantom RUNNING row in the app's own (conftest temp)
        DB is FAILED after create_app. Both methods swallow errors and return
        0, so only this proves the startup path reaches a real table."""
        from shyfem_ui.app import create_app
        from shyfem_ui.config import Config
        from shyfem_ui.db.base import get_session_factory, init_db

        init_db()
        factory = get_session_factory()
        pk = _add_workflow(factory, WorkflowStatus.RUNNING, completed=False)
        try:
            create_app(Config(deployment_mode="local"))
            row = _get(factory, pk)
            assert row.status == WorkflowStatus.FAILED
            assert _row_to_instance(row).error_message == "orphaned at server restart"
        finally:
            with factory() as s:
                s.query(Workflow).filter(Workflow.id == pk).delete()
                s.commit()

    def test_engine_construction_does_not_reconcile(self, session_factory):
        pk = _add_workflow(session_factory, WorkflowStatus.RUNNING, completed=False)
        WorkflowEngine(MagicMock(), session_factory=session_factory)
        assert _get(session_factory, pk).status == WorkflowStatus.RUNNING


class TestRetentionPruning:
    """cleanup_old_jobs analogue, with the same retention window."""

    @pytest.mark.parametrize(
        "status", [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
    )
    def test_old_finished_workflow_pruned(self, session_factory, status):
        pk = _add_workflow(session_factory, status, age_days=31)

        n = WorkflowEngine.cleanup_old_workflows(30, session_factory=session_factory)

        assert n == 1
        assert _get(session_factory, pk) is None

    def test_old_finished_without_completed_at_pruned_by_created_at(self, session_factory):
        pk = _add_workflow(session_factory, WorkflowStatus.FAILED, age_days=31, completed=False)
        assert WorkflowEngine.cleanup_old_workflows(30, session_factory=session_factory) == 1
        assert _get(session_factory, pk) is None

    def test_recent_finished_workflow_kept(self, session_factory):
        pk = _add_workflow(session_factory, WorkflowStatus.COMPLETED, age_days=29)
        assert WorkflowEngine.cleanup_old_workflows(30, session_factory=session_factory) == 0
        assert _get(session_factory, pk) is not None

    @pytest.mark.parametrize(
        "status", [WorkflowStatus.RUNNING, WorkflowStatus.PENDING, WorkflowStatus.PAUSED]
    )
    def test_old_non_terminal_workflow_never_pruned(self, session_factory, status):
        pk = _add_workflow(session_factory, status, age_days=365)
        assert WorkflowEngine.cleanup_old_workflows(30, session_factory=session_factory) == 0
        assert _get(session_factory, pk) is not None

    @pytest.mark.parametrize("job_status", [JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING])
    def test_finished_workflow_with_live_job_never_pruned(self, session_factory, job_status):
        """A FAILED workflow can still own a live job (e.g. _run_workflow's
        generic except after a successful submit). Never prune it."""
        _add_job(session_factory, "live-job-1", job_status)
        pk = _add_workflow(
            session_factory,
            WorkflowStatus.FAILED,
            age_days=90,
            step_job_ids={"Grid prep": "live-job-1"},
        )
        assert WorkflowEngine.cleanup_old_workflows(30, session_factory=session_factory) == 0
        assert _get(session_factory, pk) is not None

    def test_finished_workflow_with_finished_job_pruned(self, session_factory):
        _add_job(session_factory, "done-job-1", JobStatus.COMPLETED)
        pk = _add_workflow(
            session_factory,
            WorkflowStatus.COMPLETED,
            age_days=90,
            step_job_ids={"Grid prep": "done-job-1"},
        )
        assert WorkflowEngine.cleanup_old_workflows(30, session_factory=session_factory) == 1
        assert _get(session_factory, pk) is None

    def test_cleanup_never_raises_on_broken_db(self):
        def broken():
            raise RuntimeError("no db")

        assert WorkflowEngine.cleanup_old_workflows(30, session_factory=broken) == 0


class TestMaintenanceWiring:
    @pytest.mark.asyncio
    async def test_maintenance_prunes_workflows_with_job_retention(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq = MagicMock()
        jq.cleanup_old_jobs = AsyncMock(return_value=0)
        auth = MagicMock()
        auth.cleanup_expired_sessions = MagicMock(return_value=0)
        wf_cleanup = MagicMock(return_value=2)

        await run_maintenance_once(jq, auth, job_retention_days=30, workflow_cleanup=wf_cleanup)

        wf_cleanup.assert_called_once_with(30)

    @pytest.mark.asyncio
    async def test_workflow_cleanup_failure_does_not_raise(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq = MagicMock()
        jq.cleanup_old_jobs = AsyncMock(return_value=0)
        auth = MagicMock()
        auth.cleanup_expired_sessions = MagicMock(return_value=0)
        wf_cleanup = MagicMock(side_effect=RuntimeError("db"))

        await run_maintenance_once(jq, auth, job_retention_days=7, workflow_cleanup=wf_cleanup)
        auth.cleanup_expired_sessions.assert_called_once()

    def test_server_mode_wires_workflow_cleanup(self, monkeypatch):
        """The live scheduler must receive the workflow cleanup, else it is
        implemented-but-unwired like the pre-fix job/session cleanups."""
        monkeypatch.setenv("SHYFEM_UI_DEPLOYMENT_MODE", "server")
        monkeypatch.setenv("SHYFEM_UI_DEFAULT_ADMIN_PASSWORD", "pw-strong-123")
        import shyfem_ui.config as cfg

        monkeypatch.setattr(cfg, "_config", None)
        import shyfem_ui.services.maintenance as maint_mod

        fake_loop = MagicMock()
        monkeypatch.setattr(maint_mod, "run_maintenance_loop", fake_loop)
        from shyfem_ui.app import create_app

        app = create_app(cfg.Config())
        app.app._task_factory()
        kwargs = fake_loop.call_args.kwargs
        assert kwargs["workflow_cleanup"] == WorkflowEngine.cleanup_old_workflows
        assert kwargs["job_retention_days"] == 30
