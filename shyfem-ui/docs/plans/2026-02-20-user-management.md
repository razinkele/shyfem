# User Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add multi-user authentication with session-based login, admin/user roles, project ownership, and sharing to SHYFEM-UI.

**Architecture:** ASGI middleware validates session cookies and serves a login page for unauthenticated requests. Authenticated user context propagates via `contextvars.ContextVar` so Shiny server functions can read the current user. Projects gain `owner_id`, jobs gain `user_id`, and a new `ProjectPermission` table enables sharing. Local mode bypasses auth entirely with a synthetic admin user.

**Tech Stack:** argon2-cffi (password hashing, already installed), SQLAlchemy 2.0 (models), Alembic (migration), Shiny for Python (UI), Bootstrap 5 (login page styling)

---

### Task 1: Config Changes + Database Models + Migration

**Files:**
- Modify: `shyfem_ui/config.py`
- Create: `shyfem_ui/models/user.py`
- Modify: `shyfem_ui/models/__init__.py`
- Modify: `shyfem_ui/models/project.py`
- Modify: `shyfem_ui/db/base.py`
- Create: `migrations/versions/xxxx_add_user_management.py`
- Create: `tests/test_user_models.py`

**Step 1: Write the failing test**

Create `tests/test_user_models.py`:

```python
"""Tests for user management database models."""

import pytest
from datetime import datetime, timedelta, timezone

from shyfem_ui.models.user import User, AuthSession, ProjectPermission


class TestUserModel:
    def test_user_creation(self):
        user = User(
            username="alice",
            display_name="Alice Smith",
            email="alice@example.com",
            password_hash="$argon2id$dummy",
            role="user",
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
        assert p.owner_id is None  # nullable


class TestJobUserColumn:
    def test_job_has_user_id(self):
        from shyfem_ui.models.project import Job
        j = Job(
            job_uuid="abc", name="test", job_type="shyfem",
            command="", working_dir="/tmp",
        )
        assert hasattr(j, "user_id")
        assert j.user_id is None  # nullable
```

**Step 2: Run test to verify it fails**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_user_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shyfem_ui.models.user'`

**Step 3: Add config fields**

In `shyfem_ui/config.py`, add these fields to the `Config` class after the existing `auth_password` field (around line 85):

```python
    # Session-based auth (replaces basic auth in server mode)
    auth_session_ttl_hours: int = Field(
        default=24,
        description="Session cookie lifetime in hours"
    )
    default_admin_username: str = Field(
        default="admin",
        description="Default admin username created on first run"
    )
    default_admin_password: str = Field(
        default="",
        description="Default admin password (required for server mode first run)"
    )
```

**Step 4: Create User models**

Create `shyfem_ui/models/user.py`:

```python
"""Database models for user management, auth sessions, and project permissions."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shyfem_ui.db.base import Base


class User(Base):
    """An authenticated user of the system."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
        return self.role == "admin"

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class AuthSession(Base):
    """A server-side authentication session."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_token", "token", unique=True),
        Index("ix_auth_sessions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now >= exp

    def __repr__(self) -> str:
        return f"<AuthSession(id={self.id}, user_id={self.user_id})>"


class ProjectPermission(Base):
    """Grants a user access to a project they don't own."""

    __tablename__ = "project_permissions"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_user"),
        Index("ix_project_permissions_project_id", "project_id"),
        Index("ix_project_permissions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ProjectPermission(project_id={self.project_id}, user_id={self.user_id}, role='{self.role}')>"
```

**Step 5: Add owner_id to Project and user_id to Job**

In `shyfem_ui/models/project.py`:

Add import at top: `from sqlalchemy import ... Boolean` (add Boolean to existing import).

After `Project.work_dir` field (line 22), add:
```python
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
```

After `Job.session_id` field (line 180-182), add:
```python
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
```

**Step 6: Update model imports**

In `shyfem_ui/models/__init__.py`, replace contents:
```python
"""SQLAlchemy database models for SHYFEM UI."""

from shyfem_ui.models.project import Grid, Job, Project, ProjectFile, Simulation
from shyfem_ui.models.user import AuthSession, ProjectPermission, User

__all__ = [
    "Project", "Grid", "Simulation", "Job", "ProjectFile",
    "User", "AuthSession", "ProjectPermission",
]
```

**Step 7: Update init_db to import user models**

In `shyfem_ui/db/base.py`, line 67, change:
```python
    from shyfem_ui.models import project  # noqa: F401
```
to:
```python
    from shyfem_ui.models import project, user  # noqa: F401
```

**Step 8: Create Alembic migration**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m alembic revision --autogenerate -m "add user management tables"`

Then verify the generated migration includes: `users`, `auth_sessions`, `project_permissions` tables, `projects.owner_id`, `jobs.user_id` columns.

**Step 9: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_user_models.py -v`
Expected: All 10 tests PASS

**Step 10: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 861+ passed (851 existing + 10 new)

**Step 11: Commit**

```bash
git add shyfem_ui/config.py shyfem_ui/models/user.py shyfem_ui/models/__init__.py \
       shyfem_ui/models/project.py shyfem_ui/db/base.py migrations/versions/ \
       tests/test_user_models.py
git commit -m "feat: add User, AuthSession, ProjectPermission models and migration"
```

---

### Task 2: AuthService

**Files:**
- Create: `shyfem_ui/services/auth_service.py`
- Create: `tests/test_auth_service.py`

**Step 1: Write the failing tests**

Create `tests/test_auth_service.py`:

