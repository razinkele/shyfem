# User Management System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add required emails, per-user filesystem directories, simulation email notifications, and a restricted `user:user` tutorial account to the SHYFEM UI shared-server deployment.

**Architecture:** Seven sequential tasks build on the existing SQLAlchemy + Argon2 + session-auth stack. Each task is independently testable. No external dependencies are added — SMTP uses stdlib `smtplib`, templates use Jinja2 (already installed), directories use stdlib `pathlib`.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Shiny for Python, Jinja2 3.1.6, smtplib (stdlib), pytest

---

## Key files to understand first

```
shyfem_ui/config.py                  — Config (BaseSettings, env_prefix="SHYFEM_UI_")
shyfem_ui/models/user.py             — User ORM model (email nullable=True currently)
shyfem_ui/services/auth_service.py   — create_user(), ensure_user(), _user_to_dict()
shyfem_ui/services/job_local.py      — LocalJobQueue, _execute_job(), _persist_job()
shyfem_ui/pages/admin.py             — SIDEBAR_GROUPS not here; user CRUD modal
shyfem_ui/app.py:44-84               — SIDEBAR_GROUPS list (hardcoded, filtered by JS)
shyfem_ui/app.py:99-228              — Bootstrap: ensure_admin(), ensure_user(), _bootstrap_tutorial_project()
tests/test_auth_service.py           — Pattern for in-memory SQLite fixtures
tests/test_job_local.py              — Pattern for LocalJobQueue fixtures
```

---

### Task 1: Config — `user_data_root` and SMTP settings

**Files:**
- Modify: `shyfem_ui/config.py`
- Test: `tests/test_config.py` (add to existing)

**Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_user_data_root_default():
    """user_data_root defaults to /data/shyfem."""
    from shyfem_ui.config import Config
    c = Config()
    assert str(c.user_data_root) == "/data/shyfem"


def test_user_data_root_env(monkeypatch):
    """SHYFEM_UI_USER_DATA_ROOT overrides the default."""
    monkeypatch.setenv("SHYFEM_UI_USER_DATA_ROOT", "/mnt/data")
    from importlib import reload
    import shyfem_ui.config as cfg_mod
    reload(cfg_mod)
    c = cfg_mod.Config()
    assert str(c.user_data_root) == "/mnt/data"


def test_smtp_host_default_empty():
    """smtp_host defaults to empty string (SMTP disabled)."""
    from shyfem_ui.config import Config
    c = Config()
    assert c.smtp_host == ""


def test_smtp_settings_env(monkeypatch):
    """SMTP settings are read from env vars."""
    monkeypatch.setenv("SHYFEM_UI_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SHYFEM_UI_SMTP_PORT", "587")
    monkeypatch.setenv("SHYFEM_UI_SMTP_USER", "noreply@example.com")
    from importlib import reload
    import shyfem_ui.config as cfg_mod
    reload(cfg_mod)
    c = cfg_mod.Config()
    assert c.smtp_host == "smtp.example.com"
    assert c.smtp_port == 587
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py::test_user_data_root_default tests/test_config.py::test_smtp_host_default_empty -v 2>&1 | tail -10`
Expected: `AttributeError: 'Config' object has no attribute 'user_data_root'`

**Step 3: Add fields to `shyfem_ui/config.py`**

Add after the existing `work_dir` field (around line 40):

```python
    # Per-user data directories
    user_data_root: Path = Field(
        default=Path("/data/shyfem"),
        description="Root directory under which per-user home dirs are created: {user_data_root}/{username}/",
    )
```

Add after the `debug` field (end of Config class):

```python
    # Email / SMTP notifications
    smtp_host: str = Field(default="", description="SMTP host for notifications (empty = disabled)")
    smtp_port: int = Field(default=587, description="SMTP port (587=STARTTLS, 465=SSL)")
    smtp_user: str = Field(default="", description="SMTP login username")
    smtp_password: str = Field(default="", description="SMTP login password")
    smtp_from: str = Field(
        default="SHYFEM UI <noreply@localhost>",
        description="From address for notification emails",
    )
```

**Step 4: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py -v --tb=short 2>&1 | tail -15`
Expected: all config tests pass

