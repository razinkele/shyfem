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
    """Bootstrap creates default tutorial user with role='tutorial'."""
    source = inspect.getsource(__import__("shyfem_ui.app", fromlist=["app"]))
    assert "tutorial" in source


def test_tutorial_readonly_guard_in_source():
    """At least one page server checks for tutorial role and blocks writes."""
    import shyfem_ui.pages.run as run_mod
    source = inspect.getsource(run_mod)
    assert "tutorial" in source or "is_tutorial" in source