```python
"""Tests for authentication service."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from shyfem_ui.services.auth_service import AuthService


@pytest.fixture
def auth_service(tmp_path):
    """Create AuthService with in-memory SQLite."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shyfem_ui.db.base import Base
    from shyfem_ui.models import user as _  # noqa: F401
    from shyfem_ui.models import project as _p  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return AuthService(session_factory=Session)


class TestPasswordHashing:
    def test_hash_password_returns_string(self, auth_service):
        h = auth_service.hash_password("secret123")
        assert isinstance(h, str)
        assert h.startswith("$argon2")

    def test_verify_password_correct(self, auth_service):
        h = auth_service.hash_password("mypass")
        assert auth_service.verify_password("mypass", h) is True

    def test_verify_password_wrong(self, auth_service):
        h = auth_service.hash_password("mypass")
        assert auth_service.verify_password("wrong", h) is False

    def test_verify_password_invalid_hash(self, auth_service):
        assert auth_service.verify_password("x", "not-a-hash") is False


class TestUserCRUD:
    def test_create_user(self, auth_service):
        user = auth_service.create_user("alice", "pass123", role="user")
        assert user["username"] == "alice"
        assert user["role"] == "user"
        assert user["is_active"] is True
        assert "id" in user

    def test_create_admin(self, auth_service):
        user = auth_service.create_user("admin", "pass", role="admin")
        assert user["role"] == "admin"

    def test_create_duplicate_username_raises(self, auth_service):
        auth_service.create_user("alice", "pass1")
        with pytest.raises(ValueError, match="already exists"):
            auth_service.create_user("alice", "pass2")

    def test_get_user(self, auth_service):
        created = auth_service.create_user("bob", "pass")
        fetched = auth_service.get_user(created["id"])
        assert fetched["username"] == "bob"

    def test_get_user_not_found(self, auth_service):
        assert auth_service.get_user(999) is None

    def test_list_users(self, auth_service):
        auth_service.create_user("a", "p")
        auth_service.create_user("b", "p")
        users = auth_service.list_users()
        assert len(users) == 2

    def test_update_user(self, auth_service):
        user = auth_service.create_user("carol", "pass")
        updated = auth_service.update_user(
            user["id"], display_name="Carol D.", email="carol@test.com"
        )
        assert updated["display_name"] == "Carol D."
        assert updated["email"] == "carol@test.com"

    def test_deactivate_user(self, auth_service):
        user = auth_service.create_user("dave", "pass")
        auth_service.deactivate_user(user["id"])
        fetched = auth_service.get_user(user["id"])
        assert fetched["is_active"] is False

    def test_reset_password(self, auth_service):
        user = auth_service.create_user("eve", "oldpass")
        auth_service.reset_password(user["id"], "newpass")
        result = auth_service.authenticate("eve", "newpass")
        assert result is not None

    def test_change_role(self, auth_service):
        user = auth_service.create_user("frank", "pass", role="user")
        auth_service.update_user(user["id"], role="admin")
        fetched = auth_service.get_user(user["id"])
        assert fetched["role"] == "admin"


class TestAuthenticate:
    def test_authenticate_valid(self, auth_service):
        auth_service.create_user("alice", "secret")
        result = auth_service.authenticate("alice", "secret")
        assert result is not None
        assert result["username"] == "alice"

    def test_authenticate_wrong_password(self, auth_service):
        auth_service.create_user("alice", "secret")
        assert auth_service.authenticate("alice", "wrong") is None

    def test_authenticate_nonexistent_user(self, auth_service):
        assert auth_service.authenticate("nobody", "pass") is None

    def test_authenticate_inactive_user(self, auth_service):
        user = auth_service.create_user("alice", "secret")
        auth_service.deactivate_user(user["id"])
        assert auth_service.authenticate("alice", "secret") is None


class TestSessionManagement:
    def test_create_session(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"], ttl_hours=24)
        assert isinstance(token, str)
        assert len(token) == 64  # hex token

    def test_validate_session_valid(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"], ttl_hours=24)
        result = auth_service.validate_session(token)
        assert result is not None
        assert result["username"] == "alice"

    def test_validate_session_expired(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"], ttl_hours=0)
        # Token created with 0 TTL is already expired
        assert auth_service.validate_session(token) is None

    def test_validate_session_invalid_token(self, auth_service):
        assert auth_service.validate_session("bogus") is None

    def test_delete_session(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        token = auth_service.create_session(user["id"], ttl_hours=24)
        auth_service.delete_session(token)
        assert auth_service.validate_session(token) is None

    def test_cleanup_expired_sessions(self, auth_service):
        user = auth_service.create_user("alice", "pass")
        # Create expired session manually
        auth_service.create_session(user["id"], ttl_hours=0)
        auth_service.create_session(user["id"], ttl_hours=24)
        removed = auth_service.cleanup_expired_sessions()
        assert removed >= 1


class TestEnsureAdmin:
    def test_ensure_admin_creates_when_none(self, auth_service):
        user = auth_service.ensure_admin("admin", "secret")
        assert user["role"] == "admin"
        assert user["username"] == "admin"

    def test_ensure_admin_skips_when_exists(self, auth_service):
        auth_service.create_user("admin", "pass1", role="admin")
        user = auth_service.ensure_admin("admin", "pass2")
        assert user["username"] == "admin"
        # Password should NOT change
        assert auth_service.authenticate("admin", "pass1") is not None
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_auth_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shyfem_ui.services.auth_service'`

**Step 3: Implement AuthService**

Create `shyfem_ui/services/auth_service.py`:

```python
"""Authentication service — password hashing, sessions, user CRUD."""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from sqlalchemy.exc import IntegrityError

from shyfem_ui.models.user import AuthSession, User

logger = logging.getLogger(__name__)

_ph = PasswordHasher()


class AuthService:
    """Manages user accounts and authentication sessions.

    Args:
        session_factory: SQLAlchemy sessionmaker. If None, uses the global factory.
    """

    def __init__(self, session_factory=None):
        if session_factory is None:
            from shyfem_ui.db.base import get_session_factory
            session_factory = get_session_factory()
        self._session_factory = session_factory

    # --- Password hashing ---

    @staticmethod
    def hash_password(plain: str) -> str:
        return _ph.hash(plain)

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        try:
            return _ph.verify(hashed, plain)
        except (VerifyMismatchError, VerificationError):
            return False

    # --- User CRUD ---

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        display_name: str | None = None,
        email: str | None = None,
    ) -> dict:
        db = self._session_factory()
        try:
            existing = db.query(User).filter_by(username=username).first()
            if existing:
                raise ValueError(f"Username '{username}' already exists")
            user = User(
                username=username,
                display_name=display_name or username,
                email=email,
                password_hash=self.hash_password(password),
                role=role,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return self._user_to_dict(user)
        except IntegrityError:
            db.rollback()
            raise ValueError(f"Username '{username}' already exists")
        finally:
            db.close()

    def get_user(self, user_id: int) -> dict | None:
        db = self._session_factory()
        try:
            user = db.query(User).filter_by(id=user_id).first()
            return self._user_to_dict(user) if user else None
        finally:
            db.close()

    def list_users(self) -> list[dict]:
        db = self._session_factory()
        try:
            users = db.query(User).order_by(User.username).all()
            return [self._user_to_dict(u) for u in users]
        finally:
            db.close()

    def update_user(self, user_id: int, **kwargs) -> dict | None:
        db = self._session_factory()
        try:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                return None
            for key in ("display_name", "email", "role"):
                if key in kwargs:
                    setattr(user, key, kwargs[key])
            db.commit()
            db.refresh(user)
            return self._user_to_dict(user)
        finally:
            db.close()

    def deactivate_user(self, user_id: int) -> bool:
        db = self._session_factory()
        try:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            user.is_active = False
            db.commit()
            return True
        finally:
            db.close()

    def reset_password(self, user_id: int, new_password: str) -> bool:
        db = self._session_factory()
        try:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            user.password_hash = self.hash_password(new_password)
            db.commit()
            return True
        finally:
            db.close()

    # --- Authentication ---

    def authenticate(self, username: str, password: str) -> dict | None:
        db = self._session_factory()
        try:
            user = db.query(User).filter_by(username=username).first()
            if not user or not user.is_active:
                return None
            if not self.verify_password(password, user.password_hash):
                return None
            return self._user_to_dict(user)
        finally:
            db.close()

    # --- Session management ---

    def create_session(
        self, user_id: int, ttl_hours: int = 24, ip_address: str | None = None
    ) -> str:
        token = secrets.token_hex(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)
        db = self._session_factory()
        try:
            sess = AuthSession(
                token=token,
                user_id=user_id,
                created_at=now,
                expires_at=expires,
                ip_address=ip_address,
            )
            db.add(sess)
            db.commit()
            return token
        finally:
            db.close()

    def validate_session(self, token: str) -> dict | None:
        db = self._session_factory()
        try:
            sess = db.query(AuthSession).filter_by(token=token).first()
            if not sess:
                return None
            if sess.is_expired:
                db.delete(sess)
                db.commit()
                return None
            user = db.query(User).filter_by(id=sess.user_id).first()
            if not user or not user.is_active:
                return None
            return self._user_to_dict(user)
        finally:
            db.close()

    def delete_session(self, token: str) -> bool:
        db = self._session_factory()
        try:
            sess = db.query(AuthSession).filter_by(token=token).first()
            if not sess:
                return False
            db.delete(sess)
            db.commit()
            return True
        finally:
            db.close()

    def cleanup_expired_sessions(self) -> int:
        now = datetime.now(timezone.utc)
        db = self._session_factory()
        try:
            expired = db.query(AuthSession).filter(AuthSession.expires_at <= now).all()
            count = len(expired)
            for sess in expired:
                db.delete(sess)
            db.commit()
            return count
        finally:
            db.close()

    # --- Bootstrap ---

    def ensure_admin(self, username: str, password: str) -> dict:
        db = self._session_factory()
        try:
            existing = db.query(User).filter_by(role="admin").first()
            if existing:
                return self._user_to_dict(existing)
        finally:
            db.close()
        return self.create_user(username, password, role="admin")

    # --- Helpers ---

    @staticmethod
    def _user_to_dict(user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
        }
```