**Step 5: Run full suite (regression check)**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob='*playwright*' -q --tb=short 2>&1 | tail -5`
Expected: 1302+ passed

**Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/config.py shyfem-ui/tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(ui): add user_data_root and SMTP config fields

New Config fields: user_data_root (default /data/shyfem) for per-user
directories, and smtp_host/port/user/password/from for email notifications.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: User model — `home_dir()` method and `"tutorial"` role

**Files:**
- Modify: `shyfem_ui/models/user.py`
- Create: `tests/test_user_models.py` (file already exists — add to it)

**Step 1: Check what's already in `tests/test_user_models.py`**

Run: `head -30 /home/razinka/shyfem/shyfem-ui/tests/test_user_models.py`

Note the fixture pattern, then add new tests without duplicating.

**Step 2: Write failing tests**

Add to `tests/test_user_models.py`:

```python
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
```

**Step 3: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_user_models.py::test_home_dir_returns_root_slash_username tests/test_user_models.py::test_is_tutorial_property -v 2>&1 | tail -10`
Expected: `AttributeError: 'User' object has no attribute 'home_dir'`

**Step 4: Add `home_dir()` and `is_tutorial` to `shyfem_ui/models/user.py`**

The `User` class currently ends at line ~42. Add after the existing `is_admin` property:

```python
    @property
    def is_tutorial(self) -> bool:
        """Check if the user has the read-only tutorial role."""
        return self.role == "tutorial"

    def home_dir(self, user_data_root: "Path") -> "Path":
        """Return the per-user data directory path.

        Args:
            user_data_root: The configured root (config.user_data_root).

        Returns:
            Path: {user_data_root}/{username}/
        """
        from pathlib import Path
        return Path(user_data_root) / self.username
```

Also add `"tutorial"` as a valid role constant at the top of the file (after imports):

```python
# Valid user roles
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_TUTORIAL = "tutorial"
```

**Step 5: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_user_models.py -v --tb=short 2>&1 | tail -15`
Expected: all pass

**Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/models/user.py shyfem-ui/tests/test_user_models.py
git commit -m "$(cat <<'EOF'
feat(ui): add home_dir() method and tutorial role to User model

- User.home_dir(root) returns Path(root)/username
- User.is_tutorial property (role == "tutorial")
- ROLE_ADMIN/USER/TUTORIAL constants

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: AuthService — email enforcement and directory creation

**Files:**
- Modify: `shyfem_ui/services/auth_service.py`
- Modify: `tests/test_auth_service.py` (add tests)

**Step 1: Write failing tests**

Add to `tests/test_auth_service.py`:

```python
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
        # Make the root unwritable
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_auth_service.py::TestCreateUserEmailAndDirectory -v 2>&1 | tail -15`
Expected: failures (no email validation, no directory creation yet)

**Step 3: Modify `shyfem_ui/services/auth_service.py`**

Update `create_user` (currently lines 50-94). Add `user_data_root` parameter and validation:

```python
def create_user(
    self,
    username: str,
    password: str,
    role: str = "user",
    display_name: str | None = None,
    email: str | None = None,
    user_data_root: "Path | None" = None,
) -> dict:
    """Create a new user account.

    Args:
        username: Unique login name.
        password: Plaintext password (will be hashed).
        role: User role — "user", "admin", or "tutorial".
        display_name: Optional display name.
        email: Email address. Required for non-tutorial accounts.
        user_data_root: If provided, creates {user_data_root}/{username}/ on disk.
                        Skipped for tutorial users. If creation fails, user is not saved.

    Returns:
        Dict with user fields.

    Raises:
        ValueError: If username or email already exists, or email missing for non-tutorial.
        PermissionError: If directory creation fails.
    """
    from pathlib import Path
    from shyfem_ui.models.user import ROLE_TUTORIAL

    # Validate email requirement
    if role != ROLE_TUTORIAL and not email:
        raise ValueError("Email is required for non-tutorial accounts")

    session = self._session_factory()
    try:
        existing = session.query(User).filter_by(username=username).first()
        if existing is not None:
            raise ValueError(f"Username already exists: {username}")

        if email:
            existing_email = session.query(User).filter_by(email=email).first()
            if existing_email is not None:
                raise ValueError(f"Email already in use: {email}")

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
        home = None
        if user_data_root and role != ROLE_TUTORIAL:
            home = user.home_dir(Path(user_data_root))
            home.mkdir(parents=True, exist_ok=True)  # raises PermissionError if not writable

        session.commit()
        return self._user_to_dict(user)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

**Step 4: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_auth_service.py -v --tb=short 2>&1 | tail -20`
Expected: all pass (including new tests)

**Step 5: Run full suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob='*playwright*' -q --tb=short 2>&1 | tail -5`
Expected: 1310+ passed

**Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/services/auth_service.py shyfem-ui/tests/test_auth_service.py
git commit -m "$(cat <<'EOF'
feat(ui): enforce email + create home dir in AuthService.create_user

