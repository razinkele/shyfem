"""Access control helper for project-level permission checks."""

from shyfem_ui.models.user import ROLE_ADMIN, ROLE_TUTORIAL
from shyfem_ui.services.sharing_service import SharingService

ROLE_HIERARCHY = {"owner": 3, "editor": 2, "viewer": 1}

# Shown when a read-only tutorial account attempts any mutation. Tutorial
# read-only is enforced centrally in every mutation gate (editor /
# identity / job-cancel), from the server-validated user dict.
_TUTORIAL_READONLY_MSG = "Tutorial accounts are read-only. Contact your admin for a full account."


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


def accessible_shared_work_dirs(user: dict | None, *, session_factory=None) -> list:
    """Return the resolved ``work_dir`` Paths of every project the acting user
    holds a :class:`ProjectPermission` grant on (N44 shared-project READ
    confinement).

    The permission set is derived SERVER-SIDE from the database, keyed on the
    user's id from the server-validated identity dict -- never a client-pushed
    signal. Presence of a ``ProjectPermission`` row IS the grant (the model has
    no separate ``accepted`` flag).

    OWNED projects are intentionally excluded: an owner's reach comes from their
    own home sandbox (plus the F15 relocation for legacy pre-#29 dirs), not from
    this shared-read widening. Consequently the bootstrapped "Mar Menor
    Tutorial" -- owned by admin, shared (editor) to the tutorial user -- is
    reachable by the tutorial user via their permission row here, which is
    exactly the case N44 fixes.

    Returns ``[]`` for an unresolved / id-less user. Read-only: never mutates.

    Args:
        user: Server-validated user dict (or None).
        session_factory: Optional SQLAlchemy session factory for testing;
            defaults to the global factory.
    """
    if not isinstance(user, dict):
        return []
    user_id = user.get("id")
    if user_id is None:
        return []

    from pathlib import Path

    from shyfem_ui.models.project import Project
    from shyfem_ui.models.user import ProjectPermission

    if session_factory is None:
        from shyfem_ui.db.base import get_session_factory

        session_factory = get_session_factory()

    db = session_factory()
    try:
        rows = (
            db.query(Project.work_dir)
            .join(ProjectPermission, ProjectPermission.project_id == Project.id)
            .filter(ProjectPermission.user_id == user_id)
            .all()
        )
    finally:
        db.close()

    return [Path(work_dir).resolve() for (work_dir,) in rows]


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
    if user is not None and user.get("role") == ROLE_TUTORIAL:
        return _TUTORIAL_READONLY_MSG
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
    if user.get("role") == ROLE_TUTORIAL:
        return _TUTORIAL_READONLY_MSG
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


def job_read_denied_reason(
    *,
    job_user_id: int | None,
    job_project_id: int | None,
    user: dict | None,
    is_server_mode: bool | None = None,
    session_factory=None,
) -> str | None:
    """Return a user-facing error if ``user`` may NOT READ the job's output /
    details, else None.

    A job's stdout/stderr/working-dir/metadata may be read by its **owner**, an
    **admin**, or any **project member (viewer+)** — broader than the cancel gate
    (which needs editor) since reading is non-destructive, and a tutorial account
    may read jobs it owns or has access to. Fail-closed on an unresolved identity
    in server mode; allowed in local (single-user) mode.

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
            job_project_id, user, min_role="viewer", session_factory=session_factory
        )
        is not None
    ):
        return None
    return "Permission denied: you do not have access to this job."


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
    # Tutorial accounts are READ-ONLY everywhere. Enforced centrally here (every
    # write handler routes through this gate) rather than per-handler, and from
    # the server-validated ``user`` dict — so it cannot be escaped by spoofing
    # the client role signal, and a project-editor grant does not override it. A
    # write is any min_role at or above editor; viewer-level reads are allowed.
    if (
        user is not None
        and user.get("role") == ROLE_TUTORIAL
        and ROLE_HIERARCHY.get(min_role, 0) >= ROLE_HIERARCHY["editor"]
    ):
        return _TUTORIAL_READONLY_MSG
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
