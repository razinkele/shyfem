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
