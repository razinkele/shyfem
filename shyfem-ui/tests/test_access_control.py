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

    def test_server_mode_none_project_denied_for_authenticated_user(self, db_factory, setup):
        """A write with no active project must be DENIED in server mode, even for
        a fully-authenticated owner/admin — there is no project to authorize
        against, so the only safe answer is deny. This closes the bypass where a
        guard nested inside ``if active_project is not None`` was skipped entirely
        when no project was active."""
        from shyfem_ui.services.access_control import editor_denied_reason

        for user in (
            _user(setup["alice_id"]),  # owner
            _user(setup["admin_id"], "admin"),  # admin
        ):
            reason = editor_denied_reason(
                None, user, is_server_mode=True, session_factory=db_factory
            )
            assert reason is not None, f"no-project write must be denied for {user!r}"

    def test_server_mode_none_project_message_differs_from_unauthorized(self, db_factory, setup):
        """The no-active-project denial is its own actionable message."""
        from shyfem_ui.services.access_control import editor_denied_reason

        no_project = editor_denied_reason(
            None, _user(setup["alice_id"]), is_server_mode=True, session_factory=db_factory
        )
        unauthorized = editor_denied_reason(
            setup["project_id"],
            _user(setup["bob_id"]),
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert no_project != unauthorized

    def test_local_mode_none_project_allowed(self, db_factory, setup):
        """Local desktop mode has no auth — a None project with None user is
        allowed (backward-compatible single-user contract)."""
        from shyfem_ui.services.access_control import editor_denied_reason

        reason = editor_denied_reason(None, None, is_server_mode=False, session_factory=db_factory)
        assert reason is None

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

    def test_tutorial_denied_for_write_despite_editor_grant(self, db_factory, setup):
        """A ROLE_TUTORIAL account is read-only: it is denied a write (min_role
        editor) even if it was granted project-editor access. Enforced centrally
        in the gate so it applies to every write handler."""
        from shyfem_ui.models.user import ProjectPermission, User
        from shyfem_ui.services.access_control import editor_denied_reason

        db = db_factory()
        tut = User(username="tut", password_hash="x", role="tutorial")
        db.add(tut)
        db.flush()
        db.add(ProjectPermission(project_id=setup["project_id"], user_id=tut.id, role="editor"))
        db.commit()
        tut_id = tut.id
        db.close()

        reason = editor_denied_reason(
            setup["project_id"],
            _user(tut_id, "tutorial"),
            min_role="editor",
            is_server_mode=True,
            session_factory=db_factory,
        )
        assert reason is not None

    def test_tutorial_allowed_for_read(self, db_factory, setup):
        """A ROLE_TUTORIAL account may still READ (min_role viewer)."""
        from shyfem_ui.models.user import ProjectPermission, User
        from shyfem_ui.services.access_control import editor_denied_reason

        db = db_factory()
        tut = User(username="tut2", password_hash="x", role="tutorial")
        db.add(tut)
        db.flush()
        db.add(ProjectPermission(project_id=setup["project_id"], user_id=tut.id, role="viewer"))
        db.commit()
        tut_id = tut.id
        db.close()

        reason = editor_denied_reason(
            setup["project_id"],
            _user(tut_id, "tutorial"),
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


class TestJobCancelDeniedReason:
    """A job may be cancelled by its owner (user_id match), an admin, OR a user
    with editor access to the job's project. Fail-closed on user=None in server
    mode; allowed in local mode."""

    def _call(self, **kw):
        from shyfem_ui.services.access_control import job_cancel_denied_reason

        return job_cancel_denied_reason(**kw)

    def test_local_mode_allows_none_user(self, db_factory, setup):
        assert (
            self._call(
                job_user_id=setup["alice_id"],
                job_project_id=setup["project_id"],
                user=None,
                is_server_mode=False,
                session_factory=db_factory,
            )
            is None
        )

    def test_server_mode_denies_none_user(self, db_factory, setup):
        assert (
            self._call(
                job_user_id=setup["alice_id"],
                job_project_id=setup["project_id"],
                user=None,
                is_server_mode=True,
                session_factory=db_factory,
            )
            is not None
        )

    def test_owner_may_cancel_own_job(self, db_factory, setup):
        # bob owns the job but has NO project access — ownership alone suffices.
        assert (
            self._call(
                job_user_id=setup["bob_id"],
                job_project_id=setup["project_id"],
                user=_user(setup["bob_id"]),
                is_server_mode=True,
                session_factory=db_factory,
            )
            is None
        )

    def test_admin_may_cancel_any_job(self, db_factory, setup):
        assert (
            self._call(
                job_user_id=setup["alice_id"],
                job_project_id=setup["project_id"],
                user=_user(setup["admin_id"], "admin"),
                is_server_mode=True,
                session_factory=db_factory,
            )
            is None
        )

    def test_project_editor_may_cancel(self, db_factory, setup):
        # Give bob editor on alice's project; bob is not the job owner.
        db = db_factory()
        db.add(
            ProjectPermission(
                project_id=setup["project_id"], user_id=setup["bob_id"], role="editor"
            )
        )
        db.commit()
        db.close()
        assert (
            self._call(
                job_user_id=setup["alice_id"],
                job_project_id=setup["project_id"],
                user=_user(setup["bob_id"]),
                is_server_mode=True,
                session_factory=db_factory,
            )
            is None
        )

    def test_viewer_denied(self, db_factory, setup):
        # charlie is a viewer (set up in fixture) and not the job owner.
        assert (
            self._call(
                job_user_id=setup["alice_id"],
                job_project_id=setup["project_id"],
                user=_user(setup["charlie_id"]),
                is_server_mode=True,
                session_factory=db_factory,
            )
            is not None
        )

    def test_stranger_denied(self, db_factory, setup):
        # bob: not owner, no project access.
        assert (
            self._call(
                job_user_id=setup["alice_id"],
                job_project_id=setup["project_id"],
                user=_user(setup["bob_id"]),
                is_server_mode=True,
                session_factory=db_factory,
            )
            is not None
        )


class TestIdentityDeniedReason:
    """Create/clone/import have no pre-existing project to authorize against,
    but in server mode an unresolved identity must still be DENIED — otherwise a
    project is created with owner_id=None (orphaned). Local mode allows None."""

    def _call(self, **kw):
        from shyfem_ui.services.access_control import identity_denied_reason

        return identity_denied_reason(**kw)

    def test_server_mode_denies_none_user(self):
        assert self._call(user=None, is_server_mode=True) is not None

    def test_server_mode_allows_resolved_user(self):
        assert self._call(user={"id": 1, "role": "user"}, is_server_mode=True) is None

    def test_local_mode_allows_none_user(self):
        assert self._call(user=None, is_server_mode=False) is None


class TestTutorialReadOnlyAcrossGates:
    """ROLE_TUTORIAL is read-only across EVERY mutation gate, not just the
    per-handler editor gate: project create/import (identity_denied_reason) and
    job cancel (job_cancel_denied_reason) must also deny a tutorial account."""

    _TUT = {"id": 99, "role": "tutorial"}

    def test_identity_denies_tutorial(self):
        from shyfem_ui.services.access_control import identity_denied_reason

        assert identity_denied_reason(self._TUT, is_server_mode=True) is not None

    def test_identity_allows_regular_user(self):
        from shyfem_ui.services.access_control import identity_denied_reason

        assert identity_denied_reason({"id": 1, "role": "user"}, is_server_mode=True) is None

    def test_job_cancel_denies_tutorial(self, db_factory, setup):
        from shyfem_ui.services.access_control import job_cancel_denied_reason

        # Even as the job owner, a tutorial account may not cancel (read-only).
        assert (
            job_cancel_denied_reason(
                job_user_id=self._TUT["id"],
                job_project_id=setup["project_id"],
                user=self._TUT,
                is_server_mode=True,
                session_factory=db_factory,
            )
            is not None
        )
