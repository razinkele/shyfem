"""Tests for sharing UI pure functions."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


class TestShouldShowShareButton:
    def test_owner_sees_share(self):
        from shyfem_ui.pages.home import _should_show_share_button

        project = {"id": 1, "owner_id": 10}
        user = {"id": 10, "role": "user"}
        assert _should_show_share_button(project, user) is True

    def test_admin_sees_share(self):
        from shyfem_ui.pages.home import _should_show_share_button

        project = {"id": 1, "owner_id": 10}
        user = {"id": 99, "role": "admin"}
        assert _should_show_share_button(project, user) is True

    def test_non_owner_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button

        project = {"id": 1, "owner_id": 10}
        user = {"id": 20, "role": "user"}
        assert _should_show_share_button(project, user) is False

    def test_none_user_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button

        project = {"id": 1, "owner_id": 10}
        assert _should_show_share_button(project, None) is False

    def test_none_owner_id_admin_sees(self):
        from shyfem_ui.pages.home import _should_show_share_button

        project = {"id": 1, "owner_id": None}
        user = {"id": 99, "role": "admin"}
        assert _should_show_share_button(project, user) is True

    def test_none_owner_id_user_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button

        project = {"id": 1, "owner_id": None}
        user = {"id": 20, "role": "user"}
        assert _should_show_share_button(project, user) is False


class TestBuildPermissionsTableData:
    def test_empty_list(self):
        from shyfem_ui.pages.home import _build_permissions_table_data

        assert _build_permissions_table_data([]) == []

    def test_formats_permissions(self):
        from shyfem_ui.pages.home import _build_permissions_table_data

        perms = [
            {"user_id": 2, "username": "bob", "display_name": "Bob", "role": "editor"},
            {"user_id": 3, "username": "charlie", "display_name": None, "role": "viewer"},
        ]
        result = _build_permissions_table_data(perms)
        assert len(result) == 2
        assert result[0]["username"] == "bob"
        assert result[0]["display_name"] == "Bob"
        assert result[0]["role"] == "editor"
        assert result[1]["display_name"] == "charlie"  # fallback to username


@pytest.fixture
def db_factory():

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def setup(db_factory):
    """alice (owner), bob (no access), charlie (viewer), admin, and one project."""
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

    db.add(ProjectPermission(project_id=proj.id, user_id=charlie.id, role="viewer"))
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
    return {"id": uid, "username": f"user{uid}", "role": role}


class TestSharingDeniedReason:
    """Server-side guard for the share/unshare mutation handlers.

    The rendered Share button is only a visibility hint; a client can fire
    ``confirm_share_<pid>`` / ``unshare_<pid>_<uid>`` directly over the
    WebSocket. Only project owners and admins may modify sharing.
    """

    def test_owner_allowed(self, db_factory, setup):
        from shyfem_ui.pages.home import _sharing_denied_reason

        assert (
            _sharing_denied_reason(
                setup["project_id"], _user(setup["alice_id"]), session_factory=db_factory
            )
            is None
        )

    def test_admin_allowed(self, db_factory, setup):
        from shyfem_ui.pages.home import _sharing_denied_reason

        assert (
            _sharing_denied_reason(
                setup["project_id"],
                _user(setup["admin_id"], "admin"),
                session_factory=db_factory,
            )
            is None
        )

    def test_tutorial_owner_denied_readonly(self, db_factory, setup):
        """A ROLE_TUTORIAL account is read-only even if it OWNS the project
        (e.g. a user demoted via update_user, which keeps ownership rows). The
        tutorial check must fire before the owner allow-check, mirroring the
        other central gates."""
        from shyfem_ui.pages.home import _sharing_denied_reason

        # alice owns the project; as a tutorial she must still be denied.
        reason = _sharing_denied_reason(
            setup["project_id"],
            _user(setup["alice_id"], "tutorial"),
            session_factory=db_factory,
        )
        assert reason is not None
        assert "read-only" in reason.lower()

    def test_unresolved_actor_denied_with_signin_message(self, db_factory, setup):
        from shyfem_ui.pages.home import _sharing_denied_reason

        reason = _sharing_denied_reason(setup["project_id"], None, session_factory=db_factory)
        assert reason is not None
        assert "signed in" in reason.lower()

    def test_viewer_denied_as_not_authorized(self, db_factory, setup):
        from shyfem_ui.pages.home import _sharing_denied_reason

        reason = _sharing_denied_reason(
            setup["project_id"], _user(setup["charlie_id"]), session_factory=db_factory
        )
        assert reason is not None
        assert "authorized" in reason.lower()

    def test_non_member_denied_as_not_authorized(self, db_factory, setup):
        from shyfem_ui.pages.home import _sharing_denied_reason

        reason = _sharing_denied_reason(
            setup["project_id"], _user(setup["bob_id"]), session_factory=db_factory
        )
        assert reason is not None
        assert "authorized" in reason.lower()

    def test_unresolved_and_unauthorized_messages_differ(self, db_factory, setup):
        """The two rejection cases must surface distinct messages."""
        from shyfem_ui.pages.home import _sharing_denied_reason

        unresolved = _sharing_denied_reason(setup["project_id"], None, session_factory=db_factory)
        unauthorized = _sharing_denied_reason(
            setup["project_id"], _user(setup["bob_id"]), session_factory=db_factory
        )
        assert unresolved != unauthorized
