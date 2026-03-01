"""Authentication service -- password hashing, sessions, user CRUD."""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from shyfem_ui.models.user import AuthSession, User

logger = logging.getLogger(__name__)
_ph = PasswordHasher()


class AuthService:
    """Manages user accounts, password verification, and auth sessions."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from shyfem_ui.db.base import get_session_factory

            session_factory = get_session_factory()
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Password hashing
    # ------------------------------------------------------------------

    @staticmethod
    def hash_password(plain: str) -> str:
        """Hash a plaintext password using argon2."""
        return _ph.hash(plain)

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        """Verify a plaintext password against an argon2 hash.

        Returns True if the password matches, False otherwise.
        """
        try:
            return _ph.verify(hashed, plain)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        display_name: str | None = None,
        email: str | None = None,
    ) -> dict:
        """Create a new user account.

        Args:
            username: Unique login name.
            password: Plaintext password (will be hashed).
            role: User role -- "user" or "admin".
            display_name: Optional display name.
            email: Optional email address.

        Returns:
            Dict with user fields.

        Raises:
            ValueError: If the username already exists.
        """
        session = self._session_factory()
        try:
            existing = session.query(User).filter_by(username=username).first()
            if existing is not None:
                raise ValueError(f"Username already exists: {username}")

            user = User(
                username=username,
                password_hash=self.hash_password(password),
                role=role,
                display_name=display_name,
                email=email,
                is_active=True,
            )
            session.add(user)
            session.commit()
            return self._user_to_dict(user)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user(self, user_id: int) -> dict | None:
        """Get a user by ID.

        Returns:
            Dict with user fields, or None if not found.
        """
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return None
            return self._user_to_dict(user)
        finally:
            session.close()

    def list_users(self) -> list[dict]:
        """List all users.

        Returns:
            List of dicts with user fields.
        """
        session = self._session_factory()
        try:
            users = session.query(User).order_by(User.id).all()
            return [self._user_to_dict(u) for u in users]
        finally:
            session.close()

    def update_user(self, user_id: int, **kwargs) -> dict | None:
        """Update user fields (display_name, email, role).

        Args:
            user_id: User to update.
            **kwargs: Fields to update (display_name, email, role).

        Returns:
            Updated user dict, or None if not found.
        """
        allowed = {"display_name", "email", "role", "is_active"}
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return None
            for key, value in kwargs.items():
                if key in allowed:
                    setattr(user, key, value)
            session.commit()
            return self._user_to_dict(user)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def deactivate_user(self, user_id: int) -> bool:
        """Deactivate a user account.

        Returns:
            True if the user was found and deactivated, False if not found.
        """
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return False
            user.is_active = False
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def reset_password(self, user_id: int, new_password: str) -> bool:
        """Reset a user's password.

        Returns:
            True if the user was found and password was reset, False if not found.
        """
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return False
            user.password_hash = self.hash_password(new_password)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> dict | None:
        """Authenticate a user by username and password.

        Returns:
            User dict if credentials are valid and user is active, None otherwise.
        """
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(username=username).first()
            if user is None:
                return None
            if not user.is_active:
                return None
            if not self.verify_password(password, user.password_hash):
                return None
            return self._user_to_dict(user)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(
        self,
        user_id: int,
        ttl_hours: int = 24,
        ip_address: str | None = None,
    ) -> str:
        """Create an authenticated session for a user.

        Args:
            user_id: User to create a session for.
            ttl_hours: Session time-to-live in hours.
            ip_address: Optional IP address of the client.

        Returns:
            64-character hex session token.
        """
        token = secrets.token_hex(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        session = self._session_factory()
        try:
            auth_session = AuthSession(
                token=token,
                user_id=user_id,
                expires_at=expires_at,
                ip_address=ip_address,
            )
            session.add(auth_session)
            session.commit()
            return token
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def validate_session(self, token: str) -> dict | None:
        """Validate a session token.

        Checks that the session exists, has not expired, and the user is active.
        Deletes the session if it has expired.

        Returns:
            User dict if valid, None otherwise.
        """
        session = self._session_factory()
        try:
            auth_session = session.query(AuthSession).filter_by(token=token).first()
            if auth_session is None:
                return None

            if auth_session.is_expired:
                session.delete(auth_session)
                session.commit()
                return None

            user = session.query(User).filter_by(id=auth_session.user_id).first()
            if user is None or not user.is_active:
                return None

            return self._user_to_dict(user)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_session(self, token: str) -> bool:
        """Delete a session by token.

        Returns:
            True if the session was found and deleted, False otherwise.
        """
        session = self._session_factory()
        try:
            auth_session = session.query(AuthSession).filter_by(token=token).first()
            if auth_session is None:
                return False
            session.delete(auth_session)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions.

        Returns:
            Number of sessions removed.
        """
        now = datetime.now(timezone.utc)
        session = self._session_factory()
        try:
            expired = session.query(AuthSession).filter(AuthSession.expires_at <= now).all()
            count = len(expired)
            for s in expired:
                session.delete(s)
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def ensure_user(self, username: str, password: str) -> dict:
        """Ensure a default (non-admin) user exists.

        If a user with the given username already exists, returns it unchanged.
        Otherwise creates a new user with role "user".

        Returns:
            Dict with user fields.
        """
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(username=username).first()
            if user is not None:
                return self._user_to_dict(user)
        finally:
            session.close()

        return self.create_user(
            username=username,
            password=password,
            role="user",
        )

    def ensure_admin(self, username: str, password: str) -> dict:
        """Ensure an admin user exists.

        If no admin user exists, creates one with the given credentials.
        If an admin already exists, returns it without modifying the password.

        Returns:
            Dict with admin user fields.
        """
        session = self._session_factory()
        try:
            admin = session.query(User).filter_by(role="admin").first()
            if admin is not None:
                return self._user_to_dict(admin)
        finally:
            session.close()

        # No admin exists -- create one
        return self.create_user(
            username=username,
            password=password,
            role="admin",
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _user_to_dict(user: User) -> dict:
        """Convert a User ORM object to a plain dict."""
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role,
            "is_active": bool(user.is_active),
        }
