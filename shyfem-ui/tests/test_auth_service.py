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


@pytest.fixture()
def db_session():
    """Raw SQLAlchemy session backed by an in-memory SQLite database.

    Yields a single open session for use in tests that need direct DB access.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


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
        user = auth_service.create_user("alice", "pass123", email="alice@example.com")
        assert user["id"] is not None
        assert user["username"] == "alice"
        assert user["role"] == "user"
        assert user["is_active"] is True

    def test_create_admin(self, auth_service):
        user = auth_service.create_user("boss", "admin-pass", role="admin", email="boss@example.com")
        assert user["role"] == "admin"

    def test_create_duplicate_raises_value_error(self, auth_service):
        auth_service.create_user("alice", "pass1", email="alice@example.com")
        with pytest.raises(ValueError, match="Username already exists"):
            auth_service.create_user("alice", "pass2", email="alice2@example.com")

    def test_get_user(self, auth_service):
        created = auth_service.create_user("bob", "pass", email="bob@example.com")
        fetched = auth_service.get_user(created["id"])
        assert fetched is not None
        assert fetched["username"] == "bob"

    def test_get_user_not_found(self, auth_service):
        assert auth_service.get_user(9999) is None

    def test_list_users(self, auth_service):
        auth_service.create_user("u1", "p1", email="u1@example.com")
        auth_service.create_user("u2", "p2", email="u2@example.com")
        users = auth_service.list_users()
        assert len(users) == 2
        assert users[0]["username"] == "u1"
        assert users[1]["username"] == "u2"

    def test_update_display_name(self, auth_service):
        created = auth_service.create_user("carol", "pass", email="carol@example.com")
        updated = auth_service.update_user(
            created["id"], display_name="Carol D."
        )
        assert updated is not None
        assert updated["display_name"] == "Carol D."

    def test_update_user_not_found(self, auth_service):
        assert auth_service.update_user(9999, display_name="X") is None

    def test_deactivate_user(self, auth_service):
        created = auth_service.create_user("dave", "pass", email="dave@example.com")
        assert auth_service.deactivate_user(created["id"]) is True
        fetched = auth_service.get_user(created["id"])
        assert fetched["is_active"] is False

    def test_deactivate_not_found(self, auth_service):
        assert auth_service.deactivate_user(9999) is False

    def test_reset_password(self, auth_service):
        created = auth_service.create_user("eve", "old-pass", email="eve@example.com")
        assert auth_service.reset_password(created["id"], "new-pass") is True
        # Old password should fail, new should work
        assert auth_service.authenticate("eve", "old-pass") is None
        assert auth_service.authenticate("eve", "new-pass") is not None

    def test_reset_password_not_found(self, auth_service):
        assert auth_service.reset_password(9999, "whatever") is False

    def test_change_role(self, auth_service):
        created = auth_service.create_user("frank", "pass", email="frank@example.com")
        updated = auth_service.update_user(created["id"], role="admin")
        assert updated["role"] == "admin"


# ------------------------------------------------------------------
# Authentication
# ------------------------------------------------------------------


class TestAuthenticate:

    def test_authenticate_valid(self, auth_service):
        auth_service.create_user("alice", "s3cret", email="alice@example.com")
        result = auth_service.authenticate("alice", "s3cret")
        assert result is not None
        assert result["username"] == "alice"

    def test_authenticate_wrong_password(self, auth_service):
        auth_service.create_user("alice", "s3cret", email="alice@example.com")
        assert auth_service.authenticate("alice", "wrong") is None

    def test_authenticate_nonexistent_user(self, auth_service):
        assert auth_service.authenticate("ghost", "pass") is None

    def test_authenticate_inactive_user(self, auth_service):
        created = auth_service.create_user("alice", "s3cret", email="alice@example.com")
        auth_service.deactivate_user(created["id"])
        assert auth_service.authenticate("alice", "s3cret") is None


# ------------------------------------------------------------------
# Session management
# ------------------------------------------------------------------


class TestSessionManagement:

    def test_create_session_returns_64_char_token(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        token = auth_service.create_session(user["id"])
        assert isinstance(token, str)
        assert len(token) == 64

    def test_validate_valid_session(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        token = auth_service.create_session(user["id"], ttl_hours=1)
        result = auth_service.validate_session(token)
        assert result is not None
        assert result["username"] == "alice"

    def test_validate_expired_session(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        token = auth_service.create_session(user["id"], ttl_hours=0)
        assert auth_service.validate_session(token) is None

    def test_validate_invalid_token(self, auth_service):
        assert auth_service.validate_session("bogus-token") is None

    def test_validate_session_inactive_user(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        token = auth_service.create_session(user["id"], ttl_hours=24)
        auth_service.deactivate_user(user["id"])
        assert auth_service.validate_session(token) is None

    def test_delete_session(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        token = auth_service.create_session(user["id"])
        assert auth_service.delete_session(token) is True
        assert auth_service.validate_session(token) is None

    def test_delete_nonexistent_session(self, auth_service):
        assert auth_service.delete_session("no-such-token") is False

    def test_cleanup_expired_sessions(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        # Create two expired sessions and one valid
        auth_service.create_session(user["id"], ttl_hours=0)
        auth_service.create_session(user["id"], ttl_hours=0)
        valid_token = auth_service.create_session(user["id"], ttl_hours=24)
        removed = auth_service.cleanup_expired_sessions()
        assert removed == 2
        # Valid session should still work
        assert auth_service.validate_session(valid_token) is not None


# ------------------------------------------------------------------
# WS-auth tokens (bridge HTTP session → Shiny WebSocket scope)
# ------------------------------------------------------------------


class TestWSToken:

    def test_create_and_validate_returns_user(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        sess = auth_service.create_session(user["id"])
        ws = auth_service.create_ws_token(user["id"], sess)
        assert isinstance(ws, str)
        assert ws != sess  # distinct from cookie token
        resolved = auth_service.validate_ws_token(ws)
        assert resolved is not None
        assert resolved["id"] == user["id"]
        assert resolved["username"] == "alice"

    def test_unknown_token_returns_none(self, auth_service):
        assert auth_service.validate_ws_token("nope") is None

    def test_invalid_when_parent_session_gone(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        sess = auth_service.create_session(user["id"])
        ws = auth_service.create_ws_token(user["id"], sess)
        auth_service.delete_session(sess)  # logout
        # WS token inherits session death even though its own row may linger
        # until cleanup; validation must refuse it.
        assert auth_service.validate_ws_token(ws) is None

    def test_invalid_when_parent_session_expired(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        sess = auth_service.create_session(user["id"], ttl_hours=0)
        ws = auth_service.create_ws_token(user["id"], sess)
        assert auth_service.validate_ws_token(ws) is None

    def test_invalid_when_user_deactivated(self, auth_service):
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        sess = auth_service.create_session(user["id"])
        ws = auth_service.create_ws_token(user["id"], sess)
        auth_service.deactivate_user(user["id"])
        assert auth_service.validate_ws_token(ws) is None

    def test_logout_purges_ws_token_rows(self, auth_service):
        """delete_session must remove WS tokens spawned by the session, not
        just rely on validate_ws_token refusing them by inheritance."""
        from shyfem_ui.models.user import WSAuthToken
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        sess = auth_service.create_session(user["id"])
        auth_service.create_ws_token(user["id"], sess)
        auth_service.create_ws_token(user["id"], sess)
        auth_service.delete_session(sess)
        with auth_service._session_factory() as db:
            remaining = db.query(WSAuthToken).filter_by(session_token=sess).count()
        assert remaining == 0

    def test_cleanup_removes_expired_ws_tokens(self, auth_service):
        """cleanup_expired_sessions must also purge expired WS tokens and
        include them in the returned count."""
        user = auth_service.create_user("alice", "pass", email="alice@example.com")
        sess = auth_service.create_session(user["id"], ttl_hours=24)
        expired_ws = auth_service.create_ws_token(user["id"], sess, ttl_hours=-1)
        valid_ws = auth_service.create_ws_token(user["id"], sess, ttl_hours=24)
        removed = auth_service.cleanup_expired_sessions()
        assert removed >= 1
        assert auth_service.validate_ws_token(expired_ws) is None
        assert auth_service.validate_ws_token(valid_ws) is not None


# ------------------------------------------------------------------
# Bootstrap
# ------------------------------------------------------------------


class TestEnsureAdmin:

    def test_creates_admin_when_none_exists(self, auth_service):
        admin = auth_service.ensure_admin("admin", "admin-pass", email="admin@example.com")
        assert admin["username"] == "admin"
        assert admin["role"] == "admin"

    def test_skips_creation_when_admin_exists(self, auth_service):
        first = auth_service.ensure_admin("admin", "first-pass", email="admin@example.com")
        second = auth_service.ensure_admin("admin2", "second-pass", email="admin2@example.com")
        # Should return the existing admin, not create a new one
        assert second["id"] == first["id"]
        assert second["username"] == "admin"
        # Original password should still work
        assert auth_service.authenticate("admin", "first-pass") is not None


# ------------------------------------------------------------------
# Email enforcement and home directory creation
# ------------------------------------------------------------------


class TestCreateUserEmailAndDirectory:

    def test_create_non_tutorial_user_requires_email(self, auth_service):
        """Creating a non-tutorial user without email raises ValueError."""
        with pytest.raises(ValueError, match="email"):
            auth_service.create_user("alice", "pass1234", role="user")

    def test_create_tutorial_user_no_email_required(self, auth_service):
        """Creating a tutorial user without email is allowed."""
        result = auth_service.create_user("user", "user", role="tutorial")
        assert result["username"] == "user"
        assert result["email"] is None

    def test_create_user_with_email_succeeds(self, auth_service):
        """Creating a user with a valid email succeeds."""
        result = auth_service.create_user(
            "bob", "pass1234", role="user", email="bob@example.com"
        )
        assert result["email"] == "bob@example.com"

    def test_create_user_duplicate_email_raises(self, auth_service):
        """Duplicate email raises ValueError."""
        auth_service.create_user("alice", "pass1234", role="user", email="alice@x.com")
        with pytest.raises(ValueError, match="email"):
            auth_service.create_user("alice2", "pass1234", role="user", email="alice@x.com")

    def test_create_user_creates_home_dir(self, auth_service, tmp_path):
        """create_user creates the home directory on disk."""
        auth_service.create_user(
            "carol", "pass1234", role="user",
            email="carol@example.com",
            user_data_root=tmp_path,
        )
        assert (tmp_path / "carol").is_dir()

    def test_create_tutorial_user_no_dir_created(self, auth_service, tmp_path):
        """Tutorial user does not get a home directory."""
        auth_service.create_user("user", "user", role="tutorial", user_data_root=tmp_path)
        assert not (tmp_path / "user").exists()

    def test_create_user_dir_permission_error_rolls_back(self, auth_service, tmp_path):
        """If directory creation fails, the user record is NOT saved."""
        import os
        os.chmod(tmp_path, 0o444)
        try:
            with pytest.raises(PermissionError):
                auth_service.create_user(
                    "dave", "pass1234", role="user",
                    email="dave@example.com",
                    user_data_root=tmp_path,
                )
            # User must not be in DB
            users = auth_service.list_users()
            assert not any(u["username"] == "dave" for u in users)
        finally:
            os.chmod(tmp_path, 0o755)


# ------------------------------------------------------------------
# Password rehashing on login
# ------------------------------------------------------------------


class TestAuthenticateRehash:

    def test_authenticate_rehashes_when_needed(self, db_session):
        """Regression: when a stored hash uses weaker argon2 params than current
        defaults, authenticate() must rehash and persist on a successful login."""
        from argon2 import PasswordHasher
        from shyfem_ui.services.auth_service import AuthService
        from shyfem_ui.models.user import User

        # Create a hash with weaker-than-default parameters that needs_rehash
        weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
        user = User(username="alice", email="a@x.com",
                    password_hash=weak.hash("pw"), role="user")
        db_session.add(user)
        db_session.commit()
        old_hash = user.password_hash

        svc = AuthService(session_factory=lambda: db_session)
        result = svc.authenticate("alice", "pw")
        assert result is not None, "authenticate must return user on success"

        # Re-query the user to see the persisted hash (authenticate() calls
        # session.close() which expires attached objects).
        from shyfem_ui.models.user import User as _User
        updated_user = db_session.query(_User).filter_by(username="alice").first()
        assert updated_user is not None
        assert updated_user.password_hash != old_hash, (
            "expected hash to be rehashed with stronger params"
        )

        # Bonus: the rehashed user must still authenticate with the same password
        result2 = svc.authenticate("alice", "pw")
        assert result2 is not None, (
            "rehashed user must continue to authenticate with same password"
        )
