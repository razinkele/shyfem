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


# ---------------------------------------------------------------------------
# LiveWSIdentity — re-validates on every read (L31: a role change or
# deactivation must reach a session that is already open)
# ---------------------------------------------------------------------------


class _MutableAuthService:
    """Stub whose answer for the bound token can change between calls."""

    def __init__(self, user: dict | None):
        self.user = user
        self.calls = 0

    def validate_ws_token(self, token: str) -> dict | None:
        self.calls += 1
        return dict(self.user) if (token == "tok" and self.user) else None


def test_live_identity_sees_role_change_after_binding():
    """Demoting the user in the DB is visible on the very next read."""
    from shyfem_ui.services.ws_identity import LiveWSIdentity

    svc = _MutableAuthService({"id": 7, "username": "eve", "role": "admin"})
    ident = LiveWSIdentity(svc)
    ident.bind("tok")
    assert ident.current()["role"] == "admin"

    svc.user = {"id": 7, "username": "eve", "role": "user"}
    assert ident.current()["role"] == "user"


def test_live_identity_none_after_deactivation_or_logout():
    """A token whose session no longer validates reads as None."""
    from shyfem_ui.services.ws_identity import LiveWSIdentity

    svc = _MutableAuthService({"id": 7, "username": "eve", "role": "admin"})
    ident = LiveWSIdentity(svc)
    ident.bind("tok")
    assert ident.current() is not None

    svc.user = None
    assert ident.current() is None


def test_live_identity_unbound_is_none_without_db_call():
    """Before a token arrives there is no identity and no DB round-trip."""
    from shyfem_ui.services.ws_identity import LiveWSIdentity

    svc = _MutableAuthService({"id": 7, "username": "eve", "role": "admin"})
    ident = LiveWSIdentity(svc)
    assert ident.current() is None
    ident.bind("")
    assert ident.current() is None
    assert svc.calls == 0


def test_live_identity_fails_closed_on_service_error():
    """A DB error reads as None (deny), never as an exception a caller
    might catch and route to a stale fallback."""
    from shyfem_ui.services.ws_identity import LiveWSIdentity

    class _RaisingAuth:
        def validate_ws_token(self, token):
            raise RuntimeError("db error")

    ident = LiveWSIdentity(_RaisingAuth())
    ident.bind("tok")
    assert ident.current() is None


class TestIdentityFingerprint:
    """The live-identity poll bumps identity_rev only when this changes, so
    it must be value-compared and ignore fields that do not affect what an
    identity-scoped render shows."""

    def test_no_user_is_none(self):
        from shyfem_ui.services.ws_identity import identity_fingerprint

        assert identity_fingerprint(None) is None
        assert identity_fingerprint({}) is None

    def test_equal_identities_compare_equal(self):
        from shyfem_ui.services.ws_identity import identity_fingerprint

        a = {"id": 3, "role": "user", "username": "u"}
        b = {"id": 3, "role": "user", "username": "u", "last_seen": 123}
        assert identity_fingerprint(a) == identity_fingerprint(b)

    def test_demotion_and_deactivation_change_it(self):
        from shyfem_ui.services.ws_identity import identity_fingerprint

        admin = identity_fingerprint({"id": 3, "role": "admin"})
        assert identity_fingerprint({"id": 3, "role": "user"}) != admin
        assert identity_fingerprint(None) != admin
