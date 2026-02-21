"""Tests for access control helper."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


@pytest.fixture
def db_factory():
    from shyfem_ui.models import project as _p, user as _u  # noqa: F841
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def setup(db_factory):
    """Create alice (owner), bob (no access), charlie (viewer), admin user, and a project."""
    db = db_factory()
    alice = User(username="alice", password_hash="x", role="user")
    bob = User(username="bob", password_hash="x", role="user")
    charlie = User(username="charlie", password_hash="x", role="user")
    admin = User(username="admin", password_hash="x", role="admin")
    db.add_all([alice, bob, charlie, admin])
    db.flush()

    proj = Project(name="P1", work_dir="/tmp/p1", owner_id=alice.id)
    db.add(proj)
    db.flush()

    perm = ProjectPermission(project_id=proj.id, user_id=charlie.id, role="viewer")
    db.add(perm)
    db.commit()

    data = {
        "alice_id": alice.id,
        "bob_id": bob.id,
        "charlie_id": charlie.id,
        "admin_id": admin.id,
        "project_id": proj.id,
    }
    db.close()
    return data


def _user(uid, role="user"):
    """Helper to build a user dict like get_current_user() returns."""
    return {"id": uid, "username": f"user{uid}", "role": role}


class TestCheckProjectAccess:
    def test_none_user_denied(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(setup["project_id"], None, session_factory=db_factory)
        assert result is None

    def test_admin_always_allowed(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["admin_id"], "admin"),
            session_factory=db_factory,
        )
        assert result == "admin"

    def test_owner_has_all_roles(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        for min_role in ("viewer", "editor", "owner"):
            result = check_project_access(
                setup["project_id"], _user(setup["alice_id"]),
                min_role=min_role, session_factory=db_factory,
            )
            assert result == "owner", f"owner should satisfy min_role={min_role}"

    def test_viewer_satisfies_viewer(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="viewer", session_factory=db_factory,
        )
        assert result == "viewer"

    def test_viewer_denied_editor(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="editor", session_factory=db_factory,
        )
        assert result is None

    def test_no_access_denied(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["bob_id"]),
            session_factory=db_factory,
        )
        assert result is None

    def test_nonexistent_project(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            99999, _user(setup["alice_id"]),
            session_factory=db_factory,
        )
        assert result is None

    def test_default_min_role_is_viewer(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            session_factory=db_factory,
        )
        assert result == "viewer"


class TestRoleHierarchy:
    def test_hierarchy_values(self):
        from shyfem_ui.services.access_control import ROLE_HIERARCHY
        assert ROLE_HIERARCHY["owner"] > ROLE_HIERARCHY["editor"]
        assert ROLE_HIERARCHY["editor"] > ROLE_HIERARCHY["viewer"]

    def test_editor_satisfies_editor(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        # First give charlie editor access
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=db_factory)
        svc.share_project(setup["project_id"], setup["charlie_id"], "editor")

        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="editor", session_factory=db_factory,
        )
        assert result == "editor"

    def test_editor_denied_owner(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=db_factory)
        svc.share_project(setup["project_id"], setup["charlie_id"], "editor")

        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="owner", session_factory=db_factory,
        )
        assert result is None
