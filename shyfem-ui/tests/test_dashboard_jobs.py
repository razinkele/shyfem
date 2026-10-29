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


def _home_server_functions():
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(get_server_source(home_page, "home_server")))
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _is_effect(fn) -> bool:
    import ast

    return any(ast.unparse(d) == "reactive.effect" for d in fn.decorator_list)


def test_dashboard_jobs_refresh_periodically():
    """H-06: Active Jobs and Recent Activity were read once per identity
    change, so a job submitted, started or finished while the Dashboard was
    open never showed. An effect must re-list them on a timer, off the loop
    (awaiting the async _refresh_jobs, never a synchronous DB read)."""
    import ast

    polls = []
    for fn in _home_server_functions():
        if not (_is_effect(fn) and isinstance(fn, ast.AsyncFunctionDef)):
            continue
        calls = {ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
        awaited = {
            ast.unparse(a.value.func)
            for a in ast.walk(fn)
            if isinstance(a, ast.Await) and isinstance(a.value, ast.Call)
        }
        if "reactive.invalidate_later" in calls and "_refresh_jobs" in awaited:
            polls.append(fn.name)
    assert polls, "no timed effect re-lists the Dashboard jobs"


def test_dashboard_job_poll_compares_before_set():
    """A poll that sets a fresh-but-equal list re-renders both job cards
    every tick; _refresh_jobs must skip an unchanged listing."""
    src = get_server_source(home_page, "home_server")
    start = src.index("async def _refresh_jobs(")
    end = src.index("\n    @", start)
    body = src[start:end]
    assert "recent_jobs_list.get()" in body and "reactive.isolate()" in body