**Step 4: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_auth_service.py -v`
Expected: All 24 tests PASS

**Step 5: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 885+ passed

**Step 6: Commit**

```bash
git add shyfem_ui/services/auth_service.py tests/test_auth_service.py
git commit -m "feat: add AuthService with password hashing, sessions, and user CRUD"
```

---

### Task 3: SessionAuthMiddleware

**Files:**
- Create: `shyfem_ui/middleware/session_auth.py`
- Create: `tests/test_session_auth_middleware.py`

**Step 1: Write the failing tests**

Create `tests/test_session_auth_middleware.py`:

```python
"""Tests for session authentication middleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shyfem_ui.middleware.session_auth import (
    SessionAuthMiddleware,
    get_current_user,
    _user_var,
    _parse_cookie,
    _LOGIN_HTML,
)


class TestParseCookie:
    def test_parse_single_cookie(self):
        result = _parse_cookie(b"shyfem_session=abc123")
        assert result == {"shyfem_session": "abc123"}

    def test_parse_multiple_cookies(self):
        result = _parse_cookie(b"a=1; shyfem_session=tok; b=2")
        assert result["shyfem_session"] == "tok"

    def test_parse_empty(self):
        assert _parse_cookie(b"") == {}

    def test_parse_no_value(self):
        result = _parse_cookie(b"shyfem_session=")
        assert result["shyfem_session"] == ""


class TestGetCurrentUser:
    def test_returns_none_by_default(self):
        assert get_current_user() is None

    def test_returns_set_user(self):
        token = _user_var.set({"id": 1, "username": "test", "role": "admin"})
        try:
            user = get_current_user()
            assert user["username"] == "test"
        finally:
            _user_var.reset(token)


class TestMiddlewareLocalMode:
    @pytest.mark.asyncio
    async def test_local_mode_injects_synthetic_admin(self):
        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=MagicMock(), local_mode=True)
        scope = {"type": "http", "path": "/", "headers": [], "method": "GET"}
        await mw(scope, AsyncMock(), AsyncMock())
        assert scope["user"]["role"] == "admin"
        assert scope["user"]["username"] == "local"
        inner.assert_awaited_once()


class TestMiddlewareHTTP:
    @pytest.mark.asyncio
    async def test_valid_cookie_passes_through(self):
        user_dict = {"id": 1, "username": "alice", "role": "user"}
        auth_svc = MagicMock()
        auth_svc.validate_session.return_value = user_dict

        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc)
        scope = {
            "type": "http", "path": "/app", "method": "GET",
            "headers": [(b"cookie", b"shyfem_session=validtoken")],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        assert scope["user"] == user_dict
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_cookie_redirects_to_login(self):
        auth_svc = MagicMock()
        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc)

        sent = []
        async def mock_send(msg):
            sent.append(msg)

        scope = {
            "type": "http", "path": "/something", "method": "GET",
            "headers": [],
        }
        await mw(scope, AsyncMock(), mock_send)
        assert sent[0]["status"] == 302
        location = dict(sent[0]["headers"]).get(b"location", b"").decode()
        assert location == "/login"

    @pytest.mark.asyncio
    async def test_login_page_served(self):
        auth_svc = MagicMock()
        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc)

        sent = []
        async def mock_send(msg):
            sent.append(msg)

        scope = {
            "type": "http", "path": "/login", "method": "GET",
            "headers": [],
        }
        await mw(scope, AsyncMock(), mock_send)
        assert sent[0]["status"] == 200
        assert b"text/html" in dict(sent[0]["headers"])[b"content-type"]

    @pytest.mark.asyncio
    async def test_login_post_valid_credentials(self):
        user_dict = {"id": 1, "username": "admin", "role": "admin"}
        auth_svc = MagicMock()
        auth_svc.authenticate.return_value = user_dict
        auth_svc.create_session.return_value = "newtoken123"

        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc, session_ttl_hours=24)

        sent = []
        async def mock_send(msg):
            sent.append(msg)

        body = b"username=admin&password=secret"
        async def mock_receive():
            return {"type": "http.request", "body": body}

        scope = {
            "type": "http", "path": "/login", "method": "POST",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        }
        await mw(scope, mock_receive, mock_send)
        assert sent[0]["status"] == 302
        headers_dict = dict(sent[0]["headers"])
        assert b"set-cookie" in headers_dict
        assert b"shyfem_session=newtoken123" in headers_dict[b"set-cookie"]

    @pytest.mark.asyncio
    async def test_login_post_invalid_credentials(self):
        auth_svc = MagicMock()
        auth_svc.authenticate.return_value = None

        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc)

        sent = []
        async def mock_send(msg):
            sent.append(msg)

        body = b"username=admin&password=wrong"
        async def mock_receive():
            return {"type": "http.request", "body": body}

        scope = {
            "type": "http", "path": "/login", "method": "POST",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        }
        await mw(scope, mock_receive, mock_send)
        # Should re-render login page with error, status 200
        assert sent[0]["status"] == 200
        body_content = sent[1]["body"]
        assert b"Invalid" in body_content

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self):
        auth_svc = MagicMock()
        auth_svc.delete_session.return_value = True

        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc)

        sent = []
        async def mock_send(msg):
            sent.append(msg)

        scope = {
            "type": "http", "path": "/logout", "method": "GET",
            "headers": [(b"cookie", b"shyfem_session=sometoken")],
        }
        await mw(scope, AsyncMock(), mock_send)
        assert sent[0]["status"] == 302
        headers_dict = dict(sent[0]["headers"])
        assert b"max-age=0" in headers_dict.get(b"set-cookie", b"")


class TestMiddlewareWebSocket:
    @pytest.mark.asyncio
    async def test_ws_valid_cookie_passes(self):
        user_dict = {"id": 1, "username": "alice", "role": "user"}
        auth_svc = MagicMock()
        auth_svc.validate_session.return_value = user_dict

        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc)
        scope = {
            "type": "websocket",
            "headers": [(b"cookie", b"shyfem_session=valid")],
        }
        await mw(scope, AsyncMock(), AsyncMock())
        assert scope["user"] == user_dict
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ws_no_cookie_closes(self):
        auth_svc = MagicMock()
        inner = AsyncMock()
        mw = SessionAuthMiddleware(inner, auth_service=auth_svc)

        sent = []
        async def mock_send(msg):
            sent.append(msg)

        scope = {"type": "websocket", "headers": []}
        await mw(scope, AsyncMock(), mock_send)
        assert sent[0]["type"] == "websocket.close"
        assert sent[0]["code"] == 4001
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_auth_middleware.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement SessionAuthMiddleware**

Create `shyfem_ui/middleware/session_auth.py`:

```python
"""Session-based authentication middleware.

