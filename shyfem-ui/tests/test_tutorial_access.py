"""Tests for tutorial role access control."""



def test_tutorial_allowed_pages_constant_exists():
    """app.py defines _TUTORIAL_ALLOWED_PAGES."""
    import shyfem_ui.app as app_mod

    assert hasattr(app_mod, "_TUTORIAL_ALLOWED_PAGES")
    assert "Tutorial" in app_mod._TUTORIAL_ALLOWED_PAGES


def test_filter_sidebar_for_tutorial_keeps_only_tutorial():
    """_filter_sidebar_for_role returns only Tutorial page for tutorial role."""
    from shyfem_ui.app import SIDEBAR_GROUPS, _filter_sidebar_for_role

    filtered = _filter_sidebar_for_role(SIDEBAR_GROUPS, "tutorial")
    all_items = [item for group in filtered for item in group["items"]]
    assert len(all_items) == 1
    assert all_items[0]["value"] == "Tutorial"


def test_filter_sidebar_for_user_keeps_all_non_admin():
    """_filter_sidebar_for_role for 'user' keeps all pages except Admin."""
    from shyfem_ui.app import SIDEBAR_GROUPS, _filter_sidebar_for_role

    filtered = _filter_sidebar_for_role(SIDEBAR_GROUPS, "user")
    all_values = [item["value"] for group in filtered for item in group["items"]]
    assert "Admin" not in all_values
    assert "Tutorial" in all_values
    assert "Run" in all_values


def test_filter_sidebar_for_admin_keeps_all():
    """_filter_sidebar_for_role for 'admin' keeps all pages including Admin."""
    from shyfem_ui.app import SIDEBAR_GROUPS, _filter_sidebar_for_role

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

    assert hasattr(
        app_mod, "_bootstrap_tutorial_project"
    ), "_bootstrap_tutorial_project must exist in app.py to seed the tutorial account"
    assert callable(app_mod._bootstrap_tutorial_project)


def test_tutorial_readonly_guard_in_run_server():
    """run_server() must accept user_role and tutorial_context parameters.

    run_server is a @module.server — Shiny wraps it, hiding the original
    signature. We inspect the closure to find the underlying function and
    verify that user_role and tutorial_context parameters are present.

    NB: the tutorial read-only policy itself now lives centrally in
    ``editor_denied_reason`` (every write handler routes through it), not in a
    per-page run_server check. ``user_role`` is retained as the client-role
    propagation hook (input.current_user_role) and ``tutorial_context`` for
    tutorial navigation auto-fill; this test pins that both remain in the
    signature (app.py still passes them).
    """
    import inspect

    from shyfem_ui.pages.run import run_server

    # @module.server wraps the original; find it in the closure
    original = None
    if run_server.__closure__:
        for cell in run_server.__closure__:
            try:
                v = cell.cell_contents
                if callable(v) and hasattr(v, "__code__") and v.__name__ == "run_server":
                    original = v
                    break
            except ValueError:
                pass

    assert (
        original is not None
    ), "Could not locate the underlying run_server function in the @module.server closure"
    sig = inspect.signature(original)
    assert (
        "user_role" in sig.parameters
    ), "run_server() must have a user_role parameter (client-role propagation hook)"
    assert (
        "tutorial_context" in sig.parameters
    ), "run_server() must have a tutorial_context parameter for tutorial navigation"
