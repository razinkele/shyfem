"""Tests for project ownership and access control."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


@pytest.fixture
def db_session_factory():
    from shyfem_ui.models import project as _p, user as _u  # noqa
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def setup_data(db_session_factory):
    db = db_session_factory()
    admin = User(username="admin", password_hash="x", role="admin", display_name="Admin")
    alice = User(username="alice", password_hash="x", role="user", display_name="Alice")
    bob = User(username="bob", password_hash="x", role="user", display_name="Bob")
    db.add_all([admin, alice, bob])
    db.flush()

    p1 = Project(name="Alice Project", work_dir="/tmp/p1", owner_id=alice.id)
    p2 = Project(name="Bob Project", work_dir="/tmp/p2", owner_id=bob.id)
    p3 = Project(name="Shared", work_dir="/tmp/p3", owner_id=alice.id)
    p4 = Project(name="Unowned", work_dir="/tmp/p4", owner_id=None)
    db.add_all([p1, p2, p3, p4])
    db.flush()

    perm = ProjectPermission(project_id=p3.id, user_id=bob.id, role="viewer")
    db.add(perm)
    db.commit()

    data = {
        "admin": {"id": admin.id, "role": "admin"},
        "alice": {"id": alice.id, "role": "user"},
        "bob": {"id": bob.id, "role": "user"},
        "p1_id": p1.id, "p2_id": p2.id, "p3_id": p3.id, "p4_id": p4.id,
    }
    db.close()
    return data


def _query_user_projects(db, user_id: int, role: str) -> list:
    from shyfem_ui.pages.home import get_visible_projects
    return get_visible_projects(db, user_id, role)


class TestProjectVisibility:
    def test_admin_sees_all(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            projects = _query_user_projects(db, setup_data["admin"]["id"], "admin")
            assert len(projects) == 4
        finally:
            db.close()

    def test_alice_sees_own_and_shared(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            projects = _query_user_projects(db, setup_data["alice"]["id"], "user")
            names = {p.name for p in projects}
            assert "Alice Project" in names
            assert "Shared" in names
            assert "Bob Project" not in names
        finally:
            db.close()

    def test_bob_sees_own_and_shared(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            projects = _query_user_projects(db, setup_data["bob"]["id"], "user")
            names = {p.name for p in projects}
            assert "Bob Project" in names
            assert "Shared" in names
            assert "Alice Project" not in names
        finally:
            db.close()

    def test_unowned_visible_to_admin_only(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            admin_projects = _query_user_projects(db, setup_data["admin"]["id"], "admin")
            alice_projects = _query_user_projects(db, setup_data["alice"]["id"], "user")
            admin_names = {p.name for p in admin_projects}
            alice_names = {p.name for p in alice_projects}
            assert "Unowned" in admin_names
            assert "Unowned" not in alice_names
        finally:
            db.close()


class TestProjectCreationOwner:
    def test_new_project_gets_owner_id(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            p = Project(name="New", work_dir="/tmp/new", owner_id=setup_data["alice"]["id"])
            db.add(p)
            db.commit()
            assert p.owner_id == setup_data["alice"]["id"]
        finally:
            db.close()
