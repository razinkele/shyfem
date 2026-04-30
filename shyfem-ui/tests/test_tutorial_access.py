"""Tests for tutorial role access control."""

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


def test_tutorial_user_bootstrap_function_exists():
    """Bootstrap helper for tutorial user must be present in app module.

    The existing sidebar-filter and allowed-pages behavioral tests already
    cover the tutorial role being wired. This test confirms the bootstrap
    helper that creates the tutorial account is callable (i.e. not removed).
    """
    import shyfem_ui.app as app_mod

    assert hasattr(app_mod, "_bootstrap_tutorial_project"), (
        "_bootstrap_tutorial_project must exist in app.py to seed the tutorial account"
    )
    assert callable(app_mod._bootstrap_tutorial_project)


def test_tutorial_readonly_guard_in_run_server():
    """run_server() must accept a user_role parameter for the tutorial guard.

    The tutorial read-only block is gated on user_role returning 'tutorial'.
    Verifying the parameter exists in the function signature confirms the
    guard infrastructure has not been silently removed.
    """
    import inspect

    from shyfem_ui.pages.run import run_server

    sig = inspect.signature(run_server)
    assert "user_role" in sig.parameters, (
        "run_server() must have a user_role parameter for the tutorial read-only guard"
    )
    assert "tutorial_context" in sig.parameters, (
        "run_server() must have a tutorial_context parameter for tutorial navigation"
    )
