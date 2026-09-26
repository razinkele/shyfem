"""Tests for the dedup pattern used by file/ensemble handlers.

Background: ``@reactive.effect`` defined inside another reactive scope (a
``@render.ui``, another ``@reactive.effect``, or a render-time loop) does NOT
auto-destroy when the parent re-runs. Without a guard, every re-render or
parent invocation registers a fresh listener for the same input, causing one
user action to fire N times.

The fix in ``pages/files.py`` and ``pages/ensemble.py`` uses a session-scoped
``set`` to short-circuit duplicate registrations. These tests verify the
pattern itself plus a smoke import of the modules to catch syntax errors.
"""

from __future__ import annotations


def _idempotent_register(seen: set[int], file_id: int, register_fn) -> bool:
    """Mirror of the dedup idiom in pages/files.py and pages/ensemble.py.

    Returns True if registration ran, False if it was skipped.
    """
    if file_id in seen:
        return False
    seen.add(file_id)
    register_fn()
    return True


def test_dedup_runs_first_time_only():
    """First registration runs; subsequent ones are skipped."""
    seen: set[int] = set()
    calls: list[int] = []
    for _ in range(5):
        _idempotent_register(seen, 42, lambda: calls.append(1))
    assert len(calls) == 1
    assert seen == {42}


def test_dedup_independent_per_id():
    """Different ids each register exactly once."""
    seen: set[int] = set()
    calls: list[int] = []
    for fid in [1, 2, 3, 1, 2, 3, 1]:
        _idempotent_register(seen, fid, lambda: calls.append(1))
    assert len(calls) == 3
    assert seen == {1, 2, 3}


def test_dedup_returns_status():
    """The function reports whether registration ran or was skipped."""
    seen: set[int] = set()
    assert _idempotent_register(seen, 7, lambda: None) is True
    assert _idempotent_register(seen, 7, lambda: None) is False


def _idempotent_register_str(seen: set[str], key: str, register_fn) -> bool:
    """String-keyed mirror of the dedup idiom in pages/home.py.

    home.py's per-project factories share one set keyed by prefixed strings
    (open_proj_, project_, export_, clone_, share_, confirm_share_, unshare_).
    """
    if key in seen:
        return False
    seen.add(key)
    register_fn()
    return True


def test_dedup_shared_set_distinct_prefixes_no_collision():
    """All home.py factories share one set; distinct prefixes never collide."""
    seen: set[str] = set()
    calls: list[str] = []
    # Same project id (5) across every handler type, registered twice each.
    keys = [
        "open_proj_5",
        "project_5",
        "export_5",
        "clone_5",
        "share_5",
        "confirm_share_5",
        "unshare_5_3",
    ]
    for key in keys * 2:
        _idempotent_register_str(seen, key, lambda k=key: calls.append(k))
    # Each distinct key registers exactly once despite the shared id and set.
    assert sorted(calls) == sorted(keys)
    assert seen == set(keys)


def test_files_module_imports_cleanly():
    """Smoke test — fix should not have introduced syntax errors."""
    from shyfem_ui.pages import files  # noqa: F401


def test_ensemble_module_imports_cleanly():
    """Smoke test — fix should not have introduced syntax errors."""
    from shyfem_ui.pages import ensemble  # noqa: F401


def test_home_module_imports_cleanly():
    """Smoke test — Pattern-4 fix should not have introduced syntax errors."""
    from shyfem_ui.pages import home  # noqa: F401


def test_boundary_editor_module_imports_cleanly():
    """Smoke test — dedup guard should not have introduced syntax errors."""
    from shyfem_ui.components import boundary_editor  # noqa: F401