- Email required for user/admin roles (ValueError if missing)
- Duplicate email check before DB insert
- Creates {user_data_root}/{username}/ on disk for non-tutorial users
- PermissionError on filesystem failure rolls back DB transaction

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: NotificationService — SMTP + email templates

**Files:**
- Create: `shyfem_ui/services/notification_service.py`
- Create: `shyfem_ui/templates/email/job_success.txt`
- Create: `shyfem_ui/templates/email/job_failed.txt`
- Test: `tests/test_notification_service.py` (already exists — check and add/replace)

**Step 1: Check existing `tests/test_notification_service.py`**

Run: `head -20 /home/razinka/shyfem/shyfem-ui/tests/test_notification_service.py`

If it has existing tests, read the full file and extend rather than replace.

**Step 2: Write failing tests**

Create or extend `tests/test_notification_service.py`:

```python
"""Tests for NotificationService — SMTP email notifications."""

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from shyfem_ui.config import Config
from shyfem_ui.services.notification_service import NotificationService


def _make_config(**kwargs) -> Config:
    defaults = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "noreply@example.com",
        "smtp_password": "secret",
        "smtp_from": "SHYFEM UI <noreply@example.com>",
    }
    defaults.update(kwargs)
    return Config(**defaults)


def _make_user(email="alice@example.com"):
    return {"username": "alice", "email": email}


def _make_job(success=True, name="test_sim", duration=42.0, working_dir="/data/shyfem/alice/projects/p1"):
    return {
        "name": name,
        "success": success,
        "duration": duration,
        "working_dir": working_dir,
        "stderr": "error: something went wrong\n" * 15,  # >10 lines
    }


class TestNotificationServiceNoSmtp:

    def test_no_smtp_host_skips_silently(self, caplog):
        """No smtp_host configured → no exception, logs warning."""
        import logging
        svc = NotificationService(Config())
        with caplog.at_level(logging.WARNING):
            svc.notify_job_success(_make_user(), _make_job())
        assert "SMTP" in caplog.text or "smtp" in caplog.text.lower()

    def test_no_smtp_host_notify_failed_skips(self, caplog):
        """No smtp_host → notify_job_failed also skips without error."""
        svc = NotificationService(Config())
        svc.notify_job_failed(_make_user(), _make_job(success=False))  # must not raise


class TestNotificationServiceSmtp:

    def test_notify_success_sends_email(self):
        """notify_job_success sends an email via SMTP."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_success(_make_user(), _make_job())
        mock_smtp.sendmail.assert_called_once()
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "finished" in msg_str.lower() or "success" in msg_str.lower()
        assert "test_sim" in msg_str

    def test_notify_success_subject_contains_job_name(self):
        """Success email subject contains the job name."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_success(_make_user(), _make_job(name="my_run"))
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "my_run" in msg_str

    def test_notify_failed_sends_email(self):
        """notify_job_failed sends an email with 'failed' in subject."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_failed(_make_user(), _make_job(success=False))
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "failed" in msg_str.lower()

    def test_notify_failed_truncates_stderr_to_10_lines(self):
        """Only the last 10 lines of stderr appear in the failure email body."""
        svc = NotificationService(_make_config())
        job = _make_job(success=False)
        job["stderr"] = "\n".join(f"line {i}" for i in range(20))  # 20 lines
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_failed(_make_user(), job)
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        # Last 10 lines are 10-19; first 10 (0-9) should not be in the email
        assert "line 0" not in msg_str
        assert "line 10" in msg_str

    def test_smtp_failure_does_not_raise(self, caplog):
        """SMTP error is caught and logged, not re-raised."""
        import logging
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP", side_effect=smtplib.SMTPConnectError(421, "unavailable")):
            with caplog.at_level(logging.WARNING):
                svc.notify_job_success(_make_user(), _make_job())  # must not raise
        assert caplog.text  # something was logged

    def test_user_with_no_email_skips_silently(self):
        """User with no email address → no exception, no email sent."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            svc.notify_job_success({"username": "user", "email": None}, _make_job())
        mock_smtp_cls.assert_not_called()

    def test_notify_success_body_contains_output_path(self):
        """Success email body includes the job's working directory."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_success(_make_user(), _make_job(working_dir="/data/shyfem/alice/p1"))
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "/data/shyfem/alice/p1" in msg_str
```

