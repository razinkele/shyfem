"""Authentication service -- password hashing, sessions, user CRUD."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import HashingError, VerificationError, VerifyMismatchError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

try:
    from argon2.exceptions import InvalidHashError
except ImportError:
    from argon2.exceptions import InvalidHash as InvalidHashError  # argon2 <23

from shyfem_ui.models.user import ROLE_ADMIN, AuthSession, User, WSAuthToken, validate_username

logger = logging.getLogger(__name__)
_ph = PasswordHasher()
# Computed once at import so the missing-user/inactive-user branches of
# authenticate() can still pay the argon2 verification cost (N45): without
# this, those branches return early and response timing leaks which
# usernames exist / are active to an unauthenticated attacker.
_DUMMY_HASH = _ph.hash("x")


def _hash_token(raw: str) -> str:
    """The value stored in the DB for a session or WS-auth token (SEC-06).

    The browser and WebSocket client keep the raw token; the database keeps
    only its sha256 hex digest, so a copy of the database file cannot be
    replayed as a login. A fast hash (not argon2) is right here: the tokens
    are 256-bit random values, so there is nothing to brute-force, and the
    lookup stays an indexed equality on the digest. Every read and write of
    ``AuthSession.token``, ``WSAuthToken.token`` and
    ``WSAuthToken.session_token`` goes through this helper.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
        user_data_root: Path | None = None,
    ) -> dict:
        """Create a new user account.

        Args:
            username: Unique login name.
            password: Plaintext password (will be hashed).
            role: User role -- "user", "admin", or "tutorial".
            display_name: Optional display name.
            email: Email address. Required for non-tutorial accounts.
            user_data_root: If provided, creates {user_data_root}/{username}/ on disk.
                            Skipped for tutorial users. If creation fails, user is not saved.

        Returns:
            Dict with user fields.

        Raises:
            ValueError: If the username is unsafe (see ``validate_username``),
                username or email already exists, or email missing for
                non-tutorial.
            PermissionError: If directory creation fails.
        """
        from shyfem_ui.models.user import ROLE_TUTORIAL

        # Validate the username *before* any DB work: it becomes a
        # filesystem path segment (home_dir/confine_path), so an unsafe
        # value (e.g. '.', '..', containing '/' or '\x00') must never reach
        # the database (N43/F44).
        validate_username(username)

        # Validate email requirement
        if role != ROLE_TUTORIAL and not email:
            raise ValueError("email is required for non-tutorial accounts")

        session = self._session_factory()
        try:
            existing = session.query(User).filter_by(username=username).first()
            if existing is not None:
                raise ValueError(f"Username already exists: {username}")

            if email:
                existing_email = session.query(User).filter_by(email=email).first()
                if existing_email is not None:
                    raise ValueError(f"email already in use: {email}")

            user = User(
                username=username,
                password_hash=self.hash_password(password),
                role=role,
                display_name=display_name,
                email=email,
                is_active=True,
            )
            session.add(user)
            session.flush()  # get user.id before committing

            # Create home directory (non-tutorial only)
            if user_data_root and role != ROLE_TUTORIAL:
                home = user.home_dir(Path(user_data_root))
                home.mkdir(parents=True, exist_ok=True)  # raises PermissionError if not writable

            session.commit()
            return self._user_to_dict(user)
        except IntegrityError as e:
            # Concurrent insert raced past the existence checks above.
            session.rollback()
            raise ValueError("Username or email already taken — choose another.") from e
        except Exception:
            session.rollback()
            logger.exception("Database error in create_user")
            raise
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

        Raises:
            ValueError: If the change would leave no active admin (SEC-01).
        """
        allowed = {"display_name", "email", "role", "is_active"}
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return None
            was_active_admin = user.role == ROLE_ADMIN and user.is_active
            for key, value in kwargs.items():
                if key in allowed:
                    setattr(user, key, value)
            if was_active_admin and not (user.role == ROLE_ADMIN and user.is_active):
                if self._other_active_admins(session, user_id) == 0:
                    raise ValueError(
                        "Cannot demote or deactivate the last active admin; "
                        "make another user an admin first"
                    )
            session.commit()
            return self._user_to_dict(user)
        except Exception:
            session.rollback()
            logger.exception("Database error in update_user")
            raise
        finally:
            session.close()

    def delete_user(self, user_id: int) -> bool:
        """Delete a user account and all related records.

        Removes the user, their sessions (via cascade), and any project
        permissions. Does NOT delete the user's home directory on disk.

        Returns:
            True if the user was found and deleted, False if not found.

        Raises:
            ValueError: If attempting to delete the last admin user.
        """
        from shyfem_ui.models.user import ProjectPermission

        session = self._session_factory()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return False
            # Prevent deleting the last active admin (an inactive one cannot
            # sign in, so it does not count).
            if user.role == ROLE_ADMIN and user.is_active:
                if self._other_active_admins(session, user_id) == 0:
                    raise ValueError("Cannot delete the last admin user")
            from shyfem_ui.models.project import Job, Project
            from shyfem_ui.models.workflow import Workflow

            # No DB-level FK cascade, so clean up everything referencing this
            # user. Permissions + WS tokens are deleted; nullable ownership FKs
            # are NULLed so the underlying data survives (an admin can reassign)
            # rather than dangling at a now-deleted user id.
            session.query(ProjectPermission).filter_by(user_id=user_id).delete()
            session.query(WSAuthToken).filter_by(user_id=user_id).delete()
            session.query(Project).filter_by(owner_id=user_id).update({"owner_id": None})
            session.query(Job).filter_by(user_id=user_id).update({"user_id": None})
            session.query(Workflow).filter_by(user_id=user_id).update({"user_id": None})
            session.delete(user)
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("Database error in delete_user")
            raise
        finally:
            session.close()

    def reset_password(self, user_id: int, new_password: str) -> bool:
        """Reset a user's password and sign out every session they have.

        Sessions opened with the old password -- an open tab or a stolen
        cookie alike -- are deleted together with the WS-auth tokens minted
        from them, in the same transaction as the new hash, so a reset takes
        effect at the holder's next action rather than at session expiry.
        Resetting your own password therefore signs you out too.

        Returns:
            True if the user was found and password was reset, False if not found.
        """
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                return False
            user.password_hash = self.hash_password(new_password)
            session.query(WSAuthToken).filter_by(user_id=user_id).delete()
            session.query(AuthSession).filter_by(user_id=user_id).delete()
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("Database error in reset_password")
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
                # Verify against a dummy hash so the response takes roughly
                # the same time as a real failed login -- otherwise an
                # attacker can distinguish "no such user" from "wrong
                # password" by latency alone (N45).
                self.verify_password(password, _DUMMY_HASH)
                return None
            if not user.is_active:
                self.verify_password(password, _DUMMY_HASH)
                return None
            if not self.verify_password(password, user.password_hash):
                return None
            if _ph.check_needs_rehash(user.password_hash):
                try:
                    user.password_hash = _ph.hash(password)
                    session.commit()
                    logger.info(
                        "Rehashed password for user %s with current argon2 params",
                        user.username,
                    )
                except (HashingError, InvalidHashError, SQLAlchemyError):
                    logger.exception(
                        "Failed to persist rehashed password for user %s",
                        user.username,
                    )
                    try:
                        session.rollback()
                    except SQLAlchemyError:
                        logger.exception("Rollback after rehash failure also raised")
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
            64-character hex session token (raw: only its sha256 is stored).
        """
        token = secrets.token_hex(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        session = self._session_factory()
        try:
            auth_session = AuthSession(
                token=_hash_token(token),
                user_id=user_id,
                expires_at=expires_at,
                ip_address=ip_address,
            )
            session.add(auth_session)
            session.commit()
            return token
        except Exception:
            session.rollback()
            logger.exception("Database error in operation")
            raise
        finally:
            session.close()

    def validate_session(self, token: str) -> dict | None:
        """Validate a session token.

        Checks that the session exists, has not expired, and the user is active.
        Deletes the session if it has expired.

        Args:
            token: The raw token the client holds (the cookie value).

        Returns:
            User dict if valid, None otherwise.
        """
        return self._validate_session_hash(_hash_token(token))

    def _validate_session_hash(self, token_hash: str) -> dict | None:
        """validate_session() for an already-hashed token (as stored in
        ``WSAuthToken.session_token``): hashing it again would never match."""
        session = self._session_factory()
        try:
            auth_session = session.query(AuthSession).filter_by(token=token_hash).first()
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
            logger.exception("Database error in validate_session")
            raise
        finally:
            session.close()

    def delete_session(self, token: str) -> bool:
        """Delete a session by token.

        Also purges any WS-auth tokens minted from this session so a logout
        cleanly retires the WebSocket-side identity bridge.

        Returns:
            True if the session was found and deleted, False otherwise.
        """
        token_hash = _hash_token(token)
        session = self._session_factory()
        try:
            auth_session = session.query(AuthSession).filter_by(token=token_hash).first()
            if auth_session is None:
                return False
            session.query(WSAuthToken).filter_by(session_token=token_hash).delete()
            session.delete(auth_session)
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("Database error in delete_session")
            raise
        finally:
            session.close()

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions and WS-auth tokens.

        Returns:
            Combined count of rows removed (sessions + WS tokens).
        """
        now = datetime.now(timezone.utc)
        session = self._session_factory()
        try:
            expired = session.query(AuthSession).filter(AuthSession.expires_at <= now).all()
            count = len(expired)
            for s in expired:
                session.delete(s)
            expired_ws = session.query(WSAuthToken).filter(WSAuthToken.expires_at <= now).all()
            count += len(expired_ws)
            for w in expired_ws:
                session.delete(w)
            session.commit()
            return count
        except Exception:
            session.rollback()
            logger.exception("Database error in cleanup_expired_sessions")
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # WS-auth tokens (bridge HTTP session into Shiny WebSocket scope)
    # ------------------------------------------------------------------

    def create_ws_token(
        self,
        user_id: int,
        session_token: str,
        ttl_hours: int = 24,
    ) -> str:
        """Mint a WS-auth token bound to an existing HTTP session.

        Distinct from the session cookie value; validity inherits from the
        owning AuthSession (purged on logout, refused once expired).
        ``session_token`` is the raw cookie value; the row stores the sha256
        of both it and the new token, and the raw new token is returned.
        """
        token = secrets.token_hex(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        session = self._session_factory()
        try:
            session.add(
                WSAuthToken(
                    token=_hash_token(token),
                    session_token=_hash_token(session_token),
                    user_id=user_id,
                    expires_at=expires_at,
                )
            )
            session.commit()
            return token
        except Exception:
            session.rollback()
            logger.exception("Database error in create_ws_token")
            raise
        finally:
            session.close()

    def validate_ws_token(self, token: str) -> dict | None:
        """Validate a WS-auth token.

        Returns the user dict only if the token row exists, is unexpired,
        AND its parent HTTP session still validates (covers logout, parent
        expiry, and user deactivation in a single delegated check).
        """
        session = self._session_factory()
        try:
            row = session.query(WSAuthToken).filter_by(token=_hash_token(token)).first()
            if row is None:
                return None
            if row.is_expired:
                session.delete(row)
                session.commit()
                return None
            parent_hash = row.session_token
        except Exception:
            session.rollback()
            logger.exception("Database error in validate_ws_token")
            raise
        finally:
            session.close()
        return self._validate_session_hash(parent_hash)

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def ensure_user(
        self,
        username: str,
        password: str,
        email: str | None = None,
        role: str = "user",
        audit_service=None,
    ) -> dict:
        """Ensure a default (non-admin) user exists.

        If a user with the given username already exists, its role is forced
        to ``role`` (a deliberate shim: tutorial accounts created before the
        tutorial role existed kept role ``user``) and it is returned.
        Otherwise creates a new user with the specified role.

        The re-force rewrites an existing account's role on every start, so
        it is never silent: it logs a warning and, given ``audit_service``,
        writes a ``role_reforced`` audit entry (SEC-03).

        Args:
            username: Login name.
            password: Plaintext password.
            email: Email address. Required when creating a new non-tutorial user.
            role: Role to assign when creating a new user (default "user").
            audit_service: Optional AuditService for the re-force entry.

        Returns:
            Dict with user fields.
        """
        session = self._session_factory()
        try:
            user = session.query(User).filter_by(username=username).first()
            if user is not None:
                if user.role != role:
                    old_role = user.role
                    user.role = role
                    session.commit()
                    self._report_role_reforce(username, old_role, role, audit_service)
                return self._user_to_dict(user)
        finally:
            session.close()

        # Tutorial users don't require email; everyone else gets a localhost
        # placeholder when none is supplied so first-run bootstrap doesn't fail.
        from shyfem_ui.models.user import ROLE_TUTORIAL

        if email is None and role != ROLE_TUTORIAL:
            email = f"{username}@localhost"
        return self.create_user(
            username=username,
            password=password,
            role=role,
            email=email,
        )

    @staticmethod
    def _report_role_reforce(username: str, old_role: str, new_role: str, audit_service) -> None:
        """Log and audit ensure_user's role re-force. Best effort: never raises."""
        logger.warning(
            "ensure_user: role of existing user %r forced from %r to %r",
            username,
            old_role,
            new_role,
        )
        if audit_service is None:
            return
        try:
            audit_service.log(
                username="system",
                action="role_reforced",
                detail=f"target={username}, from={old_role}, to={new_role}",
            )
        except Exception:
            logger.exception("Failed to write role_reforced audit entry")

    def ensure_admin(self, username: str, password: str, email: str | None = None) -> dict:
        """Ensure an admin user exists.

        If no admin user exists, creates one with the given credentials.
        If an admin already exists, returns it without modifying the password.

        Args:
            username: Login name for the admin account.
            password: Plaintext password.
            email: Email address. If omitted when creating, defaults to
                ``{username}@localhost`` so first-run bootstrap doesn't fail
                when the operator hasn't configured an email.

        Returns:
            Dict with admin user fields.
        """
        session = self._session_factory()
        try:
            admin = session.query(User).filter_by(role=ROLE_ADMIN, is_active=True).first()
            if admin is not None:
                return self._user_to_dict(admin)
            # No active admin, but the configured account exists (demoted or
            # deactivated before the last-admin guard): restore it rather than
            # fail every worker start on "Username already exists" (SEC-01).
            # Its password is left as it is.
            existing = session.query(User).filter_by(username=username).first()
            if existing is not None:
                logger.warning("No active admin: restoring %r to an active admin account", username)
                existing.role = ROLE_ADMIN
                existing.is_active = True
                session.commit()
                return self._user_to_dict(existing)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        # No admin exists -- create one
        return self.create_user(
            username=username,
            password=password,
            role=ROLE_ADMIN,
            email=email or f"{username}@localhost",
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _other_active_admins(session, user_id: int) -> int:
        """Active admins other than ``user_id``, seen inside ``session``."""
        return (
            session.query(User)
            .filter(User.role == ROLE_ADMIN, User.is_active.is_(True), User.id != user_id)
            .count()
        )

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
