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


def test_validate_create_user_rejects_path_traversal():
    """_validate_create_user_form rejects usernames with path traversal characters."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("../evil", "pass1234", "user", email="x@x.com")
    assert any("username" in e.lower() for e in errors)
