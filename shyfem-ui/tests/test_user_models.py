"""Tests for user management database models."""

from datetime import datetime, timedelta, timezone

from shyfem_ui.models.user import AuthSession, ProjectPermission, User


class TestUserModel:
    def test_user_creation(self):
        user = User(
            username="alice",
            display_name="Alice Smith",
            email="alice@example.com",
            password_hash="$argon2id$dummy",
            role="user",
            is_active=True,
        )
        assert user.username == "alice"
        assert user.role == "user"
        assert user.is_active is True

    def test_user_repr(self):
        user = User(id=1, username="bob", password_hash="x", role="admin")
        assert "bob" in repr(user)
        assert "admin" in repr(user)

    def test_user_is_admin(self):
        admin = User(username="a", password_hash="x", role="admin")
        regular = User(username="b", password_hash="x", role="user")
        assert admin.is_admin is True
        assert regular.is_admin is False


class TestAuthSessionModel:
    def test_session_creation(self):
        now = datetime.now(timezone.utc)
        sess = AuthSession(
            token="abc123",
            user_id=1,
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        assert sess.token == "abc123"
        assert sess.user_id == 1

    def test_session_is_expired(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        expired = AuthSession(token="a", user_id=1, expires_at=past)
        valid = AuthSession(token="b", user_id=1, expires_at=future)
        assert expired.is_expired is True
        assert valid.is_expired is False


class TestProjectPermissionModel:
    def test_permission_creation(self):
        perm = ProjectPermission(project_id=1, user_id=2, role="viewer")
        assert perm.role == "viewer"

    def test_permission_repr(self):
        perm = ProjectPermission(id=1, project_id=10, user_id=20, role="editor")
        assert "10" in repr(perm)
        assert "20" in repr(perm)


class TestProjectOwnerColumn:
    def test_project_has_owner_id(self):
        from shyfem_ui.models.project import Project
        p = Project(name="test", work_dir="/tmp/test")
        assert hasattr(p, "owner_id")
        assert p.owner_id is None

class TestJobUserColumn:
    def test_job_has_user_id(self):
        from shyfem_ui.models.project import Job
        j = Job(
            job_uuid="abc", name="test", job_type="shyfem",
            command="", working_dir="/tmp",
        )
        assert hasattr(j, "user_id")
        assert j.user_id is None


def test_home_dir_returns_root_slash_username():
    """User.home_dir(root) returns Path(root) / username."""
    from pathlib import Path

    from shyfem_ui.models.user import User
    u = User(username="alice", password_hash="x", role="user")
    assert u.home_dir(Path("/data/shyfem")) == Path("/data/shyfem/alice")


def test_home_dir_tutorial_user():
    """Tutorial user home_dir is computed the same way (directory skipped at creation)."""
    from pathlib import Path

    from shyfem_ui.models.user import User
    u = User(username="user", password_hash="x", role="tutorial")
    assert u.home_dir(Path("/data/shyfem")) == Path("/data/shyfem/user")


def test_is_tutorial_property():
    """User.is_tutorial returns True only for role='tutorial'."""
    from shyfem_ui.models.user import User
    t = User(username="u", password_hash="x", role="tutorial")
    r = User(username="u", password_hash="x", role="user")
    assert t.is_tutorial is True
    assert r.is_tutorial is False