Validates session cookies, serves login page, handles login/logout.
Propagates authenticated user via contextvars for Shiny server access.
"""

import contextvars
import logging
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

_user_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "auth_user", default=None
)

# Synthetic user for local mode (no auth required)
_LOCAL_USER: dict = {
    "id": 0,
    "username": "local",
    "display_name": "Local User",
    "email": None,
    "role": "admin",
    "is_active": True,
}


def get_current_user() -> dict | None:
    """Get the authenticated user for the current context."""
    return _user_var.get()


def _parse_cookie(raw: bytes) -> dict[str, str]:
    """Parse a Cookie header value into a dict."""
    result = {}
    for pair in raw.decode("latin-1", errors="replace").split(";"):
        pair = pair.strip()
        if "=" in pair:
            key, _, val = pair.partition("=")
            result[key.strip()] = val.strip()
    return result


def _get_cookie(headers: list, name: str) -> str | None:
    """Extract a named cookie from ASGI headers."""
    for header_name, header_value in headers:
        if header_name == b"cookie":
            cookies = _parse_cookie(header_value)
            if name in cookies and cookies[name]:
                return cookies[name]
    return None


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SHYFEM Workbench — Login</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
      rel="stylesheet" crossorigin="anonymous">
<style>
body {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }}
.login-card {{ max-width: 400px; margin: 10vh auto; }}
</style>
</head>
<body>
<div class="login-card">
<div class="card shadow">
<div class="card-body p-4">
<h3 class="card-title text-center mb-4">SHYFEM Workbench</h3>
{error}
<form method="POST" action="/login">
<div class="mb-3">
<label for="username" class="form-label">Username</label>
<input type="text" class="form-control" id="username" name="username"
       required autofocus>
</div>
<div class="mb-3">
<label for="password" class="form-label">Password</label>
<input type="password" class="form-control" id="password" name="password"
       required>
</div>
<button type="submit" class="btn btn-primary w-100">Sign In</button>
</form>
</div>
</div>
</div>
</body>
</html>"""