**Step 3: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_notification_service.py -v 2>&1 | head -20`
Expected: `ImportError` (module doesn't exist yet)

**Step 4: Create the email templates directory and templates**

```bash
mkdir -p /home/razinka/shyfem/shyfem-ui/shyfem_ui/templates/email
```

Create `/home/razinka/shyfem/shyfem-ui/shyfem_ui/templates/email/job_success.txt`:

```
Subject: [SHYFEM] Simulation finished: {{ job_name }}

Hi {{ username }},

Your SHYFEM simulation has completed successfully.

  Job:       {{ job_name }}
  Duration:  {{ duration }}
  Output:    {{ working_dir }}

Log in to SHYFEM UI to view the results.
```

Create `/home/razinka/shyfem/shyfem-ui/shyfem_ui/templates/email/job_failed.txt`:

```
Subject: [SHYFEM] Simulation failed: {{ job_name }}

Hi {{ username }},

Your SHYFEM simulation has failed.

  Job:  {{ job_name }}

Last output:
{{ stderr_tail }}

Log in to SHYFEM UI for details.
```

**Step 5: Create `shyfem_ui/services/notification_service.py`**

```python
"""Email notification service — sends SMTP notifications on job completion.

If smtp_host is not configured, all methods log a warning and return silently.
SMTP errors are caught and logged — a notification failure must never crash a job.
"""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from pathlib import Path

import jinja2

from shyfem_ui.config import Config

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "email"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
)


def _format_duration(seconds: float | None) -> str:
    if not seconds:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


class NotificationService:
    """Sends email notifications for simulation job completion events."""

    def __init__(self, config: Config):
        self._config = config

    def notify_job_success(self, user: dict, job: dict) -> None:
        """Send a 'simulation finished' email to the user.

        Args:
            user: Dict with at least 'username' and 'email' keys.
            job: Dict with 'name', 'duration', 'working_dir' keys.
        """
        if not self._config.smtp_host:
            logger.warning("SMTP not configured — skipping success notification for %s", user.get("username"))
            return
        if not user.get("email"):
            return

        body = _jinja_env.get_template("job_success.txt").render(
            username=user["username"],
            job_name=job["name"],
            duration=_format_duration(job.get("duration")),
            working_dir=job.get("working_dir", ""),
        )
        self._send(user["email"], body)

    def notify_job_failed(self, user: dict, job: dict) -> None:
        """Send a 'simulation failed' email to the user.

        Args:
            user: Dict with at least 'username' and 'email' keys.
            job: Dict with 'name', 'stderr' keys.
        """
        if not self._config.smtp_host:
            logger.warning("SMTP not configured — skipping failure notification for %s", user.get("username"))
            return
        if not user.get("email"):
            return

        stderr = job.get("stderr") or ""
        stderr_tail = "\n".join(stderr.splitlines()[-10:])

        body = _jinja_env.get_template("job_failed.txt").render(
            username=user["username"],
            job_name=job["name"],
            stderr_tail=stderr_tail,
        )
        self._send(user["email"], body)

    def _send(self, to_addr: str, rendered_template: str) -> None:
        """Parse subject from template first line, send via SMTP.

        Template format: first line is 'Subject: ...' followed by blank line and body.
        """
        lines = rendered_template.strip().splitlines()
        subject_line = lines[0] if lines else "Subject: SHYFEM Notification"
        subject = subject_line.removeprefix("Subject:").strip()
        body = "\n".join(lines[2:]).strip()  # skip subject + blank line

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self._config.smtp_from
        msg["To"] = to_addr

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                if self._config.smtp_user:
                    smtp.login(self._config.smtp_user, self._config.smtp_password)
                smtp.sendmail(self._config.smtp_from, to_addr, msg.as_string())
                logger.info("Notification sent to %s: %s", to_addr, subject)
        except Exception:
            logger.warning("Failed to send notification to %s", to_addr, exc_info=True)
```

**Step 6: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_notification_service.py -v --tb=short 2>&1 | tail -20`
Expected: all pass

