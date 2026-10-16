"""Tests for admin page access guard."""



class TestAdminGuard:
    def test_admin_guard_function_allows_admin(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access({"id": 1, "username": "admin", "role": "admin"})
        assert result is True

    def test_admin_guard_function_denies_user(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access({"id": 2, "username": "user", "role": "user"})
        assert result is False

    def test_admin_guard_function_denies_none(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access(None)
        assert result is False


class TestAdminDecision:
    """_admin_decision: in server mode the live, server-validated identity is
    authoritative. The handshake-time ContextVar user is a snapshot taken when
    the WebSocket opened, so falling back to it whenever the live identity says
    "not admin" let a demoted admin keep admin rights until reconnect (L31)."""

    ADMIN = {"id": 1, "username": "a", "role": "admin"}
    USER = {"id": 1, "username": "a", "role": "user"}

    def _decide(self, live, fallback, server_mode):
        from shyfem_ui.pages.admin import _admin_decision

        return _admin_decision(live, lambda: fallback, server_mode=server_mode)

    def test_server_demoted_live_user_ignores_stale_admin_snapshot(self):
        assert self._decide(lambda: self.USER, self.ADMIN, True) is False

    def test_server_revoked_live_identity_ignores_stale_admin_snapshot(self):
        assert self._decide(lambda: None, self.ADMIN, True) is False

    def test_server_live_admin_allowed(self):
        assert self._decide(lambda: self.ADMIN, None, True) is True

    def test_server_live_error_denies(self):
        def boom():
            raise RuntimeError("db error")

        assert self._decide(boom, self.ADMIN, True) is False

    def test_local_mode_falls_back_to_synthetic_admin(self):
        """Local mode never gets a WS token; its synthetic admin comes from
        the ContextVar and must keep working."""
        assert self._decide(lambda: None, self.ADMIN, False) is True

    def test_no_resolver_uses_fallback(self):
        """Callers that pass no current_user (the test app) keep the old path."""
        assert self._decide(None, self.ADMIN, True) is True
        assert self._decide(None, self.USER, True) is False
