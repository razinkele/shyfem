"""SQLite foreign-key enforcement.

SQLite silently ignores foreign-key constraints unless ``PRAGMA foreign_keys=ON``
is set on every connection. Without it a row can reference a non-existent parent
and a parent can be deleted out from under its children, leaving dangling
references. These tests pin that enforcement is active on the production engine.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


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
