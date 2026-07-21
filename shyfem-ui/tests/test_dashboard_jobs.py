"""Tests for the Dashboard recent-jobs scoping (F17 completion).

Batch 3 fixed pages/run.py to scope job listings by the server-validated
user_id (via a shared helper); the Dashboard was still scoping by the
ephemeral str(id(session)) via home.recent_jobs_session_id. A WS reconnect
changes id(session), so a user's own recent jobs would drop off the
Dashboard, and CPython's id() reuse could surface a prior user's job
metadata under a new session.

Exercises the REAL wiring inside home.home_server (via source inspection --
the established pattern for @module.server functions in this codebase, see
tests/_test_helpers.get_server_source and tests/test_run_file_picker.py).
The scoping decision logic itself (own-jobs-only / admin-show-all /
fail-closed / local-mode-unfiltered) is covered behaviorally by
tests/test_run_logic.py::TestListScopedJobs against the SAME shared
function asserted here.
"""

import shyfem_ui.pages.home as home_page
from shyfem_ui.services.run_logic import list_scoped_jobs
from tests._test_helpers import get_server_source


def test_home_server_uses_shared_list_scoped_jobs_helper():
    """_refresh_jobs must scope through the SAME shared helper pages/run.py
    uses (run_logic.list_scoped_jobs) -- not a locally re-implemented copy
    that could silently drift out of sync with the admin/IDOR rules."""
    src = get_server_source(home_page, "home_server")

    assert "list_scoped_jobs(" in src


def test_refresh_jobs_no_longer_scopes_by_session_id():
    """The recent-jobs listing must not filter by session_id (ephemeral
    per-WS-connection) -- that's the F17 bug: a reconnect changes
    id(session), dropping the user's own jobs, and id() reuse can surface a
    prior user's job metadata."""
    src = get_server_source(home_page, "home_server")
    start = src.index("async def _refresh_jobs(")
    end = src.index("\n    @", start)
    body = src[start:end]

    assert (
        "session_id=" not in body
    ), "recent-jobs listing must not pass session_id= to job_queue.list_jobs"
    assert (
        "id(session)" not in body
    ), "recent-jobs listing must not scope by the ephemeral str(id(session))"


def test_recent_jobs_session_id_helper_removed():
    """The old session_id-based decision helper must be gone, not left
    behind as dead/unused code that could be silently reintroduced."""
    assert not hasattr(home_page, "recent_jobs_session_id")


def test_home_server_imports_list_scoped_jobs_from_run_logic():
    assert home_page.list_scoped_jobs is list_scoped_jobs
