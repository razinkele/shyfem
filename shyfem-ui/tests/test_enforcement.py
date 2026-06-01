"""Tests for access control enforcement at key endpoints."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


@pytest.fixture
def db_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def setup(db_factory):
    db = db_factory()
    alice = User(username="alice", password_hash="x", role="user")
    bob = User(username="bob", password_hash="x", role="user")
    admin = User(username="admin", password_hash="x", role="admin")
    db.add_all([alice, bob, admin])
    db.flush()

    proj = Project(name="P1", work_dir="/tmp/p1", owner_id=alice.id)
    db.add(proj)
    db.flush()

    perm = ProjectPermission(project_id=proj.id, user_id=bob.id, role="viewer")
    db.add(perm)
    db.commit()

    data = {
        "alice_id": alice.id,
        "bob_id": bob.id,
        "admin_id": admin.id,
        "project_id": proj.id,
    }
    db.close()
    return data


def _user(uid, role="user"):
    return {"id": uid, "username": f"user{uid}", "role": role}


class TestProjectContextEnforcement:
    def test_load_with_access(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context

        # Owner should be able to load
        ctx = load_project_context(
            setup["project_id"],
            user=_user(setup["alice_id"]),
            session_factory=db_factory,
        )
        assert ctx is not None
        assert ctx["name"] == "P1"

    def test_load_denied(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context

        # Create a second user with no access
        db = db_factory()
        eve = User(username="eve", password_hash="x", role="user")
        db.add(eve)
        db.commit()
        eve_id = eve.id
        db.close()

        ctx = load_project_context(
            setup["project_id"],
            user=_user(eve_id),
            session_factory=db_factory,
        )
        assert ctx is None

    def test_load_admin_bypass(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context

        ctx = load_project_context(
            setup["project_id"],
            user=_user(setup["admin_id"], "admin"),
            session_factory=db_factory,
        )
        assert ctx is not None

    def test_load_no_user_returns_all(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context

        # In LOCAL mode, an unresolved user (None) is legitimate and loads the
        # project unfiltered. Pin is_server_mode=False so the test asserts that
        # intent deterministically — under a server .env the gate fails closed
        # on user=None (covered by test_server_mode_denies_unresolved_user).
        ctx = load_project_context(
            setup["project_id"],
            user=None,
            is_server_mode=False,
            session_factory=db_factory,
        )
        assert ctx is not None

    def test_viewer_can_load(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context

        ctx = load_project_context(
            setup["project_id"],
            user=_user(setup["bob_id"]),
            session_factory=db_factory,
        )
        assert ctx is not None
