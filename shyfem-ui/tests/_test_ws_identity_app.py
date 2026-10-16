"""Server-mode test app seeded for WS trusted-identity (Phase 4) E2E tests.

Like ``_test_auth_app.py`` (real ``create_app()`` with SessionAuthMiddleware
active), but additionally seeds a non-admin ``viewer1`` account plus two
admin-owned projects:

- ``Shared``  — shared with ``viewer1`` at ``viewer`` permission.
- ``Private`` — NOT shared (used to prove listing + activation isolation).

The seeding is idempotent so a re-run against a persisted DB is harmless.
Identity in the WS scope flows through the Phase 3B ``setInputValue('_wsauth')``
token → resolver → ``current_user()`` path, so these fixtures exercise the
real production identity path (the session cookie is irrelevant to the guards).
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SHYFEM_UI_DEPLOYMENT_MODE", "server")
os.environ.setdefault("SHYFEM_UI_DEFAULT_ADMIN_USERNAME", "admin")
os.environ.setdefault("SHYFEM_UI_DEFAULT_ADMIN_PASSWORD", "testpass")

from shyfem_ui.app import create_app  # noqa: E402
from shyfem_ui.config import Config, set_config  # noqa: E402

VIEWER_USERNAME = "viewer1"
VIEWER_PASSWORD = "viewerpass"
# Editor on Shared whose account the L31 E2E deactivates mid-session.
DEMOTEE_USERNAME = "demotee"
DEMOTEE_PASSWORD = "demoteepass"
SHARED_PROJECT = "Shared"
PRIVATE_PROJECT = "Private"


def _seed(config: Config) -> None:
    """Seed viewer1 + a shared and a private admin-owned project (idempotent)."""
    from shyfem_ui.db.base import get_session_factory
    from shyfem_ui.models.project import Project
    from shyfem_ui.models.user import User
    from shyfem_ui.services.auth_service import AuthService
    from shyfem_ui.services.sharing_service import SharingService

    auth = AuthService()
    session_factory = get_session_factory()

    # --- viewer1 user (global role "user"; per-project role comes from sharing)
    db = session_factory()
    try:
        admin = db.query(User).filter_by(username="admin").one()
        admin_id = admin.id
        viewer = db.query(User).filter_by(username=VIEWER_USERNAME).first()
    finally:
        db.close()

    if viewer is None:
        viewer_dict = auth.create_user(
            VIEWER_USERNAME,
            VIEWER_PASSWORD,
            role="user",
            email="viewer1@example.com",
            user_data_root=config.user_data_root,
        )
        viewer_id = viewer_dict["id"]
    else:
        viewer_id = viewer.id

    # --- projects (admin-owned). Create work_dirs on disk like the UI does.
    def _ensure_project(name: str) -> int:
        db = session_factory()
        try:
            existing = db.query(Project).filter_by(name=name).first()
            if existing is not None:
                return existing.id
            work_dir = config.work_dir / name
            work_dir.mkdir(parents=True, exist_ok=True)
            proj = Project(
                name=name,
                description=f"{name} project (seeded)",
                work_dir=str(work_dir),
                owner_id=admin_id,
            )
            db.add(proj)
            db.commit()
            return proj.id
        finally:
            db.close()

    shared_id = _ensure_project(SHARED_PROJECT)
    _ensure_project(PRIVATE_PROJECT)

    # --- share "Shared" with viewer1 at viewer permission (idempotent)
    SharingService().share_project(shared_id, viewer_id, role="viewer")

    # --- demotee: an editor on Shared, deactivated mid-session by the L31 test
    db = session_factory()
    try:
        demotee = db.query(User).filter_by(username=DEMOTEE_USERNAME).first()
        demotee_id = demotee.id if demotee is not None else None
    finally:
        db.close()
    if demotee_id is None:
        demotee_id = auth.create_user(
            DEMOTEE_USERNAME,
            DEMOTEE_PASSWORD,
            role="user",
            email="demotee@example.com",
            user_data_root=config.user_data_root,
        )["id"]
    SharingService().share_project(shared_id, demotee_id, role="editor")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument("--workdir", required=True, help="Work directory path")
    args = parser.parse_args()

    config = Config(
        host=args.host,
        port=args.port,
        database_url=f"sqlite:///{args.db}",
        work_dir=Path(args.workdir),
        user_data_root=Path(args.workdir) / "users",
        deployment_mode="server",
        default_admin_username="admin",
        default_admin_password="testpass",
        auth_session_ttl_hours=24,
        debug=False,
        root_path="",
    )
    set_config(config)

    app = create_app(config)
    _seed(config)

    from shiny import run_app

    run_app(app, host=args.host, port=args.port)
