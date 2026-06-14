"""Feedback model -- user-submitted bug reports and suggestions."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from shyfem_ui.db.base import Base


class Feedback(Base):
    """A bug report or suggestion submitted from the UI.

    Submission is anonymous-friendly: only ``feedback_type``, ``title`` and
    ``description`` are required; everything else is optional or auto-captured,
    so there are no foreign keys (most rows have no associated user).
    """

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
    # "bug" | "suggestion" (validated in the service / API handler)
    feedback_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Auto-captured context (never trusted beyond a length-bounded string).
    page: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Admin triage state: new | triaged | resolved | wontfix
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'new'"), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<Feedback(id={self.id}, type={self.feedback_type!r}, "
            f"status={self.status!r}, title={self.title!r})>"
        )