class SessionAuthMiddleware:
    """ASGI middleware for session-based authentication.

    - Reads `shyfem_session` cookie from requests
    - Validates via AuthService
    - Serves /login page for unauthenticated HTTP requests
    - Handles POST /login and GET /logout
    - Closes unauthenticated WebSocket connections
    - In local_mode, injects synthetic admin user (no auth)
    """

    COOKIE_NAME = "shyfem_session"

    def __init__(self, app, auth_service, local_mode: bool = False,
                 session_ttl_hours: int = 24):
        self.app = app
        self.auth_service = auth_service
        self.local_mode = local_mode
        self.session_ttl_hours = session_ttl_hours

    async def __call__(self, scope, receive, send):
        # Non-HTTP/WS traffic passes through
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        # Local mode: inject synthetic admin, no auth required
        if self.local_mode:
            scope["user"] = _LOCAL_USER
            token = _user_var.set(_LOCAL_USER)
            try:
                return await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)

        headers = scope.get("headers", [])
        cookie_token = _get_cookie(headers, self.COOKIE_NAME)
        user = self.auth_service.validate_session(cookie_token) if cookie_token else None

        # WebSocket: must be authenticated
        if scope["type"] == "websocket":
            if user is None:
                await send({"type": "websocket.close", "code": 4001})
                return
            scope["user"] = user
            token = _user_var.set(user)
            try:
                return await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)

        # HTTP: handle login/logout routes
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path == "/login":
            if method == "POST":
                return await self._handle_login_post(scope, receive, send)
            return await self._serve_login_page(send)

        if path == "/logout":
            return await self._handle_logout(headers, send)

        # Authenticated: pass through
        if user is not None:
            scope["user"] = user
            token = _user_var.set(user)
            try:
                return await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)

        # Unauthenticated: redirect to login
        await self._redirect(send, "/login")

    async def _serve_login_page(self, send, error: str = ""):
        error_html = (
            f'<div class="alert alert-danger">{error}</div>' if error else ""
        )
        body = _LOGIN_HTML.format(error=error_html).encode()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/html; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def _handle_login_post(self, scope, receive, send):
        body_bytes = b""
        msg = await receive()
        body_bytes = msg.get("body", b"")

        params = parse_qs(body_bytes.decode("utf-8", errors="replace"))
        username = params.get("username", [""])[0]
        password = params.get("password", [""])[0]

        user = self.auth_service.authenticate(username, password)
        if user is None:
            return await self._serve_login_page(send, error="Invalid username or password.")

        token = self.auth_service.create_session(
            user["id"], ttl_hours=self.session_ttl_hours
        )
        max_age = self.session_ttl_hours * 3600
        cookie = (
            f"{self.COOKIE_NAME}={token}; Path=/; HttpOnly; "
            f"SameSite=Lax; Max-Age={max_age}"
        )
        await self._redirect(send, "/", extra_headers=[(b"set-cookie", cookie.encode())])

    async def _handle_logout(self, headers, send):
        cookie_token = _get_cookie(headers, self.COOKIE_NAME)
        if cookie_token:
            self.auth_service.delete_session(cookie_token)
        cookie = f"{self.COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        await self._redirect(send, "/login", extra_headers=[(b"set-cookie", cookie.encode())])

    async def _redirect(self, send, location: str, extra_headers=None):
        headers = [
            (b"location", location.encode()),
            (b"content-length", b"0"),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        await send({
            "type": "http.response.start",
            "status": 302,
            "headers": headers,
        })
        await send({"type": "http.response.body", "body": b""})
```

**Step 4: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_auth_middleware.py -v`
Expected: All 13 tests PASS

**Step 5: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 898+ passed

**Step 6: Commit**

```bash
git add shyfem_ui/middleware/session_auth.py tests/test_session_auth_middleware.py
git commit -m "feat: add SessionAuthMiddleware with login page and cookie management"
```

---

### Task 4: Wire Middleware into app.py + get_current_user Helper

**Files:**
- Modify: `shyfem_ui/app.py`

**Step 1: Modify create_app() to use SessionAuthMiddleware**

In `shyfem_ui/app.py`, make these changes:

1. Add import at top (after existing imports):
```python
from shyfem_ui.middleware.session_auth import SessionAuthMiddleware, get_current_user
from shyfem_ui.services.auth_service import AuthService
```

2. In `create_app()`, after `init_db()` (line 67), add:
```python
    # Initialize auth service and ensure default admin exists
    auth_service = AuthService()
    if config.deployment_mode == "server":
        if config.default_admin_password:
            auth_service.ensure_admin(
                config.default_admin_username, config.default_admin_password
            )
        elif config.auth_enabled and config.auth_password:
            # Backward compat: migrate from basic auth config
            auth_service.ensure_admin(config.auth_username, config.auth_password)
```

3. Replace the BasicAuthMiddleware block (lines 92-99) with:
```python
    # Session-based auth (replaces basic auth)
    is_local = config.deployment_mode == "local"
    app = SessionAuthMiddleware(
        app,
        auth_service=auth_service,
        local_mode=is_local,
        session_ttl_hours=config.auth_session_ttl_hours,
    )
    if not is_local and not config.default_admin_password and not config.auth_password:
        logger.warning(
            "Running in server mode without authentication credentials. "
            "Set SHYFEM_UI_DEFAULT_ADMIN_PASSWORD to enable user login."
        )
```

4. Pass `auth_service` to `_build_server`:
```python
    def server(input, output, session):
        _build_server(input, output, session, config, job_queue, auth_service)
```

5. Update `_build_server` signature:
```python
def _build_server(input, output, session, config: Config, job_queue: JobQueue,
                  auth_service: AuthService | None = None):
```

6. In `_build_server`, replace `_cleanup_session_id = str(id(session))` with:
```python
    _current_user = get_current_user()
    _cleanup_session_id = str(id(session))  # Keep for backward compat
    _is_server = config.deployment_mode == "server"
    _user_id = _current_user["id"] if _current_user else None
```

7. Add a logout button to the navbar. In `_build_ui()`, after the dark mode `nav_control` (line 496-503), add:
```python
            ui.nav_control(
                ui.tags.a(
                    "Logout",
                    href="/logout",
                    class_="btn btn-outline-danger btn-sm ms-2",
                    id="logout-btn",
                ),
            ),
```

**Step 2: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: All existing tests still pass. (No new tests for this task — wiring only.)

**Step 3: Commit**

```bash
git add shyfem_ui/app.py
git commit -m "feat: wire SessionAuthMiddleware into app, replace BasicAuth"
```

---

### Task 5: Admin Panel

**Files:**
- Create: `shyfem_ui/pages/admin.py`
- Modify: `shyfem_ui/pages/__init__.py`
- Modify: `shyfem_ui/app.py`
- Create: `tests/test_admin_page.py`

**Step 1: Write the failing tests**

Create `tests/test_admin_page.py`:

```python
"""Tests for admin page pure functions."""

import pytest
from shyfem_ui.pages.admin import (
    _build_user_table_data,
    _validate_create_user_form,
    _role_badge,
    _active_badge,
)


class TestBuildUserTableData:
    def test_empty_users(self):
        assert _build_user_table_data([]) == []

    def test_single_user(self):
        users = [{"id": 1, "username": "alice", "display_name": "Alice",
                  "email": "a@b.com", "role": "user", "is_active": True}]
        rows = _build_user_table_data(users)
        assert len(rows) == 1
        assert rows[0]["username"] == "alice"

    def test_multiple_users(self):
        users = [
            {"id": 1, "username": "a", "display_name": "A", "email": None,
             "role": "admin", "is_active": True},
            {"id": 2, "username": "b", "display_name": "B", "email": "b@c.com",
             "role": "user", "is_active": False},
        ]
        rows = _build_user_table_data(users)
        assert len(rows) == 2


class TestValidateCreateUserForm:
    def test_valid_form(self):
        errors = _validate_create_user_form("alice", "password123", "user")
        assert errors == []

    def test_missing_username(self):
        errors = _validate_create_user_form("", "pass", "user")
        assert any("username" in e.lower() for e in errors)

    def test_missing_password(self):
        errors = _validate_create_user_form("alice", "", "user")
        assert any("password" in e.lower() for e in errors)

    def test_short_password(self):
        errors = _validate_create_user_form("alice", "ab", "user")
        assert any("password" in e.lower() for e in errors)

    def test_invalid_role(self):
        errors = _validate_create_user_form("alice", "password", "superadmin")
        assert any("role" in e.lower() for e in errors)


class TestBadges:
    def test_role_badge_admin(self):
        html = _role_badge("admin")
        assert "admin" in html.lower()

    def test_role_badge_user(self):
        html = _role_badge("user")
        assert "user" in html.lower()

    def test_active_badge_true(self):
        html = _active_badge(True)
        assert "active" in html.lower()

    def test_active_badge_false(self):
        html = _active_badge(False)
        assert "inactive" in html.lower()
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_page.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create admin.py**

Create `shyfem_ui/pages/admin.py`:

```python
"""Admin panel for user management."""

import logging

from shiny import module, reactive, render, ui

from shyfem_ui.config import Config
from shyfem_ui.services.auth_service import AuthService

logger = logging.getLogger(__name__)

_VALID_ROLES = {"admin", "user"}


def _build_user_table_data(users: list[dict]) -> list[dict]:
    """Convert user dicts to table row dicts."""
    return [
        {
            "id": u["id"],
            "username": u["username"],
            "display_name": u.get("display_name") or u["username"],
            "email": u.get("email") or "-",
            "role": u["role"],
            "is_active": u.get("is_active", True),
        }
        for u in users
    ]


def _validate_create_user_form(username: str, password: str, role: str) -> list[str]:
    """Validate user creation form inputs. Returns list of error messages."""
    errors = []
    if not username or not username.strip():
        errors.append("Username is required")
    if not password:
        errors.append("Password is required")
    elif len(password) < 4:
        errors.append("Password must be at least 4 characters")
    if role not in _VALID_ROLES:
        errors.append(f"Role must be one of: {', '.join(sorted(_VALID_ROLES))}")
    return errors


def _role_badge(role: str) -> str:
    """Return HTML badge for a role."""
    cls = "bg-danger" if role == "admin" else "bg-primary"
    return f'<span class="badge {cls}">{role}</span>'


def _active_badge(is_active: bool) -> str:
    """Return HTML badge for active status."""
    if is_active:
        return '<span class="badge bg-success">Active</span>'
    return '<span class="badge bg-secondary">Inactive</span>'


@module.ui
def admin_ui():
    """Admin panel UI."""
    return ui.div(
        ui.h3("User Management"),
        ui.hr(),
        ui.row(
            ui.column(
                3,
                ui.div(
                    ui.output_ui("user_summary"),
                    ui.hr(),
                    ui.input_action_button(
                        "create_user_btn", "Create User",
                        class_="btn-primary w-100",
                    ),
                    class_="card p-3",
                ),
            ),
            ui.column(
                9,
                ui.div(
                    ui.output_ui("user_table"),
                    class_="card p-3",
                ),
            ),
        ),
    )


@module.server
def admin_server(input, output, session, config: Config, auth_service: AuthService):
    """Admin panel server logic."""
    users_data = reactive.value([])

    @reactive.effect
    def _load_users():
        users_data.set(auth_service.list_users())

    def _refresh():
        users_data.set(auth_service.list_users())

    @render.ui
    def user_summary():
        users = users_data.get()
        total = len(users)
        admins = sum(1 for u in users if u["role"] == "admin")
        active = sum(1 for u in users if u.get("is_active", True))
        return ui.div(
            ui.h6("Summary"),
            ui.p(f"Total users: {total}"),
            ui.p(f"Admins: {admins}"),
            ui.p(f"Active: {active}"),
        )

    @render.ui
    def user_table():
        users = users_data.get()
        if not users:
            return ui.p("No users found.", class_="text-muted")

        rows_data = _build_user_table_data(users)
        rows = []
        for u in rows_data:
            rows.append(
                ui.tags.tr(
                    ui.tags.td(u["username"]),
                    ui.tags.td(u["display_name"]),
                    ui.tags.td(u["email"]),
                    ui.tags.td(ui.HTML(_role_badge(u["role"]))),
                    ui.tags.td(ui.HTML(_active_badge(u["is_active"]))),
                    ui.tags.td(
                        ui.input_action_link(
                            f"reset_pw_{u['id']}", "Reset PW",
                            class_="btn btn-sm btn-outline-warning me-1",
                        ),
                        ui.input_action_link(
                            f"toggle_active_{u['id']}",
                            "Deactivate" if u["is_active"] else "Activate",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        ui.input_action_link(
                            f"toggle_role_{u['id']}",
                            "Demote" if u["role"] == "admin" else "Promote",
                            class_="btn btn-sm btn-outline-info",
                        ),
                    ),
                )
            )

        return ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Username"),
                    ui.tags.th("Display Name"),
                    ui.tags.th("Email"),
                    ui.tags.th("Role"),
                    ui.tags.th("Status"),
                    ui.tags.th("Actions"),
                )
            ),
            ui.tags.tbody(*rows),
            class_="table table-hover",
        )

    # --- Create user modal ---
    @reactive.effect
    @reactive.event(input.create_user_btn)
    def _show_create_modal():
        m = ui.modal(
            ui.input_text("new_username", "Username"),
            ui.input_password("new_password", "Password"),
            ui.input_text("new_display_name", "Display Name (optional)"),
            ui.input_text("new_email", "Email (optional)"),
            ui.input_select("new_role", "Role", choices={"user": "User", "admin": "Admin"}),
            title="Create User",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button("confirm_create", "Create", class_="btn-primary"),
                ui.input_action_button("cancel_create", "Cancel", class_="btn-secondary ms-2"),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.cancel_create)
    def _cancel_create():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.confirm_create)
    def _do_create():
        username = input.new_username().strip()
        password = input.new_password()
        display_name = input.new_display_name().strip() or None
        email = input.new_email().strip() or None
        role = input.new_role()

        errors = _validate_create_user_form(username, password, role)
        if errors:
            ui.notification_show("; ".join(errors), type="error")
            return

        try:
            auth_service.create_user(
                username, password, role=role,
                display_name=display_name, email=email,
            )
            ui.notification_show(f"User '{username}' created", type="message")
            ui.modal_remove()
            _refresh()
        except ValueError as e:
            ui.notification_show(str(e), type="error")

    # --- Action handlers ---
    @reactive.effect
    def _register_action_handlers():
        users = users_data.get()
        for u in users:
            _make_reset_pw_handler(u["id"], u["username"])
            _make_toggle_active_handler(u["id"], u["username"], u.get("is_active", True))
            _make_toggle_role_handler(u["id"], u["username"], u["role"])

    def _make_reset_pw_handler(uid: int, uname: str):
        @reactive.effect
        @reactive.event(input[f"reset_pw_{uid}"])
        def _reset():
            m = ui.modal(
                ui.input_password("reset_password", "New Password"),
                title=f"Reset Password — {uname}",
                easy_close=True,
                footer=ui.div(
                    ui.input_action_button(
                        f"confirm_reset_{uid}", "Reset", class_="btn-warning"
                    ),
                ),
            )
            ui.modal_show(m)

        @reactive.effect
        @reactive.event(input[f"confirm_reset_{uid}"])
        def _do_reset():
            pw = input.reset_password()
            if not pw or len(pw) < 4:
                ui.notification_show("Password must be at least 4 characters", type="error")
                return
            auth_service.reset_password(uid, pw)
            ui.notification_show(f"Password reset for '{uname}'", type="message")
            ui.modal_remove()

    def _make_toggle_active_handler(uid: int, uname: str, is_active: bool):
        @reactive.effect
        @reactive.event(input[f"toggle_active_{uid}"])
        def _toggle():
            if is_active:
                auth_service.deactivate_user(uid)
                ui.notification_show(f"Deactivated '{uname}'", type="warning")
            else:
                auth_service.update_user(uid, is_active=True)
                ui.notification_show(f"Activated '{uname}'", type="message")
            _refresh()

    def _make_toggle_role_handler(uid: int, uname: str, current_role: str):
        @reactive.effect
        @reactive.event(input[f"toggle_role_{uid}"])
        def _toggle():
            new_role = "user" if current_role == "admin" else "admin"
            auth_service.update_user(uid, role=new_role)
            ui.notification_show(
                f"Changed '{uname}' role to {new_role}", type="message"
            )
            _refresh()
