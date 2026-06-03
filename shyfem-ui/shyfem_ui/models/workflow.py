"""SQLAlchemy model for persisted workflow instances."""

from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import JSON, Column, DateTime, Enum, Integer, String

from shyfem_ui.db.base import Base


def _utcnow() -> datetime:
    """Naive UTC timestamp for column defaults — replaces the deprecated
    ``datetime.utcnow`` callable. Naive to match the plain ``DateTime`` columns
    (no ``timezone=True``)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkflowStatus(PyEnum):
    """Workflow execution status. Defined here (not in services) to avoid
    a service->model circular import -- services/workflow.py imports this
    model class for DB queries, so the enum must live model-side."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    template = Column(String, nullable=False)
    status = Column(
        Enum(WorkflowStatus, name="workflow_status"),
        nullable=False,
        default=WorkflowStatus.PENDING,
    )
    # JSON column stores list[dict] -- the WorkflowStep schema is owned by
    # the service (de)serialization layer; not enforced at the DB level.
    steps = Column(JSON, nullable=False, default=list)
    project_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
    completed_at = Column(DateTime, nullable=True)
