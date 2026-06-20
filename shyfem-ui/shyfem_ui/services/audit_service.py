"""Audit logging service -- records user actions to the database."""

import logging
from datetime import datetime, timedelta, timezone

from shyfem_ui.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """Writes and queries audit log entries."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from shyfem_ui.db.base import get_session_factory

            session_factory = get_session_factory()
        self._session_factory = session_factory

    def log(
        self,
        username: str,
        action: str,
        detail: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Record an audit event.

        Args:
            username: Who performed the action.
            action: Short verb (e.g. "login", "logout", "create_user").
            detail: Optional free-text detail.
            ip_address: Client IP if available.
        """
        session = self._session_factory()
        try:
            entry = AuditLog(
                username=username,
                action=action,
                detail=detail,
                ip_address=ip_address,
            )
            session.add(entry)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to write audit log entry")
        finally:
            session.close()

    def query(
        self,
        *,
        username: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Fetch audit log entries with optional filters.

        Returns:
            List of dicts with id, timestamp, username, action, detail, ip_address.
        """
        session = self._session_factory()
        try:
            q = session.query(AuditLog).order_by(AuditLog.timestamp.desc())
            if username:
                q = q.filter(AuditLog.username == username)
            if action:
                q = q.filter(AuditLog.action == action)
            if since:
                if since.tzinfo is not None:
                    since = since.astimezone(timezone.utc).replace(tzinfo=None)
                q = q.filter(AuditLog.timestamp >= since)
            rows = q.offset(offset).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "username": r.username,
                    "action": r.action,
                    "detail": r.detail or "",
                    "ip_address": r.ip_address or "",
                }
                for r in rows
            ]
        finally:
            session.close()

    def count(
        self,
        *,
        username: str | None = None,
        action: str | None = None,
    ) -> int:
        """Count total audit log entries (for pagination info)."""
        session = self._session_factory()
        try:
            q = session.query(AuditLog)
            if username:
                q = q.filter(AuditLog.username == username)
            if action:
                q = q.filter(AuditLog.action == action)
            return q.count()
        finally:
            session.close()

    def distinct_actions(self) -> list[str]:
        """Return all distinct action values in the log."""
        session = self._session_factory()
        try:
            rows = session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
            return [r[0] for r in rows]
        finally:
            session.close()

    def cleanup_old_logs(self, days: int) -> int:
        """Delete audit log entries older than ``days``, returning the count
        removed. Without this the audit_logs table grows unbounded (every action
        is logged). Best-effort: a DB failure is logged and returns 0."""
        cutoff = datetime.now() - timedelta(days=days)
        session = self._session_factory()
        try:
            count = (
                session.query(AuditLog)
                .filter(AuditLog.timestamp < cutoff)
                .delete(synchronize_session=False)
            )
            session.commit()
            return count
        except Exception:
            session.rollback()
            logger.exception("Failed to prune old audit logs")
            return 0
        finally:
            session.close()
