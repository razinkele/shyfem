#!/usr/bin/env python
"""One-time migration: relocate existing projects under their owners' home dirs.

Run AFTER deploying the path-confinement IDOR fix (Config.confine_path). Once
confinement is enforced in server mode, a project whose work_dir still lives
under the shared work_dir is unreachable by its owner; this moves each owned
project into ``user_data_root/{username}/<name>`` and updates Project.work_dir.

SAFETY:
  * Dry-run by default — prints the plan and changes nothing.
  * Back up the DB first (use the deploy-ui skill / cp shyfem_ui.db ...).
  * Idempotent: re-running skips projects already under their owner's home and
    never clobbers an existing destination directory.
  * Orphan projects (owner_id is NULL) are left in place and flagged.

USAGE:
  python -m scripts.migrations.relocate_projects_to_user_homes            # dry-run
  python -m scripts.migrations.relocate_projects_to_user_homes --apply    # execute
"""

from __future__ import annotations

import argparse
import logging
import sys

from shyfem_ui.config import get_config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import User
from shyfem_ui.services.project_relocation import apply_relocations, plan_relocations

logger = logging.getLogger("relocate_projects")


def _load_projects(db) -> list[dict]:
    rows = (
        db.query(Project.id, Project.work_dir, User.username)
        .outerjoin(User, Project.owner_id == User.id)
        .all()
    )
    return [{"id": pid, "work_dir": wd, "owner_username": uname} for pid, wd, uname in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the moves (default is a dry run that changes nothing).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = get_config()
    dry_run = not args.apply

    with db_session() as db:
        projects = _load_projects(db)
        plans = plan_relocations(projects, user_data_root=config.user_data_root)

        moves = [p for p in plans if p["action"] == "move"]
        orphans = [p for p in plans if p["action"] == "skip-orphan"]
        logger.info(
            "%d projects: %d to move, %d already home, %d orphan",
            len(plans),
            len(moves),
            sum(1 for p in plans if p["action"] == "skip-already-home"),
            len(orphans),
        )
        for p in orphans:
            logger.warning("ORPHAN (no owner) left in place: project %s at %s", p["id"], p["src"])

        def _update_work_dir(pid: int, new_path: str) -> None:
            db.query(Project).filter(Project.id == pid).update({Project.work_dir: new_path})
            db.commit()

        summary = apply_relocations(plans, update_work_dir=_update_work_dir, dry_run=dry_run)

    logger.info(
        "%s complete: moved=%d skipped=%d failed=%d",
        "DRY-RUN" if dry_run else "APPLY",
        summary["moved"],
        summary["skipped"],
        summary["failed"],
    )
    if dry_run and moves:
        logger.info("Re-run with --apply to perform the %d move(s).", len(moves))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
