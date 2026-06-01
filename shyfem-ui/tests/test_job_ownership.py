"""Tests for job ownership via user_id."""

from shyfem_ui.pages.run import _get_job_metadata


class TestGetJobMetadata:
    def test_returns_user_id_when_available(self):
        meta = _get_job_metadata(session_id="sess123", user_id=42)
        assert meta["user_id"] == 42
        assert meta["session_id"] == "sess123"

    def test_returns_session_only_when_no_user(self):
        meta = _get_job_metadata(session_id="sess456", user_id=None)
        assert "user_id" not in meta
        assert meta["session_id"] == "sess456"

    def test_returns_both_fields(self):
        meta = _get_job_metadata(session_id="s", user_id=1)
        assert "session_id" in meta
        assert "user_id" in meta

    def test_includes_project_id_when_available(self):
        meta = _get_job_metadata(session_id="s", user_id=1, project_id=7)
        assert meta["project_id"] == 7

    def test_omits_project_id_when_none(self):
        meta = _get_job_metadata(session_id="s", user_id=1, project_id=None)
        assert "project_id" not in meta
