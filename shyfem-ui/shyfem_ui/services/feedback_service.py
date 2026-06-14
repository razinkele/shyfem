"""Feedback service -- stores and queries user-submitted bug reports / suggestions."""

import logging

from shyfem_ui.models.feedback import Feedback

logger = logging.getLogger(__name__)

VALID_TYPES = ("bug", "suggestion")
VALID_STATUSES = ("new", "triaged", "resolved", "wontfix")
VALID_SEVERITIES = ("low", "medium", "high")

_TITLE_MAX = 255
_DESC_MAX = 8000
_EMAIL_MAX = 255
_PAGE_MAX = 64
_VERSION_MAX = 32
_LIST_MAX = 500


class FeedbackService:
    """Creates and queries Feedback rows."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from shyfem_ui.db.base import get_session_factory

            session_factory = get_session_factory()
        self._session_factory = session_factory

    def create(
        self,
        *,
        feedback_type: str,
        title: str,
        description: str,
        severity: str | None = None,
        contact_email: str | None = None,
        page: str | None = None,
        app_version: str | None = None,
    ) -> dict:
        """Create a feedback row.

        Validates and length-bounds all fields (the same caps the API relies on
        as abuse defense). Raises ValueError on invalid/empty required input.
        """
        feedback_type = (feedback_type or "").strip().lower()
        if feedback_type not in VALID_TYPES:
            raise ValueError(f"feedback_type must be one of {VALID_TYPES}")
        title = (title or "").strip()
        description = (description or "").strip()
        if not title or not description:
            raise ValueError("title and description are required")
        severity = (severity or "").strip().lower() or None
        if severity is not None and severity not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {VALID_SEVERITIES}")

        row = Feedback(
            feedback_type=feedback_type,
            title=title[:_TITLE_MAX],
            description=description[:_DESC_MAX],
            severity=severity,
            contact_email=_clip((contact_email or "").strip(), _EMAIL_MAX),
            page=_clip((page or "").strip(), _PAGE_MAX),
            app_version=_clip((app_version or "").strip(), _VERSION_MAX),
        )
        session = self._session_factory()
        try:
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_dict(row)
        except Exception:
            session.rollback()
            logger.exception("Failed to create feedback")
            raise
        finally:
            session.close()

    def list(
        self,
        *,
        status: str | None = None,
        feedback_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Return feedback rows, newest first, with optional filters + pagination."""
        limit = max(1, min(int(limit), _LIST_MAX))
        offset = max(0, int(offset))
        session = self._session_factory()
        try:
            q = session.query(Feedback).order_by(Feedback.created_at.desc(), Feedback.id.desc())
            if status:
                q = q.filter(Feedback.status == status)
            if feedback_type:
                q = q.filter(Feedback.feedback_type == feedback_type)
            return [self._to_dict(r) for r in q.offset(offset).limit(limit).all()]
        finally:
            session.close()

    def count(self, *, status: str | None = None, feedback_type: str | None = None) -> int:
        """Count feedback rows (for pagination info)."""
        session = self._session_factory()
        try:
            q = session.query(Feedback)
            if status:
                q = q.filter(Feedback.status == status)
            if feedback_type:
                q = q.filter(Feedback.feedback_type == feedback_type)
            return q.count()
        finally:
            session.close()

    def set_status(self, feedback_id: int, status: str) -> bool:
        """Update a row's triage status. Returns False if the row does not exist."""
        status = (status or "").strip().lower()
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        session = self._session_factory()
        try:
            row = session.get(Feedback, feedback_id)
            if row is None:
                return False
            row.status = status
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("Failed to update feedback status")
            raise
        finally:
            session.close()

    @staticmethod
    def _to_dict(r: Feedback) -> dict:
        return {
            "id": r.id,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
            "feedback_type": r.feedback_type,
            "title": r.title,
            "description": r.description,
            "severity": r.severity,
            "contact_email": r.contact_email,
            "page": r.page,
            "app_version": r.app_version,
            "status": r.status,
        }


def _clip(value: str, maxlen: int) -> str | None:
    """Return a length-capped non-empty string, or None."""
    value = (value or "").strip()
    return value[:maxlen] if value else None
