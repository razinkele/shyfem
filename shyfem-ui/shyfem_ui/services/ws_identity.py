"""WS-auth session identity resolver.

Pure, dependency-light wrapper around AuthService.validate_ws_token so the
resolution logic can be unit-tested without a real database or Shiny session.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_ws_user(ws_token: str | None, auth_service) -> dict | None:
    """Resolve a WS-auth token to a user dict, server-side.

    Pure wrapper for testability.

    Args:
        ws_token: The raw token string from the ``_wsauth`` Shiny input.
            Falsy values (empty string, None) are rejected immediately.
        auth_service: Any object with a ``validate_ws_token(token: str)``
            method that returns a user dict or None.

    Returns:
        The user dict if the token is valid and unexpired, otherwise None.
    """
    if not ws_token:
        return None
    return auth_service.validate_ws_token(ws_token)


class LiveWSIdentity:
    """The identity bound to one Shiny session's WS-auth token, re-validated on
    every read.

    Resolving the token once at connect time froze the user's role and active
    flag for the life of the WebSocket: an admin demoted, deactivated or logged
    out elsewhere kept their old rights until they reloaded (L31). Each
    :meth:`current` call goes back to the DB (two indexed SELECTs), so the
    answer at a decision site is the answer the DB gives now.

    :meth:`current` never raises: a DB error reads as None, which every guard
    treats as deny. An exception would let a caller's ``except`` fall through
    to a stale fallback identity.
    """

    def __init__(self, auth_service):
        self._auth_service = auth_service
        self._token: str | None = None

    def bind(self, ws_token: str | None) -> None:
        """Attach the token the browser pushed as ``input._wsauth``."""
        self._token = ws_token or None

    def current(self) -> dict | None:
        """Return the user as the DB sees them now, or None (deny)."""
        if self._token is None:
            return None
        try:
            return resolve_ws_user(self._token, self._auth_service)
        except Exception:
            logger.warning("WS identity re-validation failed; denying", exc_info=True)
            return None
