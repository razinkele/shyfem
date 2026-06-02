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


def resolve_effective_role(server_user: dict | None, fallback_role: str | None) -> str | None:
    """Resolve the role to enforce policy against, preferring the
    server-validated WS identity.

    ``server_user`` is the dict from the ``_wsauth``-resolved ``current_user()``
    (authoritative, server-side). ``fallback_role`` is the client-supplied
    ``input.current_user_role()`` signal, which is spoofable from the browser
    console. The fallback is consulted ONLY when there is no server-validated
    identity (the HTTP / local-mode path); otherwise a tutorial account could
    spoof ``current_user_role`` to escape the read-only policy gate.
    """
    if server_user is not None:
        return server_user.get("role")
    return fallback_role


def identity_denied_reason(
    user: dict | None,
    *,
    is_server_mode: bool | None = None,
) -> str | None:
    """Return a user-facing error if an action requiring a signed-in user may
    NOT proceed, else None.

    For create-class actions (project create / clone / import) there is no
    pre-existing project to authorize against, so ``editor_denied_reason`` does
    not apply — but in server mode an unresolved identity must still be DENIED,
    otherwise the new project is stamped ``owner_id=None`` (an orphan nobody
    owns). Local mode has no auth and is allowed.

    Args:
        user: Server-validated user dict (or None).
        is_server_mode: When None, resolved from the global config.
    """
    if is_server_mode is None:
        from shyfem_ui.config import get_config

        is_server_mode = get_config().deployment_mode == "server"

    if is_server_mode and user is None:
        return "Session identity could not be verified. Please reload the page and sign in again."
    return None


def job_cancel_denied_reason(
    *,
    job_user_id: int | None,
    job_project_id: int | None,
    user: dict | None,
    is_server_mode: bool | None = None,
    session_factory=None,
) -> str | None:
    """Return a user-facing error if ``user`` may NOT cancel the job, else None.

    A job may be cancelled by its **owner** (``user_id`` match), an **admin**, or
    a user with **editor** access to the job's project. This is broader than
    ``editor_denied_reason`` (which gates per-project writes): a user may own a
    job — and thus cancel it — without holding a project role, and a project
    editor may cancel a collaborator's job on a shared project.

    Fail-closed, gated by deployment mode (same as ``editor_denied_reason``):

    * **Server mode** — an unresolved identity (``user is None``) is DENIED.
    * **Local mode** — single-user desktop has no auth; ``user`` is legitimately
      None and cancellation is allowed.

    Args:
        job_user_id: The job's owner user id (from job metadata), or None.
        job_project_id: The job's project id (from job metadata), or None.
        user: Server-validated user dict (or None).
        is_server_mode: When None, resolved from the global config.
        session_factory: Optional SQLAlchemy session factory for testing.
    """
    if is_server_mode is None:
        from shyfem_ui.config import get_config

        is_server_mode = get_config().deployment_mode == "server"

    if not is_server_mode:
        return None
    if user is None:
        return "Session identity could not be verified. Please reload the page and sign in again."
    if user.get("role") == ROLE_ADMIN:
        return None
    if job_user_id is not None and user.get("id") == job_user_id:
        return None
    if (
        job_project_id is not None
        and check_project_access(
            job_project_id, user, min_role="editor", session_factory=session_factory
        )
        is not None
    ):
        return None
    return (
        "Permission denied: only the job owner, a project editor, or an admin may cancel this job."
    )


def editor_denied_reason(
    project_id: int | None,
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

    A ``project_id`` of None means no project is active. In server mode that is
    DENIED unconditionally (there is nothing to authorize against, and treating
    it as "allow" re-opens the bypass where a guard nested inside
    ``if active_project is not None`` was skipped when no project was active);
    in local mode it is allowed.

    Distinguishes the unresolved-actor, no-active-project, and
    resolved-but-unauthorized cases so each surfaces its own notification (no
    silent ``return``).

    Args:
        project_id: Project being mutated, or None if no project is active.
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
    if is_server_mode and project_id is None:
        return "No active project. Open a project before performing this action."
    if (
        user is not None
        and project_id is not None
        and check_project_access(
            project_id, user, min_role=min_role, session_factory=session_factory
        )
        is None
    ):
        return f"Permission denied: {min_role} role required for this project."
    return None
