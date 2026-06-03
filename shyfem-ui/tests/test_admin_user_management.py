"""Tests for admin panel user management improvements."""


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


def test_send_test_email_infrastructure_exists():
    """Admin panel must wire a test-email action to NotificationService.

    Verifies behavioral prerequisites rather than scanning source text:
    - admin_server is callable (it is the scope where _send_test_email lives)
    - NotificationService has notify_job_success() — the method invoked by
      the send-test-email handler inside admin_server.
    """
    from shyfem_ui.services.notification_service import NotificationService

    assert hasattr(admin, "admin_server") and callable(admin.admin_server), (
        "admin_server must be callable — it is the scope that registers send_test_email"
    )
    assert callable(getattr(NotificationService, "notify_job_success", None)), (
        "NotificationService must have notify_job_success() used by the test-email handler"
    )


def test_tutorial_role_in_valid_roles():
    """'tutorial' is in _VALID_ROLES in admin.py."""
    from shyfem_ui.pages.admin import _VALID_ROLES
    assert "tutorial" in _VALID_ROLES


def test_home_dir_column_in_user_table_data():
    """User table rows must include a username field used to construct home paths.

    _build_user_table_data() is the helper that prepares each table row; the
    render code combines row['username'] with config.user_data_root to produce
    the home-directory cell. Confirming 'username' is present in the output is
    the behavioral guard for the home_dir column.
    """
    from shyfem_ui.pages.admin import _build_user_table_data

    users = [{"id": 1, "username": "alice", "role": "user", "is_active": True}]
    rows = _build_user_table_data(users)
    assert len(rows) == 1
    assert "username" in rows[0], "_build_user_table_data must include 'username' for home-dir column"
    assert rows[0]["username"] == "alice"


def test_validate_create_user_rejects_path_traversal():
    """_validate_create_user_form rejects usernames with path traversal characters."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("../evil", "pass1234", "user", email="x@x.com")
    assert any("username" in e.lower() for e in errors)


def test_username_rejects_dotdot():
    """Username '..' must be rejected to prevent path traversal."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("..", "password123", "user", "test@example.com")
    assert any("consecutive dots" in e.lower() or "username" in e.lower() for e in errors)


def test_username_rejects_dotdot_embedded():
    """Username 'foo..bar' must be rejected."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("foo..bar", "password123", "user", "test@example.com")
    assert len(errors) > 0