```

**Step 4: Register admin page**

In `shyfem_ui/pages/__init__.py`, add `"admin"` to `__all__`.

In `shyfem_ui/app.py`, add to imports: `from shyfem_ui.pages import admin` (add to existing import block, but since pages uses lazy loading, just add `"admin"` to the `__all__` list in `__init__.py`).

In `_build_ui()`, add Admin tab after Files tab (conditionally shown for admin in server function):
```python
            ui.nav_panel("Admin", admin.admin_ui("admin")),
```

In `_build_server()`, add admin server initialization:
```python
    if auth_service:
        admin.admin_server("admin", config, auth_service)
```

**Step 5: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_page.py -v`
Expected: All 12 tests PASS

**Step 6: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 910+ passed

**Step 7: Commit**

```bash
git add shyfem_ui/pages/admin.py shyfem_ui/pages/__init__.py shyfem_ui/app.py \
       tests/test_admin_page.py
git commit -m "feat: add admin panel for user management"
```

---

### Task 6: Project Ownership + Query Filtering

**Files:**
- Modify: `shyfem_ui/pages/home.py`
- Modify: `shyfem_ui/services/project_context.py`
- Modify: `shyfem_ui/app.py`
- Create: `tests/test_project_ownership.py`

**Step 1: Write the failing tests**

Create `tests/test_project_ownership.py`:

