"""WS-auth session identity resolver.

Pure, dependency-light wrapper around AuthService.validate_ws_token so the
resolution logic can be unit-tested without a real database or Shiny session.
"""

from __future__ import annotations


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