**Step 7: Run full suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob='*playwright*' -q --tb=short 2>&1 | tail -5`
Expected: 1320+ passed

**Step 8: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/services/notification_service.py \
        shyfem-ui/shyfem_ui/templates/email/job_success.txt \
        shyfem-ui/shyfem_ui/templates/email/job_failed.txt \
        shyfem-ui/tests/test_notification_service.py
git commit -m "$(cat <<'EOF'
feat(ui): add NotificationService for job completion emails

Sends SMTP emails on job success/failure using Jinja2 plain-text templates.
Skips silently when smtp_host not configured. SMTP errors are caught and
logged so a notification failure never crashes a simulation job.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Job queue — user_id in persistence + notification hook

**Files:**
- Modify: `shyfem_ui/services/job_local.py`
- Modify: `tests/test_job_local.py` (add tests)

**Step 1: Find the exact `_persist_job` lines**

Run: `grep -n "session_id\|user_id\|metadata.get" /home/razinka/shyfem/shyfem-ui/shyfem_ui/services/job_local.py`

Look for the line that sets `session_id=job.metadata.get("session_id")` — add `user_id` extraction on the next line.

**Step 2: Write failing tests**

Add to `tests/test_job_local.py`:

```python
class TestJobUserIdAndNotifications:

    @pytest.mark.asyncio
    async def test_user_id_saved_from_metadata(self, queue, job_spec, tmp_path):
        """Job submitted with user_id in metadata persists user_id to DB."""
        from unittest.mock import MagicMock, patch
        from shyfem_ui.models.project import Job as JobModel, JobStatus

        job_spec.metadata["user_id"] = 42
        with patch.object(queue, "_persist_job") as mock_persist:
            job_id = await queue.submit(job_spec)
            await asyncio.sleep(0.1)  # let executor run
        # Check the persisted job had user_id in metadata
        calls = mock_persist.call_args_list
        assert calls, "Expected _persist_job to be called"
        job_arg = calls[-1][0][0]
        assert job_arg.metadata.get("user_id") == 42

    @pytest.mark.asyncio
    async def test_notification_called_on_success(self, queue, job_spec):
        """NotificationService.notify_job_success is called when job succeeds."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import asyncio

        mock_notif = MagicMock()
        mock_notif.notify_job_success = MagicMock()
        queue.notification_service = mock_notif

        job_id = await queue.submit(job_spec)
        await asyncio.sleep(0.3)
        mock_notif.notify_job_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_called_on_failure(self, queue, job_spec, mock_wrapper):
        """NotificationService.notify_job_failed is called when job fails."""
        from unittest.mock import AsyncMock, MagicMock
        import asyncio
        from shyfem_ui.services.shyfem_wrapper import CommandResult

        mock_wrapper.run_command = AsyncMock(return_value=CommandResult(
            success=False, return_code=1, stdout="", stderr="error",
            command="test", working_dir="/tmp", duration=0.1, output_files=[],
        ))
        mock_notif = MagicMock()
        queue.notification_service = mock_notif

        job_id = await queue.submit(job_spec)
        await asyncio.sleep(0.3)
        mock_notif.notify_job_failed.assert_called_once()
```

**Step 3: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_job_local.py::TestJobUserIdAndNotifications -v 2>&1 | tail -15`
Expected: AttributeError (no notification_service attribute)

**Step 4: Modify `shyfem_ui/services/job_local.py`**

**4a. Find `__init__` of `LocalJobQueue` and add `notification_service=None` parameter:**

```python
def __init__(self, ..., notification_service=None):
    ...
    self.notification_service = notification_service
```

**4b. In `_persist_job`, find the line setting `session_id` and add `user_id` below it:**

```python
session_id=job.metadata.get("session_id"),
user_id=job.metadata.get("user_id"),  # ADD THIS LINE
```

**4c. In `_execute_job`, after line 304 (`self._persist_job(job)`), add notification hook:**

```python
self._persist_job(job)
# Notify user on completion (best-effort, never raises)
self._send_completion_notification(job)
```

**4d. Add `_send_completion_notification` method:**

```python
def _send_completion_notification(self, job: "JobInfo") -> None:
    """Send email notification for job completion. Skips if not configured."""
    if self.notification_service is None:
        return
    user_id = job.metadata.get("user_id")
    if not user_id:
        return

    try:
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.user import User
        from shyfem_ui.services.job_queue import JobStatus

        with db_session() as db:
            user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return

        user_dict = {"username": user.username, "email": user.email}
        job_dict = {
            "name": job.name,
            "duration": (job.completed_at - job.started_at).total_seconds()
                        if job.started_at and job.completed_at else None,
            "working_dir": job.working_dir,
            "stderr": job.error_message or "",
        }
        if job.status == JobStatus.COMPLETED:
            self.notification_service.notify_job_success(user_dict, job_dict)
        else:
            self.notification_service.notify_job_failed(user_dict, job_dict)
    except Exception:
        logger.warning("Failed to send completion notification for job %s", job.id, exc_info=True)
```

**Step 5: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_job_local.py -v --tb=short 2>&1 | tail -20`
Expected: all pass

**Step 6: Run full suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob='*playwright*' -q --tb=short 2>&1 | tail -5`

**Step 7: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/services/job_local.py shyfem-ui/tests/test_job_local.py
git commit -m "$(cat <<'EOF'
feat(ui): persist user_id in job queue and send completion notifications

- Extract user_id from job metadata in _persist_job (same pattern as session_id)
- Add notification_service to LocalJobQueue (optional, injected at startup)
- _send_completion_notification called after _persist_job (best-effort, never raises)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Admin panel — required email, home_dir column, test email, tutorial account

**Files:**
- Modify: `shyfem_ui/pages/admin.py`
- Create: `tests/test_admin_user_management.py`

**Step 1: Write failing tests**

Create `tests/test_admin_user_management.py`:

```python
"""Tests for admin panel user management improvements."""

import inspect

import pytest

from shyfem_ui.pages import admin


def test_validate_create_user_requires_email():
    """_validate_create_user_form rejects missing email for non-tutorial users."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("alice", "pass1234", "user", email=None)
    assert any("email" in e.lower() for e in errors)


