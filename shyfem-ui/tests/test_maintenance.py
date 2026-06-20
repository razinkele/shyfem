"""Tests for the periodic maintenance loop (cleanup_old_jobs + expired sessions).

These tasks exist and are correct but were never invoked (2026-06-08 unwired
audit, P1). The loop wires them to a periodic schedule.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _mocks(job_n=0, sess_n=0):
    jq = MagicMock()
    jq.cleanup_old_jobs = AsyncMock(return_value=job_n)
    auth = MagicMock()
    auth.cleanup_expired_sessions = MagicMock(return_value=sess_n)
    return jq, auth


class TestRunMaintenanceOnce:
    @pytest.mark.asyncio
    async def test_calls_both_cleanups_with_config(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq, auth = _mocks(job_n=3, sess_n=2)
        await run_maintenance_once(jq, auth, job_retention_days=30)
        jq.cleanup_old_jobs.assert_awaited_once_with(days=30)
        auth.cleanup_expired_sessions.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_job_failure_does_not_block_session_cleanup_or_raise(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq, auth = _mocks()
        jq.cleanup_old_jobs = AsyncMock(side_effect=RuntimeError("boom"))
        await run_maintenance_once(jq, auth, job_retention_days=7)  # must NOT raise
        auth.cleanup_expired_sessions.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_failure_does_not_raise(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq, auth = _mocks()
        auth.cleanup_expired_sessions = MagicMock(side_effect=RuntimeError("db"))
        await run_maintenance_once(jq, auth, job_retention_days=7)  # must NOT raise
        jq.cleanup_old_jobs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prunes_audit_logs_when_audit_service_given(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq, auth = _mocks()
        audit = MagicMock()
        audit.cleanup_old_logs = MagicMock(return_value=5)
        await run_maintenance_once(
            jq, auth, job_retention_days=30, audit_service=audit, audit_retention_days=365
        )
        audit.cleanup_old_logs.assert_called_once_with(365)

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_block_or_raise(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq, auth = _mocks()
        audit = MagicMock()
        audit.cleanup_old_logs = MagicMock(side_effect=RuntimeError("db"))
        # must NOT raise; jobs + sessions still run
        await run_maintenance_once(jq, auth, job_retention_days=7, audit_service=audit)
        jq.cleanup_old_jobs.assert_awaited_once()
        auth.cleanup_expired_sessions.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_audit_service_skips_audit_cleanup(self):
        from shyfem_ui.services.maintenance import run_maintenance_once

        jq, auth = _mocks()
        # audit_service omitted -> no audit pruning, no error (backward compatible)
        await run_maintenance_once(jq, auth, job_retention_days=7)
        jq.cleanup_old_jobs.assert_awaited_once()


class TestCreateAppWiring:
    """create_app wires MaintenanceMiddleware with a live factory in server mode
    (interval>0) and a None factory (pass-through) otherwise."""

    def test_server_mode_wires_factory(self, monkeypatch):
        monkeypatch.setenv("SHYFEM_UI_DEPLOYMENT_MODE", "server")
        monkeypatch.setenv("SHYFEM_UI_DEFAULT_ADMIN_PASSWORD", "pw-strong-123")
        import shyfem_ui.config as cfg

        monkeypatch.setattr(cfg, "_config", None)
        from shyfem_ui.app import create_app
        from shyfem_ui.middleware.maintenance import MaintenanceMiddleware

        app = create_app(cfg.Config())
        inner = app.app  # HealthCheckMiddleware is outermost; Maintenance is just inside
        assert isinstance(inner, MaintenanceMiddleware)
        assert inner._task_factory is not None

    def test_server_mode_interval_zero_disables(self, monkeypatch):
        monkeypatch.setenv("SHYFEM_UI_DEPLOYMENT_MODE", "server")
        monkeypatch.setenv("SHYFEM_UI_DEFAULT_ADMIN_PASSWORD", "pw-strong-123")
        monkeypatch.setenv("SHYFEM_UI_MAINTENANCE_INTERVAL_SECONDS", "0")
        import shyfem_ui.config as cfg

        monkeypatch.setattr(cfg, "_config", None)
        from shyfem_ui.app import create_app
        from shyfem_ui.middleware.maintenance import MaintenanceMiddleware

        app = create_app(cfg.Config())
        inner = app.app
        assert isinstance(inner, MaintenanceMiddleware)
        assert inner._task_factory is None

    def test_local_mode_no_factory(self):
        from shyfem_ui.app import create_app
        from shyfem_ui.config import Config
        from shyfem_ui.middleware.maintenance import MaintenanceMiddleware

        app = create_app(Config(deployment_mode="local"))
        inner = app.app
        assert isinstance(inner, MaintenanceMiddleware)
        assert inner._task_factory is None


class TestRunMaintenanceLoop:
    @pytest.mark.asyncio
    async def test_loop_ticks_then_cancellable(self):
        from shyfem_ui.services.maintenance import run_maintenance_loop

        jq, auth = _mocks()
        task = asyncio.ensure_future(
            run_maintenance_loop(jq, auth, interval_s=0.01, job_retention_days=30)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert jq.cleanup_old_jobs.await_count >= 1
        assert auth.cleanup_expired_sessions.call_count >= 1
