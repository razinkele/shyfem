"""Periodic maintenance: prune old jobs/workflows and expired auth sessions/WS tokens.

These cleanups (``JobQueue.cleanup_old_jobs`` and
``AuthService.cleanup_expired_sessions``) are implemented and tested but had no
caller, so the ``jobs``/``auth_sessions``/``ws_auth_tokens`` tables grew
unbounded (2026-06-08 unwired audit, P1). This module schedules them.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_maintenance_once(
    job_queue,
    auth_service,
    job_retention_days: int,
    *,
    audit_service=None,
    audit_retention_days: int = 365,
    feedback_service=None,
    feedback_retention_days: int = 180,
    workflow_cleanup=None,
) -> None:
    """Run one maintenance pass: prune old jobs, expired sessions/tokens, old
    audit logs, old feedback submissions, and old finished workflows.

    ``workflow_cleanup`` (``WorkflowEngine.cleanup_old_workflows`` in prod) is
    called with ``job_retention_days``: workflows share the job retention
    window. It runs AFTER ``cleanup_old_jobs``, whose first use reconciles
    phantom active job rows, so a dead job never pins its workflow (L37).

    Each cleanup is independent — a failure in one is logged and must not block
    the others or propagate (the scheduling loop must never die).
    """
    try:
        removed = await job_queue.cleanup_old_jobs(days=job_retention_days)
        if removed:
            logger.info("maintenance: pruned %d job(s) older than %dd", removed, job_retention_days)
    except Exception:
        logger.exception("maintenance: cleanup_old_jobs failed")

    if workflow_cleanup is not None:
        try:
            # Synchronous DB delete — keep it off the event loop.
            removed = await asyncio.to_thread(workflow_cleanup, job_retention_days)
            if removed:
                logger.info(
                    "maintenance: pruned %d workflow(s) older than %dd",
                    removed,
                    job_retention_days,
                )
        except Exception:
            logger.exception("maintenance: cleanup_old_workflows failed")

    try:
        # cleanup_expired_sessions is synchronous DB work — keep it off the loop.
        removed = await asyncio.to_thread(auth_service.cleanup_expired_sessions)
        if removed:
            logger.info("maintenance: pruned %d expired session(s)/token(s)", removed)
    except Exception:
        logger.exception("maintenance: cleanup_expired_sessions failed")

    if audit_service is not None:
        try:
            # Synchronous DB delete — keep it off the event loop.
            removed = await asyncio.to_thread(audit_service.cleanup_old_logs, audit_retention_days)
            if removed:
                logger.info(
                    "maintenance: pruned %d audit log(s) older than %dd",
                    removed,
                    audit_retention_days,
                )
        except Exception:
            logger.exception("maintenance: cleanup_old_logs failed")

    if feedback_service is not None:
        try:
            # Synchronous DB delete — keep it off the event loop.
            removed = await asyncio.to_thread(feedback_service.cleanup_old, feedback_retention_days)
            if removed:
                logger.info(
                    "maintenance: pruned %d feedback row(s) older than %dd",
                    removed,
                    feedback_retention_days,
                )
        except Exception:
            logger.exception("maintenance: cleanup_old (feedback) failed")


async def run_maintenance_loop(
    job_queue,
    auth_service,
    *,
    interval_s: int,
    job_retention_days: int,
    audit_service=None,
    audit_retention_days: int = 365,
    feedback_service=None,
    feedback_retention_days: int = 180,
    workflow_cleanup=None,
) -> None:
    """Run :func:`run_maintenance_once` every ``interval_s`` seconds, forever.

    Intended to be launched as a background task (see MaintenanceMiddleware) and
    cancelled on shutdown. ``run_maintenance_once`` swallows its own errors, so
    the loop survives transient failures.
    """
    logger.info(
        "maintenance loop started (interval=%ds, job retention=%dd, audit retention=%dd, "
        "feedback retention=%dd)",
        interval_s,
        job_retention_days,
        audit_retention_days,
        feedback_retention_days,
    )
    while True:
        await asyncio.sleep(interval_s)
        await run_maintenance_once(
            job_queue,
            auth_service,
            job_retention_days,
            audit_service=audit_service,
            audit_retention_days=audit_retention_days,
            feedback_service=feedback_service,
            feedback_retention_days=feedback_retention_days,
            workflow_cleanup=workflow_cleanup,
        )