```python
"""Tests for project ownership and access control."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


@pytest.fixture
def db_session_factory():
    from shyfem_ui.models import project as _p, user as _u  # noqa
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def setup_data(db_session_factory):
    db = db_session_factory()
    admin = User(username="admin", password_hash="x", role="admin", display_name="Admin")
    alice = User(username="alice", password_hash="x", role="user", display_name="Alice")
    bob = User(username="bob", password_hash="x", role="user", display_name="Bob")
    db.add_all([admin, alice, bob])
    db.flush()

    p1 = Project(name="Alice Project", work_dir="/tmp/p1", owner_id=alice.id)
    p2 = Project(name="Bob Project", work_dir="/tmp/p2", owner_id=bob.id)
    p3 = Project(name="Shared", work_dir="/tmp/p3", owner_id=alice.id)
    p4 = Project(name="Unowned", work_dir="/tmp/p4", owner_id=None)
    db.add_all([p1, p2, p3, p4])
    db.flush()

    perm = ProjectPermission(project_id=p3.id, user_id=bob.id, role="viewer")
    db.add(perm)
    db.commit()

    data = {
        "admin": {"id": admin.id, "role": "admin"},
        "alice": {"id": alice.id, "role": "user"},
        "bob": {"id": bob.id, "role": "user"},
        "p1_id": p1.id, "p2_id": p2.id, "p3_id": p3.id, "p4_id": p4.id,
    }
    db.close()
    return data


def _query_user_projects(db, user_id: int, role: str) -> list:
    """Replicate the filtering logic from home.py."""
    from shyfem_ui.pages.home import get_visible_projects
    return get_visible_projects(db, user_id, role)


class TestProjectVisibility:
    def test_admin_sees_all(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            projects = _query_user_projects(
                db, setup_data["admin"]["id"], "admin"
            )
            assert len(projects) == 4
        finally:
            db.close()

    def test_alice_sees_own_and_shared(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            projects = _query_user_projects(
                db, setup_data["alice"]["id"], "user"
            )
            names = {p.name for p in projects}
            assert "Alice Project" in names
            assert "Shared" in names
            assert "Bob Project" not in names
        finally:
            db.close()

    def test_bob_sees_own_and_shared(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            projects = _query_user_projects(
                db, setup_data["bob"]["id"], "user"
            )
            names = {p.name for p in projects}
            assert "Bob Project" in names
            assert "Shared" in names
            assert "Alice Project" not in names
        finally:
            db.close()

    def test_unowned_visible_to_admin_only(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            admin_projects = _query_user_projects(
                db, setup_data["admin"]["id"], "admin"
            )
            alice_projects = _query_user_projects(
                db, setup_data["alice"]["id"], "user"
            )
            admin_names = {p.name for p in admin_projects}
            alice_names = {p.name for p in alice_projects}
            assert "Unowned" in admin_names
            assert "Unowned" not in alice_names
        finally:
            db.close()


class TestProjectCreationOwner:
    def test_new_project_gets_owner_id(self, db_session_factory, setup_data):
        db = db_session_factory()
        try:
            p = Project(
                name="New", work_dir="/tmp/new",
                owner_id=setup_data["alice"]["id"],
            )
            db.add(p)
            db.commit()
            assert p.owner_id == setup_data["alice"]["id"]
        finally:
            db.close()
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_ownership.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_visible_projects' from 'shyfem_ui.pages.home'`

**Step 3: Add get_visible_projects to home.py**

In `shyfem_ui/pages/home.py`, add this module-level function (after the `_safe_filename` function):

```python
from sqlalchemy import or_
from shyfem_ui.models.user import ProjectPermission


def get_visible_projects(db, user_id: int, role: str, limit: int = 10):
    """Return projects visible to a user based on ownership and permissions.

    Admins see all projects. Regular users see their own projects
    plus projects shared with them.
    """
    if role == "admin":
        return db.query(Project).order_by(Project.updated_at.desc()).limit(limit).all()

    return (
        db.query(Project)
        .filter(
            or_(
                Project.owner_id == user_id,
                Project.id.in_(
                    db.query(ProjectPermission.project_id)
                    .filter(ProjectPermission.user_id == user_id)
                ),
            )
        )
        .order_by(Project.updated_at.desc())
        .limit(limit)
        .all()
    )
```

Then update `_refresh_projects()` inside `home_server` to use it:

```python
    def _refresh_projects():
        from shyfem_ui.middleware.session_auth import get_current_user
        user = get_current_user()
        with db_session() as db:
            if user and user["role"] != "admin":
                project_list = get_visible_projects(db, user["id"], user["role"])
            else:
                project_list = db.query(Project).order_by(Project.updated_at.desc()).limit(10).all()
            projects.set([
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "work_dir": p.work_dir,
                    "updated_at": p.updated_at,
                    "owner_id": p.owner_id,
                }
                for p in project_list
            ])
```

Also update `_create_project()` to set `owner_id`:

```python
        # In _create_project(), where Project is created:
        from shyfem_ui.middleware.session_auth import get_current_user
        user = get_current_user()
        project = Project(
            name=name,
            description=description or None,
            work_dir=str(project_path),
            owner_id=user["id"] if user else None,
        )
```

Apply the same `owner_id` assignment in `_create_tutorial_project()` and `_do_import_project()` and `_do_clone()`.

**Step 4: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_ownership.py -v`
Expected: All 5 tests PASS

**Step 5: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 915+ passed

**Step 6: Commit**

```bash
git add shyfem_ui/pages/home.py shyfem_ui/services/project_context.py \
       tests/test_project_ownership.py
git commit -m "feat: add project ownership filtering and owner_id on creation"
```

---

### Task 7: Job Ownership (user_id replaces session_id)

**Files:**
- Modify: `shyfem_ui/pages/run.py`
- Modify: `shyfem_ui/pages/home.py`
- Modify: `shyfem_ui/app.py`
- Create: `tests/test_job_ownership.py`

**Step 1: Write the failing tests**

Create `tests/test_job_ownership.py`:

```python
"""Tests for job ownership via user_id."""

import pytest
from shyfem_ui.pages.run import _get_job_metadata


class TestGetJobMetadata:
    def test_returns_user_id_when_available(self):
        meta = _get_job_metadata(
            session_id="sess123",
            user_id=42,
        )
        assert meta["user_id"] == 42
        assert meta["session_id"] == "sess123"

    def test_returns_session_only_when_no_user(self):
        meta = _get_job_metadata(
            session_id="sess456",
            user_id=None,
        )
        assert "user_id" not in meta
        assert meta["session_id"] == "sess456"

    def test_returns_both_fields(self):
        meta = _get_job_metadata(session_id="s", user_id=1)
        assert "session_id" in meta
        assert "user_id" in meta
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_job_ownership.py -v`
Expected: FAIL — `cannot import name '_get_job_metadata'`

**Step 3: Add _get_job_metadata to run.py**

In `shyfem_ui/pages/run.py`, add module-level function:

```python
def _get_job_metadata(session_id: str, user_id: int | None = None) -> dict:
    """Build job metadata dict with session_id and optional user_id."""
    meta = {"session_id": session_id}
    if user_id is not None:
        meta["user_id"] = user_id
    return meta
```

Then update the job submission code (around line 406) to use it:
```python
        metadata = _get_job_metadata(_session_id, _user_id)
```

Where `_user_id` comes from `get_current_user()` (set up at the start of `run_server`):
```python
    from shyfem_ui.middleware.session_auth import get_current_user
    _current_user = get_current_user()
    _user_id = _current_user["id"] if _current_user else None