def test_validate_create_user_rejects_bad_email():
    """_validate_create_user_form rejects obviously invalid email."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("alice", "pass1234", "user", email="notanemail")
    assert any("email" in e.lower() for e in errors)


def test_validate_create_user_tutorial_no_email_required():
    """Tutorial role does not require email."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("user", "user", "tutorial", email=None)
    assert not any("email" in e.lower() for e in errors)


def test_validate_create_user_valid_email_passes():
    """Valid email passes validation."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("alice", "pass1234", "user", email="alice@x.com")
    assert not errors


def test_send_test_email_function_exists():
    """Admin page exports a send_test_email helper (or it's in the module)."""
    source = inspect.getsource(admin)
    assert "send_test_email" in source or "test_email" in source


def test_tutorial_role_in_valid_roles():
    """'tutorial' is in _VALID_ROLES in admin.py."""
    from shyfem_ui.pages.admin import _VALID_ROLES
    assert "tutorial" in _VALID_ROLES


def test_home_dir_column_in_source():
    """Admin page source references home_dir for the user table."""
    source = inspect.getsource(admin)
    assert "home_dir" in source
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_user_management.py -v 2>&1 | tail -15`
Expected: failures (no email validation, no home_dir, no tutorial role)

**Step 3: Modify `shyfem_ui/pages/admin.py`**

**3a. Add `"tutorial"` to `_VALID_ROLES` (find the line with `_VALID_ROLES`):**

```python
_VALID_ROLES = {"admin", "user", "tutorial"}
```

**3b. Update `_validate_create_user_form` to accept and validate `email`:**

```python
def _validate_create_user_form(
    username: str, password: str, role: str, email: str | None = None
) -> list[str]:
    """Validate user creation form inputs."""
    errors: list[str] = []
    if not username or not username.strip():
        errors.append("Username is required")
    if not password:
        errors.append("Password is required")
    elif len(password) < 4:
        errors.append("Password must be at least 4 characters")
    if role not in _VALID_ROLES:
        errors.append(f"Role must be one of: {', '.join(sorted(_VALID_ROLES))}")
    # Email required for non-tutorial accounts
    if role != "tutorial":
        if not email or not email.strip():
            errors.append("Email is required")
        elif "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Email address is not valid")
    return errors
```

**3c. In `_show_create_modal`, change `new_email` from optional to required with a hint:**

```python
ui.input_text("new_email", "Email (required for user/admin)"),
```

**3d. In `_do_create_user`, pass `email` to validation and `home_dir` display:**

```python
def _do_create_user():
    username = input.new_username() or ""
    password = input.new_password() or ""
    role = input.new_role() or "user"
    display_name = input.new_display_name() or None
    email = input.new_email() or None

    errors = _validate_create_user_form(username, password, role, email=email)
    if errors:
        ui.notification_show("; ".join(errors), type="error", duration=5)
        return

    try:
        from shyfem_ui.config import Config
        config = Config()
        auth_service.create_user(
            username=username.strip(),
            password=password,
            role=role,
            display_name=display_name,
            email=email,
            user_data_root=config.user_data_root,
        )
        home = f"{config.user_data_root}/{username.strip()}" if role != "tutorial" else "N/A"
        ui.modal_remove()
        ui.notification_show(
            f"User '{username.strip()}' created. Home: {home}",
            type="message", duration=5,
        )
        _refresh()
    except (ValueError, PermissionError) as exc:
        ui.notification_show(str(exc), type="error", duration=5)
    except Exception as exc:
        logger.exception("Failed to create user")
        ui.notification_show(f"Error creating user: {exc}", type="error", duration=5)
