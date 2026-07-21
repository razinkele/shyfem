"""Database models for user management, sessions, and project permissions."""

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shyfem_ui.db.base import Base

# Valid user roles
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_TUTORIAL = "tutorial"

# A username becomes a single filesystem path segment (see User.home_dir and
# Config.confine_path), so it must never contain '/', '\x00', whitespace, or
# a leading '.'/'-' that could be misread as a flag or a hidden/relative
# path. This is intentionally strict: letters/digits/underscore first, then
# letters/digits/underscore/dot/hyphen (N43/F44).
USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_MAX_USERNAME_LEN = 64


def validate_username(username: str) -> None:
    """Raise ValueError if ``username`` is unsafe to use as a path segment.

    Called both at account-creation time (``AuthService.create_user``) and
    defensively wherever a username is turned into a filesystem path
    (``Config.confine_path``) -- see docs/reviews N43/F44.
    """
    if (
        not username
        or len(username) > _MAX_USERNAME_LEN
        or username in (".", "..")
        or not USERNAME_RE.match(username)
    ):
        raise ValueError(
            "Username must be 1-64 characters, start with a letter, digit, "
            "or underscore, contain only letters, digits, dots, hyphens, "
            "and underscores, and must not be '.' or '..'."
        )


class User(Base):
    """A registered user of the SHYFEM UI application."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    sessions: Mapped[list["AuthSession"]] = relationship(
        "AuthSession", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        """Check if the user has admin role."""
        return self.role == ROLE_ADMIN

    @property
    def is_tutorial(self) -> bool:
        """Check if the user has the read-only tutorial role."""
        return self.role == ROLE_TUTORIAL

    def home_dir(self, user_data_root: Path) -> Path:
        """Return the per-user data directory path.

        Args:
            user_data_root: The configured root (config.user_data_root).

        Returns:
            Path: {user_data_root}/{username}/

        Raises:
            ValueError: If the resolved path escapes user_data_root.

        Note:
            This only checks *containment* (F44) -- it does NOT reject
            username=="." (which resolves to user_data_root itself and is,
            trivially, "contained" in it). Guarding against that collapse is
            Config.confine_path's job (N43; it calls validate_username()
            first). Callers that skip confine_path must not assume home_dir()
            alone confines a "." or ".." username to a private subdirectory.
        """
        result = (Path(user_data_root) / self.username).resolve()
        root = Path(user_data_root).resolve()
        # Containment, not string-prefix matching: startswith would wrongly
        # accept a sibling directory that merely shares root's string prefix
        # (e.g. root=/data/shyfem, result=/data/shyfem-evil) (F44).
        if not result.is_relative_to(root):
            raise ValueError(f"Username {self.username!r} escapes data root")
        return result

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class AuthSession(Base):
    """An authenticated session tied to a user."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")

    @property
    def is_expired(self) -> bool:
        """Check if the session has expired.

        Handles timezone-naive datetimes by assuming UTC.
        """
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    def __repr__(self) -> str:
        return f"<AuthSession(id={self.id}, user_id={self.user_id}, expired={self.is_expired})>"


class WSAuthToken(Base):
    """Server-issued token that bridges the authenticated HTTP session into
    the Shiny WebSocket scope.

    Distinct from the session cookie value; a pointer to the owning
    ``AuthSession`` whose validity it inherits (expires no later, dies on
    logout, dies on session expiry).
    """

    __tablename__ = "ws_auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    session_token: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    def __repr__(self) -> str:
        return f"<WSAuthToken(id={self.id}, user_id={self.user_id}, expired={self.is_expired})>"


class ProjectPermission(Base):
    """Permission granting a user access to a project with a specific role."""

    __tablename__ = "project_permissions"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectPermission(id={self.id}, project_id={self.project_id}, "
            f"user_id={self.user_id}, role='{self.role}')>"
        )
