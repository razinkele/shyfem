"""Sentinel for the file-picker path-traversal E2E tests (review H5).

The 7 ``test_playwright_*_picker.py`` suites assert that file pickers reject
path-traversal input, but each gates that assertion behind a probe for
``window.__test_set_active_project`` and calls ``pytest.skip(...)`` when the
hook is absent. If that debug hook in ``_test_app.py`` is ever renamed or
removed, ALL of those security assertions would skip silently while the suite
stays green — the path-traversal protection would go entirely unexercised.

This sentinel runs in the DEFAULT suite (the picker suites are Playwright and
excluded via addopts), so a rename breaks the build loudly instead of silently
disabling the security tests. Mirrors test_pages_access_control's
``test_step2_handler_table_is_complete`` sentinel.
"""

import pathlib

_TESTS_DIR = pathlib.Path(__file__).parent
_TEST_APP = _TESTS_DIR / "_test_app.py"

# The exact hook name the picker suites probe before asserting traversal rejection.
_HOOK = "window.__test_set_active_project"

# Keep this list in sync with the picker suites; each gates on the hook.
_PICKER_SUITES = [
    "test_playwright_run_picker.py",
    "test_playwright_ibm_picker.py",
    "test_playwright_postprocess_picker.py",
    "test_playwright_simulation_picker.py",
    "test_playwright_physics_picker.py",
    "test_playwright_grid_prep_picker.py",
    "test_playwright_partitioning_picker.py",
]


def test_test_app_exposes_active_project_hook():
    """_test_app.py must define the hook the picker traversal tests depend on."""
    src = _TEST_APP.read_text()
    assert _HOOK in src, (
        f"{_TEST_APP} no longer defines {_HOOK!r}. The picker path-traversal "
        f"security tests skip themselves when this hook is missing — renaming or "
        f"removing it silently disables those security assertions. Restore the "
        f"hook or update both this sentinel and every picker suite."
    )


def test_picker_suites_present():
    """Each picker suite that relies on the hook must still exist (so a deleted
    suite is noticed rather than silently reducing coverage)."""
    missing = [name for name in _PICKER_SUITES if not (_TESTS_DIR / name).exists()]
    assert not missing, f"picker traversal suites missing: {missing}"
