"""Clock helpers shared by services, models and tests."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a *naive* datetime.

    Drop-in for the deprecated ``datetime.utcnow()``. Naive on purpose: the
    ``DateTime`` columns are filled by ``server_default=func.now()`` (SQLite
    ``CURRENT_TIMESTAMP``, UTC, no tzinfo) and the in-memory timestamps are
    naive too; comparing an aware value against them raises. Compute retention
    cutoffs and timestamps with this, never with ``datetime.now()`` (local) --
    on a non-UTC server that shifts every window by the local offset.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_to_local(value: datetime | None) -> datetime | None:
    """A naive UTC datetime (a ``server_default=func.now()`` column) as naive
    LOCAL time, for showing it next to the naive-local job times (J-09).
    ``None`` passes through."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
