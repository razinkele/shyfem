"""Tests for the Dashboard recent-jobs session/IDOR filter.

Exercises the REAL helper the Dashboard's _refresh_jobs uses to decide which
session_id to filter by (shyfem_ui.pages.home.recent_jobs_session_id), not a
re-implemented copy — so these fail if the admin/IDOR gate regresses.
"""

from shyfem_ui.models.user import ROLE_ADMIN
from shyfem_ui.pages.home import recent_jobs_session_id

ADMIN = {"id": 1, "role": ROLE_ADMIN}
VIEWER = {"id": 2, "role": "viewer"}


def test_local_mode_shows_all_jobs():
    """Local (single-user) mode never filters by session."""
    assert recent_jobs_session_id(False, True, None, "sess-x") is None


def test_server_admin_show_all_sees_everything():
    """An admin asking to show all jobs gets the unfiltered list."""
    assert recent_jobs_session_id(True, True, ADMIN, "sess-x") is None


def test_server_non_admin_show_all_downgraded_to_own_session():
    """IDOR guard: a non-admin's 'show all' is downgraded to their own jobs."""
    assert recent_jobs_session_id(True, True, VIEWER, "sess-x") == "sess-x"


def test_server_unauthenticated_show_all_downgraded():
    """No user (unresolved WS identity) cannot list everyone's jobs."""
    assert recent_jobs_session_id(True, True, None, "sess-x") == "sess-x"


def test_server_not_show_all_filters_by_session():
    """When not asking for all, even an admin sees only their own session."""
    assert recent_jobs_session_id(True, False, ADMIN, "sess-x") == "sess-x"
