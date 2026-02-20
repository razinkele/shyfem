"""Tests for AuthService -- password hashing, user CRUD, sessions, bootstrap."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models import project as _p  # noqa: F401 -- register models
from shyfem_ui.models import user as _u  # noqa: F401 -- register models
from shyfem_ui.services.auth_service import AuthService


@pytest.fixture()
def auth_service():
    """AuthService backed by an in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return AuthService(session_factory=Session)


# ------------------------------------------------------------------
# Password hashing
# ------------------------------------------------------------------


class TestPasswordHashing:

    def test_hash_returns_argon2_string(self):
        hashed = AuthService.hash_password("secret123")
        assert hashed.startswith("$argon2")

    def test_verify_correct_password(self):
        hashed = AuthService.hash_password("correct-horse")
        assert AuthService.verify_password("correct-horse", hashed) is True

    def test_verify_wrong_password(self):
        hashed = AuthService.hash_password("correct-horse")
        assert AuthService.verify_password("wrong-horse", hashed) is False

    def test_verify_invalid_hash(self):
        assert AuthService.verify_password("anything", "not-a-valid-hash") is False


# ------------------------------------------------------------------
# User CRUD
# ------------------------------------------------------------------


class TestUserCRUD:

    def test_create_user(self, auth_service):
        user = auth_service.create_user("alice", "pass123")
        assert user["id"] is not None
        assert user["username"] == "alice"
        assert user["role"] == "user"
        assert user["is_active"] is True

    def test_create_admin(self, auth_service):
        user = auth_service.create_user("boss", "admin-pass", role="admin")
        assert user["role"] == "admin"

    def test_create_duplicate_raises_value_error(self, auth_service):
        auth_service.create_user("alice", "pass1")
        with pytest.raises(ValueError, match="Username already exists"):
            auth_service.create_user("alice", "pass2")

    def test_get_user(self, auth_service):
        created = auth_service.create_user("bob", "pass")
        fetched = auth_service.get_user(created["id"])
        assert fetched is not None
        assert fetched["username"] == "bob"

    def test_get_user_not_found(self, auth_service):
        assert auth_service.get_user(9999) is None

    def test_list_users(self, auth_service):
        auth_service.create_user("u1", "p1")
        auth_service.create_user("u2", "p2")
        users = auth_service.list_users()
        assert len(users) == 2
        assert users[0]["username"] == "u1"
        assert users[1]["username"] == "u2"

    def test_update_display_name(self, auth_service):
        created = auth_service.create_user("carol", "pass")
        updated = auth_service.update_user(
            created["id"], display_name="Carol D."
        )
        assert updated is not None
        assert updated["display_name"] == "Carol D."

    def test_update_user_not_found(self, auth_service):
        assert auth_service.update_user(9999, display_name="X") is None

    def test_deactivate_user(self, auth_service):
        created = auth_service.create_user("dave", "pass")
        assert auth_service.deactivate_user(created["id"]) is True
        fetched = auth_service.get_user(created["id"])
        assert fetched["is_active"] is False

    def test_deactivate_not_found(self, auth_service):
        assert auth_service.deactivate_user(9999) is False

    def test_reset_password(self, auth_service):
        created = auth_service.create_user("eve", "old-pass")
        assert auth_service.reset_password(created["id"], "new-pass") is True
        # Old password should fail, new should work
        assert auth_service.authenticate("eve", "old-pass") is None
        assert auth_service.authenticate("eve", "new-pass") is not None

    def test_reset_password_not_found(self, auth_service):
        assert auth_service.reset_password(9999, "whatever") is False

    def test_change_role(self, auth_service):
        created = auth_service.create_user("frank", "pass")
        updated = auth_service.update_user(created["id"], role="admin")
        assert updated["role"] == "admin"


# ------------------------------------------------------------------
# Authentication
# ------------------------------------------------------------------


class TestAuthenticate:

    def test_authenticate_valid(self, auth_service):
        auth_service.create_user("alice", "s3cret")
        result = auth_service.authenticate("alice", "s3cret")
        assert result is not None
        assert result["username"] == "alice"

    def test_authenticate_wrong_password(self, auth_service):
        auth_service.create_user("alice", "s3cret")
        assert auth_service.authenticate("alice", "wrong") is None

    def test_authenticate_nonexistent_user(self, auth_service):
        assert auth_service.authenticate("ghost", "pass") is None

    def test_authenticate_inactive_user(self, auth_service):
        created = auth_service.create_user("alice", "s3cret")
        auth_service.deactivate_user(created["id"])
        assert auth_service.authenticate("alice", "s3cret") is None


# ------------------------------------------------------------------
# Session management
# ------------------------------------------------------------------


class TestSessionManagement:

    def test_create_session_returns_64_char_token(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"])
        assert isinstance(token, str)
        assert len(token) == 64

    def test_validate_valid_session(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"], ttl_hours=1)
        result = auth_service.validate_session(token)
        assert result is not None
        assert result["username"] == "alice"

    def test_validate_expired_session(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"], ttl_hours=0)
        assert auth_service.validate_session(token) is None

    def test_validate_invalid_token(self, auth_service):
        assert auth_service.validate_session("bogus-token") is None

    def test_validate_session_inactive_user(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"], ttl_hours=24)
        auth_service.deactivate_user(user["id"])
        assert auth_service.validate_session(token) is None

    def test_delete_session(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"])
        assert auth_service.delete_session(token) is True
        assert auth_service.validate_session(token) is None

    def test_delete_nonexistent_session(self, auth_service):
        assert auth_service.delete_session("no-such-token") is False

    def test_cleanup_expired_sessions(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        # Create two expired sessions and one valid
        auth_service.create_session(user["id"], ttl_hours=0)
        auth_service.create_session(user["id"], ttl_hours=0)
        valid_token = auth_service.create_session(user["id"], ttl_hours=24)
        removed = auth_service.cleanup_expired_sessions()
        assert removed == 2
        # Valid session should still work
        assert auth_service.validate_session(valid_token) is not None


# ------------------------------------------------------------------
# Bootstrap
# ------------------------------------------------------------------


class TestEnsureAdmin:

    def test_creates_admin_when_none_exists(self, auth_service):
        admin = auth_service.ensure_admin("admin", "admin-pass")
        assert admin["username"] == "admin"
        assert admin["role"] == "admin"

    def test_skips_creation_when_admin_exists(self, auth_service):
        first = auth_service.ensure_admin("admin", "first-pass")
        second = auth_service.ensure_admin("admin2", "second-pass")
        # Should return the existing admin, not create a new one
        assert second["id"] == first["id"]
        assert second["username"] == "admin"
        # Original password should still work
        assert auth_service.authenticate("admin", "first-pass") is not None
