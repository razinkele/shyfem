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

    def test_missing_display_name_falls_back(self):
        users = [{"id": 1, "username": "alice", "display_name": None,
                  "email": None, "role": "user", "is_active": True}]
        rows = _build_user_table_data(users)
        assert rows[0]["display_name"] == "alice"

    def test_missing_email_shows_dash(self):
        users = [{"id": 1, "username": "alice", "display_name": "A",
                  "email": None, "role": "user", "is_active": True}]
        rows = _build_user_table_data(users)
        assert rows[0]["email"] == "-"

    def test_preserves_id(self):
        users = [{"id": 42, "username": "bob", "display_name": "Bob",
                  "email": "bob@x.com", "role": "admin", "is_active": False}]
        rows = _build_user_table_data(users)
        assert rows[0]["id"] == 42
        assert rows[0]["role"] == "admin"
        assert rows[0]["is_active"] is False

    def test_missing_is_active_defaults_true(self):
        users = [{"id": 1, "username": "alice", "role": "user"}]
        rows = _build_user_table_data(users)
        assert rows[0]["is_active"] is True

    def test_empty_display_name_string_falls_back(self):
        users = [{"id": 1, "username": "alice", "display_name": "",
                  "email": None, "role": "user", "is_active": True}]
        rows = _build_user_table_data(users)
        assert rows[0]["display_name"] == "alice"

    def test_empty_email_string_shows_dash(self):
        users = [{"id": 1, "username": "alice", "display_name": "A",
                  "email": "", "role": "user", "is_active": True}]
        rows = _build_user_table_data(users)
        assert rows[0]["email"] == "-"


class TestValidateCreateUserForm:
    def test_valid_form(self):
        errors = _validate_create_user_form("alice", "password123", "user", email="alice@example.com")
        assert errors == []

    def test_missing_username(self):
        errors = _validate_create_user_form("", "pass", "user")
        assert any("username" in e.lower() for e in errors)

    def test_whitespace_only_username(self):
        errors = _validate_create_user_form("   ", "pass", "user")
        assert any("username" in e.lower() for e in errors)

    def test_missing_password(self):
        errors = _validate_create_user_form("alice", "", "user")
        assert any("password" in e.lower() for e in errors)

    def test_short_password(self):
        errors = _validate_create_user_form("alice", "ab", "user")
        assert any("password" in e.lower() for e in errors)

    def test_password_exactly_8_chars(self):
        errors = _validate_create_user_form("alice", "abcd1234", "user", email="alice@example.com")
        assert errors == []

    def test_password_minimum_length_8(self):
        """Password must be at least 8 characters."""
        errors = _validate_create_user_form("testuser", "short", "user", "test@example.com")
        assert any("at least 8" in e for e in errors)

    def test_password_7_chars_rejected(self):
        """7-character password is rejected."""
        errors = _validate_create_user_form("testuser", "1234567", "user", "test@example.com")
        assert any("at least 8" in e for e in errors)

    def test_password_8_chars_accepted(self):
        """8-character password is accepted."""
        errors = _validate_create_user_form("testuser", "12345678", "user", "test@example.com")
        assert not any("password" in e.lower() for e in errors)

    def test_invalid_role(self):
        errors = _validate_create_user_form("alice", "password", "superadmin")
        assert any("role" in e.lower() for e in errors)

    def test_valid_admin_role(self):
        errors = _validate_create_user_form("alice", "password", "admin", email="alice@example.com")
        assert errors == []

    def test_multiple_errors(self):
        errors = _validate_create_user_form("", "", "invalid")
        assert len(errors) >= 2


class TestBadges:
    def test_role_badge_admin(self):
        html = _role_badge("admin")
        assert "admin" in html.lower()
        assert "bg-danger" in html

    def test_role_badge_user(self):
        html = _role_badge("user")
        assert "user" in html.lower()
        assert "bg-primary" in html

    def test_active_badge_true(self):
        html = _active_badge(True)
        assert "active" in html.lower()
        assert "bg-success" in html

    def test_active_badge_false(self):
        html = _active_badge(False)
        assert "inactive" in html.lower()
        assert "bg-secondary" in html

    def test_role_badge_returns_span(self):
        html = _role_badge("user")
        assert html.startswith("<span")
        assert html.endswith("</span>")

    def test_active_badge_returns_span(self):
        html = _active_badge(True)
        assert html.startswith("<span")
        assert html.endswith("</span>")
