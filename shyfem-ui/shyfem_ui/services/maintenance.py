"""Periodic maintenance: prune old jobs and expired auth sessions/WS tokens.

These cleanups (``JobQueue.cleanup_old_jobs`` and
``AuthService.cleanup_expired_sessions``) are implemented and tested but had no
caller, so the ``jobs``/``auth_sessions``/``ws_auth_tokens`` tables grew
unbounded (2026-06-08 unwired audit, P1). This module schedules them.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_maintenance_once(job_queue, auth_service, job_retention_days: int) -> None:
    """Run one maintenance pass: prune old jobs, then expired sessions/tokens.

    The two cleanups are independent — a failure in one is logged and must not
    block the other or propagate (the scheduling loop must never die).
    """
    try:
        removed = await job_queue.cleanup_old_jobs(days=job_retention_days)
        if removed:
            logger.info("maintenance: pruned %d job(s) older than %dd", removed, job_retention_days)
    except Exception:
        logger.exception("maintenance: cleanup_old_jobs failed")

    try:
        # cleanup_expired_sessions is synchronous DB work — keep it off the loop.
        removed = await asyncio.to_thread(auth_service.cleanup_expired_sessions)
        if removed:
            logger.info("maintenance: pruned %d expired session(s)/token(s)", removed)
    except Exception:
        logger.exception("maintenance: cleanup_expired_sessions failed")


async def run_maintenance_loop(
    job_queue, auth_service, *, interval_s: int, job_retention_days: int
) -> None:
    """Run :func:`run_maintenance_once` every ``interval_s`` seconds, forever.

    Intended to be launched as a background task (see MaintenanceMiddleware) and
    cancelled on shutdown. ``run_maintenance_once`` swallows its own errors, so
    the loop survives transient failures.
    """
    logger.info(
        "maintenance loop started (interval=%ds, job retention=%dd)",
        interval_s,
        job_retention_days,
    )
    while True:
        await asyncio.sleep(interval_s)
        await run_maintenance_once(job_queue, auth_service, job_retention_days)
