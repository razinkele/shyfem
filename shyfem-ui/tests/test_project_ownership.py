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
        "p1_id": p1.id,
        "p2_id": p2.id,
        "p3_id": p3.id,
        "p4_id": p4.id,
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


class TestDashboardProjectsFailClosed:
    """The dashboard project listing must NOT leak every user's projects when
    the WS identity is unresolved (user=None) in server mode. Behind the Shiny
    Server proxy the reactive layer runs with user=None until ``_wsauth``
    resolves, and the old ``if user and ...: ... else: <all projects>`` shape
    fell to the unfiltered else branch — listing all projects on the first
    reactive flush of every server-mode session."""

    def test_server_mode_unresolved_user_sees_nothing(self):
        from shyfem_ui.pages.home import _dashboard_projects

        # user=None in server mode is fail-closed: empty list, and no db query
        # is issued (passing db=None proves the db is never touched).
        assert _dashboard_projects(None, None, is_server_mode=True) == []

    def test_local_mode_unresolved_user_sees_all(self, db_session_factory, setup_data):
        from shyfem_ui.pages.home import _dashboard_projects

        db = db_session_factory()
        try:
            result = _dashboard_projects(db, None, is_server_mode=False)
            assert len(result) >= 1, "local desktop mode lists projects with no auth"
        finally:
            db.close()

    def test_server_mode_regular_user_sees_only_own(self, db_session_factory, setup_data):
        from shyfem_ui.pages.home import _dashboard_projects

        db = db_session_factory()
        try:
            result = _dashboard_projects(db, setup_data["alice"], is_server_mode=True)
            names = {p.name for p in result}
            assert "Bob Project" not in names
            assert "Alice Project" in names
        finally:
            db.close()

    def test_server_mode_admin_sees_all(self, db_session_factory, setup_data):
        from shyfem_ui.pages.home import _dashboard_projects

        db = db_session_factory()
        try:
            result = _dashboard_projects(db, setup_data["admin"], is_server_mode=True)
            assert len(result) >= 4, "admin sees every project including unowned"
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
