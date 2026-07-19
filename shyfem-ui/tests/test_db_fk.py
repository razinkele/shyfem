"""SQLite foreign-key enforcement.

SQLite silently ignores foreign-key constraints unless ``PRAGMA foreign_keys=ON``
is set on every connection. Without it a row can reference a non-existent parent
and a parent can be deleted out from under its children, leaving dangling
references. These tests pin that enforcement is active on the production engine.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fresh_engine(tmp_path, monkeypatch):
    """Point the base.py engine at a temp DB and initialise the schema."""
    import shyfem_ui.config as cfg
    import shyfem_ui.db.base as base

    db = tmp_path / "fk.db"
    monkeypatch.setattr(cfg, "_config", cfg.Config(database_url=f"sqlite:///{db}"))
    monkeypatch.setattr(base, "_engine", None)
    monkeypatch.setattr(base, "_SessionLocal", None)
    base.init_db()
    return base


def test_dangling_foreign_key_insert_rejected(tmp_path, monkeypatch):
    """Inserting a child row that references a non-existent parent must fail."""
    base = _fresh_engine(tmp_path, monkeypatch)
    from shyfem_ui.models.user import ProjectPermission

    with pytest.raises(IntegrityError):
        with base.db_session() as session:
            session.add(
                ProjectPermission(project_id=987654, user_id=123456, role="viewer")
            )


def test_deleting_parent_with_children_rejected(tmp_path, monkeypatch):
    """Deleting a user while a child row still references it must fail. This is
    the constraint that forces delete_user to clean up / NULL its children
    before removing the user (an ORM cascade does this for sessions, explicit
    cleanup for the rest)."""
    base = _fresh_engine(tmp_path, monkeypatch)
    from shyfem_ui.models.user import AuthSession, User

    with base.db_session() as session:
        user = User(username="fkuser", password_hash="h", role="user")
        session.add(user)
        session.flush()
        session.add(
            AuthSession(
                token="tok-fk",
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )

    # Raw DELETE bypasses the ORM cascade, so the child row is still present —
    # FK enforcement must reject removing the parent.
    with pytest.raises(IntegrityError):
        with base.db_session() as session:
            session.execute(text("DELETE FROM users WHERE username = 'fkuser'"))


def test_deleting_project_cascades_permission_rows(tmp_path, monkeypatch):
    """F24: deleting a project that still has ProjectPermission rows must
    succeed and remove those rows (ON DELETE CASCADE on project_id), matching
    how grids/simulations/files already cascade via the ORM. Before the fix,
    project_permissions.project_id has no ondelete and the raw DELETE below
    is rejected with IntegrityError instead."""
    base = _fresh_engine(tmp_path, monkeypatch)
    from shyfem_ui.models.project import Project
    from shyfem_ui.models.user import ProjectPermission, User

    with base.db_session() as session:
        user = User(username="owner", password_hash="h", role="user")
        project = Project(name="proj-fk", work_dir="/tmp/proj-fk")
        session.add_all([user, project])
        session.flush()
        session.add(ProjectPermission(project_id=project.id, user_id=user.id, role="viewer"))
        session.flush()
        project_id = project.id

    with base.db_session() as session:
        session.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})

    with base.db_session() as session:
        remaining = session.execute(
            text("SELECT COUNT(*) FROM project_permissions WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar()
    assert remaining == 0


def test_deleting_user_cascades_permission_rows(tmp_path, monkeypatch):
    """F24: deleting a user that still has ProjectPermission rows must
    succeed and remove those rows (ON DELETE CASCADE on user_id). Distinct
    from delete_user()'s explicit application-level cleanup (auth_service.py)
    — this proves the schema itself enforces it, not just that one call site."""
    base = _fresh_engine(tmp_path, monkeypatch)
    from shyfem_ui.models.project import Project
    from shyfem_ui.models.user import ProjectPermission, User

    with base.db_session() as session:
        user = User(username="shared-with", password_hash="h", role="user")
        project = Project(name="proj-fk-2", work_dir="/tmp/proj-fk-2")
        session.add_all([user, project])
        session.flush()
        session.add(ProjectPermission(project_id=project.id, user_id=user.id, role="viewer"))
        session.flush()
        user_id = user.id

    with base.db_session() as session:
        session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})

    with base.db_session() as session:
        remaining = session.execute(
            text("SELECT COUNT(*) FROM project_permissions WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar()
    assert remaining == 0


def _project_permissions_ondelete(db_path: Path) -> dict[str, str | None]:
    """Return {fk_constraint_name: ondelete_action} for project_permissions."""
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        fks = inspect(engine).get_foreign_keys("project_permissions")
        return {fk["name"]: fk["options"].get("ondelete") for fk in fks}
    finally:
        engine.dispose()


def test_project_permissions_cascade_migration_up_down_up(tmp_path):
    """The 85f9efff4f5e migration (F24) must apply cleanly in both directions
    against a real Alembic run (not just via base.py's init_db() wrapper):
    ON DELETE CASCADE present after upgrade, gone after downgrading past it,
    and back after re-upgrading -- proving the migration itself, not just the
    end schema, is correct and reversible."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    db = tmp_path / "migration_roundtrip.db"
    alembic_cfg = AlembicConfig(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    alembic_cfg.config_file_name = None

    command.upgrade(alembic_cfg, "head")
    after_upgrade = _project_permissions_ondelete(db)
    assert after_upgrade == {
        "fk_project_permissions_project_id_projects": "CASCADE",
        "fk_project_permissions_user_id_users": "CASCADE",
    }

    command.downgrade(alembic_cfg, "-1")
    after_downgrade = _project_permissions_ondelete(db)
    assert set(after_downgrade) == set(after_upgrade)
    assert all(action is None for action in after_downgrade.values()), after_downgrade

    command.upgrade(alembic_cfg, "head")
    after_reupgrade = _project_permissions_ondelete(db)
    assert after_reupgrade == after_upgrade


def test_project_permissions_cascade_migration_preserves_existing_rows(tmp_path):
    """SQLite can't ALTER a FK in place, so this migration's batch_alter_table
    rebuilds project_permissions (rename -> create -> copy rows -> drop). Prove
    the copy step is lossless: seed a row on the schema as it existed *before*
    this migration (its down_revision), then upgrade the last step to head and
    confirm the row survived the rebuild unchanged. (FK cascade *behaviour*
    after the rebuild is covered separately by the cascade tests above --
    this test is only about not losing pre-existing data during the rebuild.)"""
    import sqlite3

    from alembic import command
    from alembic.config import Config as AlembicConfig

    db = tmp_path / "migration_preserve.db"
    alembic_cfg = AlembicConfig(str(_REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    alembic_cfg.config_file_name = None

    # Build the schema as it stood immediately before this migration.
    command.upgrade(alembic_cfg, "ccde037a5855")

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active) "
            "VALUES ('presrv-user', 'h', 'user', 1)"
        )
        user_id = conn.execute(
            "SELECT id FROM users WHERE username = 'presrv-user'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO projects (name, work_dir) VALUES ('presrv-proj', '/tmp/presrv-proj')"
        )
        project_id = conn.execute(
            "SELECT id FROM projects WHERE name = 'presrv-proj'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO project_permissions (project_id, user_id, role) VALUES (?, ?, 'editor')",
            (project_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()

    # This is the migration under test: batch_alter_table rebuilds the table.
    command.upgrade(alembic_cfg, "head")

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT project_id, user_id, role FROM project_permissions "
            "WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
    finally:
        conn.close()
    assert row == (project_id, user_id, "editor"), (
        "the rebuild triggered by ondelete=CASCADE lost or altered a pre-existing "
        f"project_permissions row: {row}"
    )