```

**3e. Add `home_dir` column to the user table display and "Send test email" button.**

Find the user table rendering section (look for where `ui.HTML` or `ui.tags.table` is used to render users). Add:
- A `Home Dir` column showing the path (or "N/A" for tutorial)
- A "Send test email" button per row

For the test email button, add a reactive handler:

```python
@reactive.effect
@reactive.event(input.send_test_email_btn)
def _send_test_email():
    """Send a test notification email to the selected user."""
    from shyfem_ui.config import Config
    from shyfem_ui.services.notification_service import NotificationService
    user_id = input.send_test_email_btn()
    # Resolve user from DB
    user_dict = auth_service.get_user_by_id(user_id)
    if not user_dict or not user_dict.get("email"):
        ui.notification_show("User has no email address.", type="warning")
        return
    config = Config()
    svc = NotificationService(config)
    try:
        svc.notify_job_success(user_dict, {
            "name": "test notification",
            "duration": None,
            "working_dir": str(config.user_data_root / user_dict["username"]),
            "stderr": "",
        })
        ui.notification_show(f"Test email sent to {user_dict['email']}", type="message")
    except Exception as e:
        ui.notification_show(f"SMTP error: {e}", type="error")
```

**Step 4: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_user_management.py -v --tb=short 2>&1 | tail -20`
Expected: all pass

**Step 5: Run full suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob='*playwright*' -q --tb=short 2>&1 | tail -5`

**Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/admin.py shyfem-ui/tests/test_admin_user_management.py
git commit -m "$(cat <<'EOF'
feat(ui): admin panel — required email, home dir column, test email, tutorial role

- _validate_create_user_form now validates email (required for user/admin)
- "tutorial" added to _VALID_ROLES
- User table shows Home Directory column (N/A for tutorial)
- "Send test email" button per user row triggers NotificationService

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Tutorial role — sidebar restriction, write guards, bootstrap

**Files:**
- Modify: `shyfem_ui/app.py` (SIDEBAR_GROUPS filtering + bootstrap)
- Create: `tests/test_tutorial_access.py`

**Step 1: Write failing tests**

Create `tests/test_tutorial_access.py`:

```python
"""Tests for tutorial role access control."""

import inspect

import pytest


def test_tutorial_allowed_pages_constant_exists():
    """app.py defines _TUTORIAL_ALLOWED_PAGES."""
    import shyfem_ui.app as app_mod
    assert hasattr(app_mod, "_TUTORIAL_ALLOWED_PAGES")
    assert "Tutorial" in app_mod._TUTORIAL_ALLOWED_PAGES


def test_filter_sidebar_for_tutorial_keeps_only_tutorial():
    """_filter_sidebar_for_role returns only Tutorial page for tutorial role."""
    from shyfem_ui.app import _filter_sidebar_for_role, SIDEBAR_GROUPS
    filtered = _filter_sidebar_for_role(SIDEBAR_GROUPS, "tutorial")
    all_items = [item for group in filtered for item in group["items"]]
    assert len(all_items) == 1
    assert all_items[0]["value"] == "Tutorial"


def test_filter_sidebar_for_user_keeps_all_non_admin():
    """_filter_sidebar_for_role for 'user' keeps all pages except Admin."""
    from shyfem_ui.app import _filter_sidebar_for_role, SIDEBAR_GROUPS
    filtered = _filter_sidebar_for_role(SIDEBAR_GROUPS, "user")
    all_values = [item["value"] for group in filtered for item in group["items"]]
    assert "Admin" not in all_values
    assert "Tutorial" in all_values
    assert "Run" in all_values


def test_filter_sidebar_for_admin_keeps_all():
    """_filter_sidebar_for_role for 'admin' keeps all pages including Admin."""
    from shyfem_ui.app import _filter_sidebar_for_role, SIDEBAR_GROUPS
    filtered = _filter_sidebar_for_role(SIDEBAR_GROUPS, "admin")
    all_values = [item["value"] for group in filtered for item in group["items"]]
    assert "Admin" in all_values
    assert "Tutorial" in all_values


def test_tutorial_user_bootstrap_uses_tutorial_role():
    """Bootstrap creates default tutorial user with role='tutorial', not 'user'."""
    source = inspect.getsource(__import__("shyfem_ui.app", fromlist=["app"]))
    # The ensure_user call for the tutorial user must pass role='tutorial'
    assert "tutorial" in source


