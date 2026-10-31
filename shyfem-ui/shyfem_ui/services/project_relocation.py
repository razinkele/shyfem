"""Relocate existing projects under their owners' per-user home sandbox.

Once ``Config.confine_path`` is enforced in server mode, a project whose
``work_dir`` lives under the shared ``work_dir`` (instead of
``user_data_root/{username}/``) becomes unreachable by its owner. This module
plans and applies the one-time relocation.

The planning step (:func:`plan_relocations`) is pure and unit-tested; the
filesystem move + DB update (:func:`apply_relocations`) is driven by that
vetted plan, supports a dry run, and is idempotent (re-running skips projects
already under their owner's home).
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)


def plan_relocations(
    projects: Iterable[dict],
    *,
    user_data_root: Path | str,
    busy_project_ids: Iterable[int] = (),
) -> list[dict]:
    """Compute relocation plans for a set of projects.

    Args:
        projects: dicts with keys ``id``, ``work_dir``, ``owner_username``.
        user_data_root: configured per-user data root.
        busy_project_ids: projects with a job or workflow still pending,
            queued or running (see :func:`busy_project_ids`); a move for one
            of them becomes ``"skip-active-jobs"`` (H-10).

    Returns:
        One plan dict per project: ``{id, src, dst, action}`` where ``action``
        is ``"move"`` (relocate src -> dst), ``"skip-already-home"`` (already in
        the owner's sandbox), ``"skip-orphan"`` (no owner username — left in
        place and flagged for manual handling), or ``"skip-active-jobs"``
        (a job or workflow is still using the folder — re-run once it ends).
    """
    root = Path(user_data_root).resolve()
    busy = set(busy_project_ids)
    plans: list[dict] = []

    for proj in projects:
        pid = proj["id"]
        src = Path(proj["work_dir"]).resolve()
        owner = proj.get("owner_username")

        if not owner:
            plans.append({"id": pid, "src": str(src), "dst": None, "action": "skip-orphan"})
            continue

        home = (root / owner).resolve()
        if src == home or str(src).startswith(str(home) + "/"):
            plans.append(
                {"id": pid, "src": str(src), "dst": str(src), "action": "skip-already-home"}
            )
            continue

        # Use only the basename so a pathological stored path cannot relocate
        # outside the owner's home.
        dst = (home / src.name).resolve()
        action = "skip-active-jobs" if pid in busy else "move"
        plans.append({"id": pid, "src": str(src), "dst": str(dst), "action": action})

    return plans


def busy_project_ids(db, projects: Iterable[dict]) -> set[int]:
    """Ids of the projects whose folder a job or workflow is still using.

    A job counts while it is pending, queued or running, matched by its
    ``project_id`` or, for a row without one, by a ``working_dir`` inside the
    project's folder; a workflow counts while it is pending or running.
    Moving such a folder pulls it out from under the running tool (H-10).

    Args:
        db: an open SQLAlchemy session.
        projects: dicts with keys ``id`` and ``work_dir``.
    """
    from shyfem_ui.models.project import Job
    from shyfem_ui.models.workflow import Workflow, WorkflowStatus
    from shyfem_ui.services.job_detached import ACTIVE_STATUSES

    projects = list(projects)
    ids = {p["id"] for p in projects}
    busy: set[int] = set()

    job_rows = (
        db.query(Job.project_id, Job.working_dir).filter(Job.status.in_(ACTIVE_STATUSES)).all()
    )
    folders = [(p["id"], Path(p["work_dir"]).resolve()) for p in projects]
    for project_id, working_dir in job_rows:
        if project_id in ids:
            busy.add(project_id)
            continue
        if not working_dir:
            continue
        wd = Path(working_dir).resolve()
        for pid, folder in folders:
            if wd == folder or folder in wd.parents:
                busy.add(pid)

    wf_rows = (
        db.query(Workflow.project_id)
        .filter(Workflow.status.in_((WorkflowStatus.PENDING, WorkflowStatus.RUNNING)))
        .all()
    )
    busy.update(pid for (pid,) in wf_rows if pid in ids)
    return busy


def apply_relocations(
    plans: Iterable[dict],
    *,
    update_work_dir,
    dry_run: bool = True,
) -> dict:
    """Execute relocation plans: move directories and update each project's
    ``work_dir`` via the ``update_work_dir(project_id, new_path)`` callback.

    Idempotent and fail-soft: a project whose source dir is missing or whose
    destination already exists is skipped with a warning rather than aborting
    the whole run. Returns a summary ``{moved, skipped, failed}`` count dict.

    Args:
        plans: output of :func:`plan_relocations`.
        update_work_dir: callable(project_id, new_work_dir:str) -> None, run
            AFTER a successful move to persist the new path in the DB.
        dry_run: when True (default), only log what would happen.
    """
    summary = {"moved": 0, "skipped": 0, "failed": 0}

    for plan in plans:
        pid, action = plan["id"], plan["action"]
        if action == "skip-active-jobs":
            logger.warning(
                "project %s: a job or workflow is still active in %s — left in place; "
                "re-run once it has finished",
                pid,
                plan["src"],
            )
            summary["skipped"] += 1
            continue
        if action != "move":
            logger.info("project %s: %s (%s)", pid, action, plan["src"])
            summary["skipped"] += 1
            continue

        src, dst = Path(plan["src"]), Path(plan["dst"])
        if not src.exists():
            logger.warning("project %s: source %s missing — skipping", pid, src)
            summary["skipped"] += 1
            continue
        if dst.exists():
            logger.warning("project %s: destination %s already exists — skipping", pid, dst)
            summary["skipped"] += 1
            continue

        if dry_run:
            logger.info("[dry-run] project %s: would move %s -> %s", pid, src, dst)
            summary["skipped"] += 1
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            update_work_dir(pid, str(dst))
            logger.info("project %s: moved %s -> %s", pid, src, dst)
            summary["moved"] += 1
        except Exception:
            logger.exception("project %s: relocation failed (%s -> %s)", pid, src, dst)
            summary["failed"] += 1

    return summary


def relocate_legacy_projects(
    *,
    user_data_root=None,
    session_factory=None,
    dry_run: bool = True,
) -> dict:
    """F15 driver: relocate every owned project whose ``work_dir`` still lives
    outside its owner's home into ``user_data_root/{owner}/{basename}``.

    This is the DB glue that :func:`plan_relocations` / :func:`apply_relocations`
    lacked (they had no caller). It fixes LEGACY OWNER access after PR#29's
    ``confine_path`` enforcement, where a pre-#29 project stored under the shared
    ``work_dir`` became unreachable by its owner.

    It does NOT fix the tutorial-share case. The bootstrapped "Mar Menor
    Tutorial" is owned by ``admin``, so this relocates it under the ADMIN's home
    — still outside the tutorial user's allowlist. That case is handled by
    ``confine_path``'s shared-read widening
    (:func:`shyfem_ui.services.access_control.accessible_shared_work_dirs`),
    not here.

    Operator-invoked; **never auto-run at startup** — a bad stored path or a
    permission error must not trigger ``shutil.move`` on the laguna deployment's
    next boot. Defaults to ``dry_run=True``: run once to preview the plan, then
    again with ``dry_run=False`` to apply. Idempotent (re-running skips projects
    already under their owner's home).

    Args:
        user_data_root: per-user data root; defaults to ``config.user_data_root``.
        session_factory: SQLAlchemy session factory; defaults to the global one.
        dry_run: when True (default), only log intended moves.

    Returns:
        The ``{moved, skipped, failed}`` summary from :func:`apply_relocations`.
    """
    from shyfem_ui.models.project import Project
    from shyfem_ui.models.user import User

    if session_factory is None:
        from shyfem_ui.db.base import get_session_factory

        session_factory = get_session_factory()
    if user_data_root is None:
        from shyfem_ui.config import get_config

        user_data_root = get_config().user_data_root

    db = session_factory()
    try:
        rows = (
            db.query(Project.id, Project.work_dir, User.username)
            .outerjoin(User, Project.owner_id == User.id)
            .all()
        )
        projects = [
            {"id": pid, "work_dir": work_dir, "owner_username": owner}
            for (pid, work_dir, owner) in rows
        ]
        busy = busy_project_ids(db, projects)
    finally:
        db.close()

    plans = plan_relocations(projects, user_data_root=user_data_root, busy_project_ids=busy)

    def _update_work_dir(project_id: int, new_work_dir: str) -> None:
        session = session_factory()
        try:
            proj = session.query(Project).filter_by(id=project_id).first()
            if proj is not None:
                proj.work_dir = new_work_dir
                session.commit()
        finally:
            session.close()

    return apply_relocations(plans, update_work_dir=_update_work_dir, dry_run=dry_run)