```

**Step 4: Update job listing in home.py to use user_id**

In `home_server` `_refresh_jobs()`, update filtering:
```python
    async def _refresh_jobs():
        if job_queue:
            try:
                show_all = input.show_all_jobs() if _is_server_mode else True
            except Exception:
                show_all = False
            # Use user_id for filtering when available, fall back to session_id
            from shyfem_ui.middleware.session_auth import get_current_user
            user = get_current_user()
            if show_all:
                sid = None
            elif user and _is_server_mode:
                sid = _session_id  # Still filter by session in current impl
            else:
                sid = None
            jobs = await job_queue.list_jobs(limit=5, session_id=sid)
            recent_jobs_list.set(jobs)
```

**Step 5: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_job_ownership.py -v`
Expected: All 3 tests PASS

**Step 6: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 918+ passed

**Step 7: Commit**

```bash
git add shyfem_ui/pages/run.py shyfem_ui/pages/home.py tests/test_job_ownership.py
git commit -m "feat: add user_id to job metadata for ownership tracking"
```

---

### Task 8: Project Sharing UI

**Files:**
- Modify: `shyfem_ui/pages/home.py`
- Create: `shyfem_ui/services/sharing_service.py`
- Create: `tests/test_sharing_service.py`

**Step 1: Write the failing tests**

Create `tests/test_sharing_service.py`:

```python
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
        result = service.share_project(
            setup["project_id"], setup["bob_id"], "viewer"
        )
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
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_sharing_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create SharingService**

Create `shyfem_ui/services/sharing_service.py`:

```python
"""Service for managing project sharing permissions."""

import logging

from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User

logger = logging.getLogger(__name__)


class SharingService:
    """Manages project permission grants between users."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from shyfem_ui.db.base import get_session_factory
            session_factory = get_session_factory()
        self._session_factory = session_factory

    def share_project(self, project_id: int, user_id: int, role: str = "viewer") -> bool:
        """Grant or update a user's access to a project."""
        db = self._session_factory()
        try:
            existing = (
                db.query(ProjectPermission)
                .filter_by(project_id=project_id, user_id=user_id)
                .first()
            )
            if existing:
                existing.role = role
            else:
                perm = ProjectPermission(
                    project_id=project_id, user_id=user_id, role=role
                )
                db.add(perm)
            db.commit()
            return True
        finally:
            db.close()

    def unshare_project(self, project_id: int, user_id: int) -> bool:
        """Revoke a user's access to a project."""
        db = self._session_factory()
        try:
            perm = (
                db.query(ProjectPermission)
                .filter_by(project_id=project_id, user_id=user_id)
                .first()
            )
            if not perm:
                return False
            db.delete(perm)
            db.commit()
            return True
        finally:
            db.close()

    def list_permissions(self, project_id: int) -> list[dict]:
        """List all users with access to a project (excluding owner)."""
        db = self._session_factory()
        try:
            perms = (
                db.query(ProjectPermission, User)
                .join(User, ProjectPermission.user_id == User.id)
                .filter(ProjectPermission.project_id == project_id)
                .all()
            )
            return [
                {
                    "user_id": perm.user_id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "role": perm.role,
                }
                for perm, user in perms
            ]
        finally:
            db.close()

    def get_user_role(self, project_id: int, user_id: int) -> str | None:
        """Get a user's role for a project. Returns 'owner', 'editor', 'viewer', or None."""
        db = self._session_factory()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if not project:
                return None
            if project.owner_id == user_id:
                return "owner"
            perm = (
                db.query(ProjectPermission)
                .filter_by(project_id=project_id, user_id=user_id)
                .first()
            )
            return perm.role if perm else None
        finally:
            db.close()

    def list_shareable_users(self, project_id: int, exclude_user_id: int) -> list[dict]:
        """List users that can be shared with (active, not owner, not already shared)."""
        db = self._session_factory()
        try:
            already_shared = (
                db.query(ProjectPermission.user_id)
                .filter(ProjectPermission.project_id == project_id)
                .subquery()
            )
            users = (
                db.query(User)
                .filter(
                    User.is_active == True,  # noqa: E712
                    User.id != exclude_user_id,
                    ~User.id.in_(already_shared),
                )
                .order_by(User.username)
                .all()
            )
            return [
                {"id": u.id, "username": u.username, "display_name": u.display_name}
                for u in users
            ]
        finally:
            db.close()
```

**Step 4: Add Share button to home.py project cards**

In `shyfem_ui/pages/home.py`, add a "Share" action link next to Export/Clone for projects the user owns. This is wired in the existing project table rows. Add after the Clone button:

```python
                        ui.input_action_link(
                            f"share_{p['id']}",
                            "Share",
                            class_="btn btn-sm btn-outline-primary ms-1",
                        ) if _is_owner(p) else ui.span(),
```

Where `_is_owner` checks if the current user owns the project:
```python
    def _is_owner(project_dict: dict) -> bool:
        from shyfem_ui.middleware.session_auth import get_current_user
        user = get_current_user()
        if not user:
            return False
        if user["role"] == "admin":
            return True
        return project_dict.get("owner_id") == user["id"]
```

Add share modal handler with user select dropdown and role picker.

**Step 5: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_sharing_service.py -v`
Expected: All 7 tests PASS

**Step 6: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 925+ passed

**Step 7: Commit**

```bash
git add shyfem_ui/services/sharing_service.py shyfem_ui/pages/home.py \
       tests/test_sharing_service.py
git commit -m "feat: add project sharing with viewer/editor permissions"
```

---

### Task 9: Update TODO_NEXT.md + Final Test Suite Run

**Step 1: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 920+ passed, 0 failed

**Step 2: Update TODO_NEXT.md**

Add Phase 45 section after Phase 44:

```markdown
## Phase 45: User Management

> Multi-user authentication with session-based login, admin/user roles,
> project ownership with sharing, and job ownership.

- [x] **45.1** User + AuthSession + ProjectPermission models + Alembic migration
  - Config: `auth_session_ttl_hours`, `default_admin_username`, `default_admin_password`
  - `argon2-cffi` password hashing (already installed)

- [x] **45.2** AuthService — password hashing, session management, user CRUD
  - `hash_password`, `verify_password`, `authenticate`, `create_session`, `validate_session`
  - `create_user`, `update_user`, `deactivate_user`, `reset_password`, `ensure_admin`

- [x] **45.3** SessionAuthMiddleware — replaces BasicAuthMiddleware
  - Cookie-based session validation, `/login` page, `/logout` endpoint
  - `user_var` contextvar for Shiny server access, local mode bypass

- [x] **45.4** App wiring — middleware swap, logout button, auth_service init
  - `create_app()` creates AuthService, ensures default admin
  - `_build_server` receives auth_service, reads `get_current_user()`

- [x] **45.5** Admin panel (`pages/admin.py`)
  - User table with create, reset password, toggle active, change role
  - Form validation, role/active badges

- [x] **45.6** Project ownership — `owner_id`, filtered listing, `get_visible_projects()`
  - Regular users see own + shared projects, admins see all

- [x] **45.7** Job ownership — `user_id` in metadata, `_get_job_metadata()` helper

- [x] **45.8** Project sharing — SharingService, share/unshare, permissions UI
  - Viewer (read-only) and editor (modify) roles per project
```

**Step 3: Commit**

```bash
git add shyfem_ui/ tests/ TODO_NEXT.md
git commit -m "docs: mark Phase 45 user management complete"
```
