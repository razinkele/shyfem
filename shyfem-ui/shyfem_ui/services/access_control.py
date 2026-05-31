"""Access control helper for project-level permission checks."""

from shyfem_ui.models.user import ROLE_ADMIN
from shyfem_ui.services.sharing_service import SharingService

ROLE_HIERARCHY = {"owner": 3, "editor": 2, "viewer": 1}


def check_project_access(
    project_id: int,
    user: dict | None,
    min_role: str = "viewer",
    session_factory=None,
) -> str | None:
    """Check if user has at least min_role access to a project.

    Returns the user's actual role if sufficient, None if denied.
    Admins always get access (returns "admin").

    Args:
        project_id: The project to check access for.
        user: User dict from get_current_user() (or None).
        min_role: Minimum required role ("viewer", "editor", or "owner").
        session_factory: Optional SQLAlchemy session factory for testing.
    """
    if user is None:
        return None
    if user.get("role") == ROLE_ADMIN:
        return ROLE_ADMIN

    svc = SharingService(session_factory=session_factory)
    actual_role = svc.get_user_role(project_id, user["id"])
    if actual_role is None:
        return None
    if ROLE_HIERARCHY.get(actual_role, 0) >= ROLE_HIERARCHY.get(min_role, 0):
        return actual_role
    return None


def editor_denied_reason(
    project_id: int,
    user: dict | None,
    *,
    min_role: str = "editor",
    is_server_mode: bool | None = None,
    session_factory=None,
) -> str | None:
    """Return a user-facing error if ``user`` may NOT perform a write, else None.

    This is the single, fail-CLOSED authorization gate for every mutation
    handler reachable over the Shiny WebSocket (job submit, STR/physics save,
    file upload/delete, partitioning/grid runs, ...). Button visibility is only
    a hint: the reactive inputs are live for any project a client can address,
    so each handler must re-check server-validated identity.

    Fail-closed semantics, gated by deployment mode:

    * **Server mode** — a missing/unresolved identity (``user is None``) is
      DENIED. Behind the Shiny Server proxy the WS is admitted with
      ``user=None`` (cookies are not forwarded), so treating None as "allow"
      re-opens the prod viewer-write bypass for any client that simply never
      pushes its ``_wsauth`` token.
    * **Local mode** — single-user desktop has no auth and ``user`` is
      legitimately None; access is allowed (backward-compatible).

    Distinguishes the unresolved-actor case from the resolved-but-unauthorized
    case so each surfaces its own notification (no silent ``return``).

    Args:
        project_id: Project being mutated.
        user: Server-validated user dict (or None).
        min_role: Minimum role required ("viewer", "editor", "owner").
        is_server_mode: Whether the app runs in multi-user server mode. When
            None, resolved from the global config's ``deployment_mode``.
        session_factory: Optional SQLAlchemy session factory for testing.
    """
    if is_server_mode is None:
        from shyfem_ui.config import get_config

        is_server_mode = get_config().deployment_mode == "server"

    if is_server_mode and user is None:
        return "Session identity could not be verified. Please reload the page and sign in again."
    if (
        user is not None
        and check_project_access(
            project_id, user, min_role=min_role, session_factory=session_factory
        )
        is None
    ):
        return f"Permission denied: {min_role} role required for this project."
    return None
