"""Tests for admin page access guard."""

import pytest


class TestAdminGuard:
    def test_admin_guard_function_allows_admin(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access({"id": 1, "username": "admin", "role": "admin"})
        assert result is True

    def test_admin_guard_function_denies_user(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access({"id": 2, "username": "user", "role": "user"})
        assert result is False

    def test_admin_guard_function_denies_none(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access(None)
        assert result is False
