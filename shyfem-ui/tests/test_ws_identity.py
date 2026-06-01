"""Tests for the WS-auth session identity resolver."""

import pytest

from shyfem_ui.services.ws_identity import resolve_ws_user


class _FakeAuthService:
    """Stub auth service for unit tests — never touches a real DB."""

    def validate_ws_token(self, token: str) -> dict | None:
        if token == "good":
            return {"id": 1, "username": "alice", "role": "user"}
        return None


@pytest.fixture()
def fake_auth():
    """Return a stub AuthService that accepts only the token 'good'."""
    return _FakeAuthService()


def test_resolve_returns_user_for_valid_token(fake_auth):
    """A valid token resolves to the matching user dict."""
    assert resolve_ws_user("good", fake_auth)["id"] == 1


def test_resolve_none_for_blank_or_invalid(fake_auth):
    """Blank, None, and unknown tokens all resolve to None."""
    assert resolve_ws_user("", fake_auth) is None
    assert resolve_ws_user("bad", fake_auth) is None
    assert resolve_ws_user(None, fake_auth) is None


def test_resolve_propagates_service_exception():
    """resolve_ws_user is a pure wrapper — it must NOT swallow exceptions."""

    class _RaisingAuth:
        def validate_ws_token(self, token):
            raise RuntimeError("db error")

    with pytest.raises(RuntimeError):
        resolve_ws_user("tok", _RaisingAuth())