def test_tutorial_readonly_guard_in_source():
    """At least one page server checks for tutorial role and blocks writes."""
    # Check that any page (e.g. run.py or grid_prep.py) has a tutorial role guard
    import shyfem_ui.pages.run as run_mod
    source = inspect.getsource(run_mod)
    assert "tutorial" in source or "is_tutorial" in source
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_tutorial_access.py -v 2>&1 | tail -15`
Expected: `AttributeError: module 'shyfem_ui.app' has no attribute '_TUTORIAL_ALLOWED_PAGES'`

**Step 3: Add sidebar filtering to `shyfem_ui/app.py`**

**3a.** Add after `SIDEBAR_GROUPS` definition (around line 85):

```python
# Pages accessible to tutorial (read-only demo) accounts
_TUTORIAL_ALLOWED_PAGES = {"Tutorial"}


def _filter_sidebar_for_role(groups: list[dict], role: str) -> list[dict]:
    """Return a filtered copy of SIDEBAR_GROUPS for the given user role.

    - "admin"    — all pages
    - "user"     — all pages except Admin
    - "tutorial" — Tutorial page only
    """
    _hidden = {
        "user": {"Admin"},
        "tutorial": {
            item["value"]
            for group in groups
            for item in group["items"]
            if item["value"] not in _TUTORIAL_ALLOWED_PAGES
        },
    }.get(role, set())

    filtered = []
    for group in groups:
        items = [i for i in group["items"] if i["value"] not in _hidden]
        if items:
            filtered.append({**group, "items": items})
    return filtered
```

**3b.** Update the bootstrap section (around line 224) to create the tutorial user with `role="tutorial"`:

Find:
```python
        tutorial_user = auth_service.ensure_user(
            config.default_user_username, config.default_user_password
        )
```

Replace with (add the `role` argument — check `ensure_user` signature first; if it doesn't accept `role`, update it):
```python
        tutorial_user = auth_service.ensure_user(
            config.default_user_username, config.default_user_password, role="tutorial"
        )
```

**3c.** In `auth_service.py`, check if `ensure_user` exists and update to accept `role`:

```python
def ensure_user(self, username: str, password: str, role: str = "user") -> dict:
    """Create the user if it doesn't exist, or return the existing one."""
    try:
        return self.create_user(username, password, role=role)
    except ValueError:
        return self.get_user_by_username(username)
```

**Step 4: Add write guard to `pages/run.py`**

Find the job submission handler in `pages/run.py` (look for `@reactive.event(input.run_btn)` or similar). Add at the top of the handler:

```python
# Tutorial accounts are read-only
user = active_user.get() if active_user else None
if user and user.get("role") == "tutorial":
    ui.notification_show(
        "Tutorial accounts are read-only. Contact your admin for a full account.",
        type="warning",
        duration=6,
    )
    return
```

Also add the same guard in `pages/grid_prep.py` at the top of any mesh-generation or file-save handler.

**Step 5: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_tutorial_access.py -v --tb=short 2>&1 | tail -20`
Expected: all pass

**Step 6: Run full suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob='*playwright*' -q --tb=short 2>&1 | tail -5`
Expected: 1340+ passed

**Step 7: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/app.py \
        shyfem-ui/shyfem_ui/services/auth_service.py \
        shyfem-ui/shyfem_ui/pages/run.py \
        shyfem-ui/shyfem_ui/pages/grid_prep.py \
        shyfem-ui/tests/test_tutorial_access.py
git commit -m "$(cat <<'EOF'
feat(ui): tutorial role sidebar restriction and write guards

- _TUTORIAL_ALLOWED_PAGES + _filter_sidebar_for_role() in app.py
- Tutorial users see only the Tutorial page in sidebar
- Bootstrap creates default user with role='tutorial'
- Run and Grid Prep pages block writes for tutorial accounts

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Final verification

**Step 1: Full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob='*playwright*' -v --tb=short 2>&1 | tail -20`
Expected: 1340+ passed, 0 failures

**Step 2: Smoke check imports**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "
from shyfem_ui.config import Config
from shyfem_ui.services.notification_service import NotificationService
from shyfem_ui.app import _filter_sidebar_for_role, SIDEBAR_GROUPS, _TUTORIAL_ALLOWED_PAGES
from shyfem_ui.models.user import ROLE_TUTORIAL
print('All imports OK')
print('Tutorial filter:', _filter_sidebar_for_role(SIDEBAR_GROUPS, 'tutorial'))
"`
Expected: `All imports OK` followed by a list containing only the Tutorial page

**Step 3: Verify git log**

Run: `cd /home/razinka/shyfem && git log --oneline -8`
Expected: 7 new commits from this feature at top
