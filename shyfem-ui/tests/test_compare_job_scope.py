"""Tests for the Compare page's job-selector scoping (F17 completion).

Batch 3 fixed pages/run.py to scope job listings by the server-validated
user_id (via a shared helper); the comparison job selector was still
scoping non-admin users by the ephemeral str(id(session)). A WS reconnect
changes id(session), so a user's own completed jobs would drop off the
comparison dropdowns, and CPython's id() reuse could surface a prior
user's job metadata under a new session. Also: the previous code fell
through to a session_id filter (rather than failing closed) when the WS
identity was unresolved -- a coincidental near-empty result, not a
deliberate fail-closed guard.

Exercises the REAL wiring inside compare.compare_server (via source
inspection -- the established pattern for @module.server functions in
this codebase, see tests/_test_helpers.get_server_source and
tests/test_run_file_picker.py). The scoping decision logic itself is
covered behaviorally by tests/test_run_logic.py::TestListScopedJobs
against the SAME shared function asserted here.
"""

import shyfem_ui.pages.compare as compare_page
from shyfem_ui.services.run_logic import list_scoped_jobs
from tests._test_helpers import get_server_source


def test_load_jobs_uses_shared_list_scoped_jobs_helper():
    """_load_jobs must scope through the SAME shared helper pages/run.py
    uses (run_logic.list_scoped_jobs) -- not a locally re-implemented copy
    of the admin/IDOR rules."""
    src = get_server_source(compare_page, "compare_server")

    assert "list_scoped_jobs(" in src


def test_load_jobs_no_longer_scopes_by_session_id():
    """The comparison job listing must not filter by session_id (ephemeral
    per-WS-connection) -- that's the F17 bug."""
    src = get_server_source(compare_page, "compare_server")
    start = src.index("async def _load_jobs(")
    end = src.index("\n    @", start)
    body = src[start:end]

    assert (
        "session_id=" not in body
    ), "comparison job listing must not pass session_id= to job_queue.list_jobs"
    assert (
        "id(session)" not in body
    ), "comparison job listing must not scope by the ephemeral str(id(session))"


def test_compare_server_imports_list_scoped_jobs_from_run_logic():
    assert compare_page.list_scoped_jobs is list_scoped_jobs
