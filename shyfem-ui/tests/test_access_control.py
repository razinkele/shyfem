"""Tests for access control helper."""

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
            setup["project_id"],
            _user(setup["admin_id"], "admin"),
            session_factory=db_factory,
        )
        assert result == "admin"

    def test_owner_has_all_roles(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access

        for min_role in ("viewer", "editor", "owner"):
            result = check_project_access(
                setup["project_id"],
                _user(setup["alice_id"]),
                min_role=min_role,
                session_factory=db_factory,
            )
            assert result == "owner", f"owner should satisfy min_role={min_role}"

    def test_viewer_satisfies_viewer(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access

        result = check_project_access(
            setup["project_id"],
            _user(setup["charlie_id"]),
            min_role="viewer",
            session_factory=db_factory,
        )
        assert result == "viewer"

    def test_viewer_denied_editor(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access

        result = check_project_access(
            setup["project_id"],
            _user(setup["charlie_id"]),
            min_role="editor",
            session_factory=db_factory,
        )
        assert result is None

    def test_no_access_denied(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access

        result = check_project_access(
            setup["project_id"],
            _user(setup["bob_id"]),
            session_factory=db_factory,
        )
        assert result is None

    def test_nonexistent_project(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access

        result = check_project_access(
            99999,
            _user(setup["alice_id"]),
            session_factory=db_factory,
        )
        assert result is None

    def test_default_min_role_is_viewer(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access

        result = check_project_access(
            setup["project_id"],
            _user(setup["charlie_id"]),
            session_factory=db_factory,
        )
        assert result == "viewer"


class TestEditorDeniedReason:
    """Fail-CLOSED server-side guard for edit-level mutation handlers.

    Behind the Shiny Server proxy the WebSocket is admitted with ``user=None``
    (cookies are not forwarded), and the reactive inputs are live regardless of
    button visibility. So a write guard that only denies when an *explicit*
    user lacks access (``user is not None and check(...) is None``) fails OPEN:
    a viewer who never pushes the ``_wsauth`` token keeps ``user=None`` and
    sails through. ``editor_denied_reason`` fails CLOSED in server mode — a
    missing identity is denied — while preserving the local single-user desktop
    contract where ``user`` is legitimately None and access is allowed.
    """

    def test_server_mode_unresolved_actor_denied(self, db_factory, setup):
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(
            setup["project_id"], None, is_server_mode=True, session_factory=db_factory
        )
        assert reason is not None

    def test_local_mode_unresolved_actor_allowed(self, db_factory, setup):
        """Local desktop mode has no auth — user is always None and allowed."""
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(
            setup["project_id"], None, is_server_mode=False, session_factory=db_factory
        )
        assert reason is None

    def test_server_mode_owner_allowed(self, db_factory, setup):
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(
            setup["project_id"],
            _user(setup["alice_id"]),
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert reason is None

    def test_server_mode_admin_allowed(self, db_factory, setup):
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(
            setup["project_id"],
            _user(setup["admin_id"], "admin"),
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert reason is None

    def test_server_mode_viewer_denied_for_editor_role(self, db_factory, setup):
        """A viewer (charlie) lacks editor access — denied even in server mode."""
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(
            setup["project_id"],
            _user(setup["charlie_id"]),
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert reason is not None

    def test_server_mode_non_member_denied(self, db_factory, setup):
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(
            setup["project_id"],
            _user(setup["bob_id"]),
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert reason is not None

    def test_unresolved_and_unauthorized_messages_differ(self, db_factory, setup):
        """The two rejection cases must surface distinct, actionable messages."""
        from shyfem_ui.services.access_control import editor_denied_reason

        unresolved = editor_denied_reason(
            setup["project_id"], None, is_server_mode=True, session_factory=db_factory
        )
        unauthorized = editor_denied_reason(
            setup["project_id"],
            _user(setup["bob_id"]),
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert unresolved != unauthorized

    def test_min_role_viewer_allows_viewer(self, db_factory, setup):
        """With min_role='viewer', charlie (a viewer) is allowed in server mode."""
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(
            setup["project_id"],
            _user(setup["charlie_id"]),
            min_role="viewer",
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert reason is None

    def test_is_server_mode_auto_detected_from_config(self, db_factory, setup, monkeypatch):
        """Omitting is_server_mode resolves it from the global config."""
        import shyfem_ui.config as cfg_mod
        from shyfem_ui.services.access_control import editor_denied_reason

        cfg = cfg_mod.get_config()
        monkeypatch.setattr(cfg, "deployment_mode", "server")
        # server mode + unresolved actor => denied without an explicit flag
        assert (
            editor_denied_reason(setup["project_id"], None, session_factory=db_factory) is not None
        )
        monkeypatch.setattr(cfg, "deployment_mode", "local")
        assert editor_denied_reason(setup["project_id"], None, session_factory=db_factory) is None


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
            setup["project_id"],
            _user(setup["charlie_id"]),
            min_role="editor",
            session_factory=db_factory,
        )
        assert result == "editor"

    def test_editor_denied_owner(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        from shyfem_ui.services.sharing_service import SharingService

        svc = SharingService(session_factory=db_factory)
        svc.share_project(setup["project_id"], setup["charlie_id"], "editor")

        result = check_project_access(
            setup["project_id"],
            _user(setup["charlie_id"]),
            min_role="owner",
            session_factory=db_factory,
        )
        assert result is None
