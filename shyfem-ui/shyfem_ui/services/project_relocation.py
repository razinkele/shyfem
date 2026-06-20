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
) -> list[dict]:
    """Compute relocation plans for a set of projects.

    Args:
        projects: dicts with keys ``id``, ``work_dir``, ``owner_username``.
        user_data_root: configured per-user data root.

    Returns:
        One plan dict per project: ``{id, src, dst, action}`` where ``action``
        is ``"move"`` (relocate src -> dst), ``"skip-already-home"`` (already in
        the owner's sandbox), or ``"skip-orphan"`` (no owner username — left in
        place and flagged for manual handling).
    """
    root = Path(user_data_root).resolve()
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
        plans.append({"id": pid, "src": str(src), "dst": str(dst), "action": "move"})

    return plans


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
