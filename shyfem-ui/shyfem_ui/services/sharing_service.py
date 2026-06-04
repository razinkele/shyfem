"""Service for managing project sharing permissions."""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User

logger = logging.getLogger(__name__)


class SharingService:
    """Manages project permission grants between users."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from shyfem_ui.db.base import get_session_factory

            session_factory = get_session_factory()
        self._session_factory = session_factory

    #: roles a project may be *shared* with (owner is implicit, not assignable)
    SHAREABLE_ROLES = ("viewer", "editor")

    def share_project(self, project_id: int, user_id: int, role: str = "viewer") -> bool:
        """Grant or update a user's access to a project.

        ``role`` must be one of :attr:`SHAREABLE_ROLES`; anything else (e.g. a
        client-supplied ``"owner"`` over the WS) raises ``ValueError`` — without
        this the string was stored verbatim, allowing escalation to project owner.
        """
        if role not in self.SHAREABLE_ROLES:
            raise ValueError(
                f"invalid share role: {role!r} (allowed: {', '.join(self.SHAREABLE_ROLES)})"
            )
        db = self._session_factory()
        try:
            existing = (
                db.query(ProjectPermission)
                .filter_by(project_id=project_id, user_id=user_id)
                .first()
            )
            if existing:
                existing.role = role
            else:
                perm = ProjectPermission(project_id=project_id, user_id=user_id, role=role)
                db.add(perm)
            db.commit()
            return True
        except IntegrityError:
            # Concurrent insert won the race; fold into the update path.
            db.rollback()
            existing = (
                db.query(ProjectPermission)
                .filter_by(project_id=project_id, user_id=user_id)
                .first()
            )
            if existing:
                existing.role = role
                db.commit()
                return True
            logger.exception("share_project IntegrityError without existing permission")
            raise
        except Exception:
            db.rollback()
            logger.exception("Failed to share project %s with user %s", project_id, user_id)
            raise
        finally:
            db.close()

    def unshare_project(self, project_id: int, user_id: int) -> bool:
        """Revoke a user's access to a project."""
        db = self._session_factory()
        try:
            perm = (
                db.query(ProjectPermission)
                .filter_by(project_id=project_id, user_id=user_id)
                .first()
            )
            if not perm:
                return False
            db.delete(perm)
            db.commit()
            return True
        except Exception:
            db.rollback()
            logger.exception("Failed to unshare project %s from user %s", project_id, user_id)
            raise
        finally:
            db.close()

    def list_permissions(self, project_id: int) -> list[dict]:
        """List all users with access to a project (excluding owner)."""
        db = self._session_factory()
        try:
            perms = (
                db.query(ProjectPermission, User)
                .join(User, ProjectPermission.user_id == User.id)
                .filter(ProjectPermission.project_id == project_id)
                .all()
            )
            return [
                {
                    "user_id": perm.user_id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "role": perm.role,
                }
                for perm, user in perms
            ]
        finally:
            db.close()

    def get_user_role(self, project_id: int, user_id: int) -> str | None:
        """Get a user's role for a project. Returns 'owner', 'editor', 'viewer', or None."""
        db = self._session_factory()
        try:
            project = db.query(Project).filter_by(id=project_id).first()
            if not project:
                return None
            if project.owner_id == user_id:
                return "owner"
            perm = (
                db.query(ProjectPermission)
                .filter_by(project_id=project_id, user_id=user_id)
                .first()
            )
            return perm.role if perm else None
        finally:
            db.close()

    def list_shareable_users(self, project_id: int, exclude_user_id: int) -> list[dict]:
        """List users that can be shared with (active, not owner, not already shared)."""
        db = self._session_factory()
        try:
            already_shared = select(ProjectPermission.user_id).where(
                ProjectPermission.project_id == project_id
            )
            users = (
                db.query(User)
                .filter(
                    User.is_active == True,  # noqa: E712
                    User.id != exclude_user_id,
                    ~User.id.in_(already_shared),
                )
                .order_by(User.username)
                .all()
            )
            return [
                {"id": u.id, "username": u.username, "display_name": u.display_name} for u in users
            ]
        finally:
            db.close()
