"""Tests for project sharing service."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User
from shyfem_ui.services.sharing_service import SharingService


@pytest.fixture
def db_factory():
    from shyfem_ui.models import project as _p, user as _u  # noqa
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def service(db_factory):
    return SharingService(session_factory=db_factory)


@pytest.fixture
def setup(db_factory):
    db = db_factory()
    alice = User(username="alice", password_hash="x", role="user")
    bob = User(username="bob", password_hash="x", role="user")
    db.add_all([alice, bob])
    db.flush()
    proj = Project(name="P1", work_dir="/tmp/p1", owner_id=alice.id)
    db.add(proj)
    db.commit()
    data = {"alice_id": alice.id, "bob_id": bob.id, "project_id": proj.id}
    db.close()
    return data


class TestShareProject:
    def test_share_with_user(self, service, setup):
        result = service.share_project(setup["project_id"], setup["bob_id"], "viewer")
        assert result is True

    def test_share_duplicate_updates_role(self, service, setup):
        service.share_project(setup["project_id"], setup["bob_id"], "viewer")
        service.share_project(setup["project_id"], setup["bob_id"], "editor")
        perms = service.list_permissions(setup["project_id"])
        assert len(perms) == 1
        assert perms[0]["role"] == "editor"

    def test_unshare(self, service, setup):
        service.share_project(setup["project_id"], setup["bob_id"], "viewer")
        service.unshare_project(setup["project_id"], setup["bob_id"])
        perms = service.list_permissions(setup["project_id"])
        assert len(perms) == 0


class TestListPermissions:
    def test_empty(self, service, setup):
        perms = service.list_permissions(setup["project_id"])
        assert perms == []

    def test_with_shares(self, service, setup):
        service.share_project(setup["project_id"], setup["bob_id"], "editor")
        perms = service.list_permissions(setup["project_id"])
        assert len(perms) == 1
        assert perms[0]["username"] == "bob"
        assert perms[0]["role"] == "editor"


class TestGetUserRole:
    def test_owner(self, service, setup):
        role = service.get_user_role(setup["project_id"], setup["alice_id"])
        assert role == "owner"

    def test_shared_viewer(self, service, setup):
        service.share_project(setup["project_id"], setup["bob_id"], "viewer")
        role = service.get_user_role(setup["project_id"], setup["bob_id"])
        assert role == "viewer"

    def test_no_access(self, service, setup):
        role = service.get_user_role(setup["project_id"], setup["bob_id"])
        assert role is None


@pytest.fixture
def setup_three_users(db_factory):
    db = db_factory()
    alice = User(username="alice3", password_hash="x", role="user")
    bob = User(username="bob3", password_hash="x", role="user")
    carol = User(username="carol3", password_hash="x", role="user")
    db.add_all([alice, bob, carol])
    db.flush()
    proj = Project(name="P3", work_dir="/tmp/p3", owner_id=alice.id)
    db.add(proj)
    db.commit()
    data = {
        "alice_id": alice.id,
        "bob_id": bob.id,
        "carol_id": carol.id,
        "project_id": proj.id,
    }
    db.close()
    return data


class TestListShareableUsers:
    """Edge cases for list_shareable_users — the largest untested surface
    in sharing_service."""

    def test_excludes_owner(self, service, setup):
        """The project owner should NEVER be returned as a sharing candidate
        — they already have full access (excluded via exclude_user_id)."""
        candidates = service.list_shareable_users(
            project_id=setup["project_id"], exclude_user_id=setup["alice_id"]
        )
        ids = [u["id"] for u in candidates]
        assert setup["alice_id"] not in ids

    def test_excludes_already_shared(self, service, setup):
        """A user who already has a permission on the project should NOT
        appear as a sharing candidate."""
        service.share_project(setup["project_id"], setup["bob_id"], "viewer")
        candidates = service.list_shareable_users(
            project_id=setup["project_id"], exclude_user_id=setup["alice_id"]
        )
        ids = [u["id"] for u in candidates]
        assert setup["bob_id"] not in ids

    def test_returns_remaining_users(
        self, db_factory, setup_three_users
    ):
        """Of three users, with one shared and the owner excluded, the
        single remaining user is returned."""
        svc = SharingService(session_factory=db_factory)
        data = setup_three_users
        svc.share_project(data["project_id"], data["bob_id"], "viewer")
        candidates = svc.list_shareable_users(
            project_id=data["project_id"], exclude_user_id=data["alice_id"]
        )
        ids = [u["id"] for u in candidates]
        assert data["carol_id"] in ids
        assert data["alice_id"] not in ids
        assert data["bob_id"] not in ids

    def test_empty_when_all_users_have_access(self, service, setup):
        """When the only non-owner user is already shared, no candidates."""
        service.share_project(setup["project_id"], setup["bob_id"], "viewer")
        candidates = service.list_shareable_users(
            project_id=setup["project_id"], exclude_user_id=setup["alice_id"]
        )
        assert candidates == []
