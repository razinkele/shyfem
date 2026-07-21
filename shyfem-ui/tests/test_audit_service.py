"""Tests for AuditService -- round-trip, filters, and rollback."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.services.audit_service import AuditService


@pytest.fixture
def session_factory():
    """In-memory SQLite session factory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def svc(session_factory):
    return AuditService(session_factory=session_factory)


class TestAuditLogRoundTrip:

    def test_log_then_query_returns_entry(self, svc):
        svc.log(username="alice", action="login", detail="ok", ip_address="10.0.0.1")
        rows = svc.query()
        assert len(rows) == 1
        assert rows[0]["username"] == "alice"
        assert rows[0]["action"] == "login"
        assert rows[0]["detail"] == "ok"
        assert rows[0]["ip_address"] == "10.0.0.1"

    def test_query_returns_newest_first(self, svc):
        svc.log(username="a", action="x")
        svc.log(username="b", action="y")
        rows = svc.query()
        assert rows[0]["username"] == "b"
        assert rows[1]["username"] == "a"


class TestAuditFilters:

    def test_filter_by_username(self, svc):
        svc.log(username="alice", action="login")
        svc.log(username="bob", action="login")
        rows = svc.query(username="alice")
        assert len(rows) == 1
        assert rows[0]["username"] == "alice"

    def test_filter_by_action(self, svc):
        svc.log(username="alice", action="login")
        svc.log(username="alice", action="logout")
        rows = svc.query(action="logout")
        assert len(rows) == 1
        assert rows[0]["action"] == "logout"

    def test_since_accepts_naive_datetime(self, svc):
        """Regression test: naive `since` must not raise on SQLite-native DateTime columns."""
        svc.log(username="alice", action="login")
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        rows = svc.query(since=one_hour_ago)
        assert len(rows) == 1

    def test_since_accepts_aware_datetime(self, svc):
        svc.log(username="alice", action="login")
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        rows = svc.query(since=one_hour_ago)
        assert len(rows) == 1

    def test_pagination_via_offset_and_limit(self, svc):
        for i in range(5):
            svc.log(username=f"u{i}", action="login")
        page1 = svc.query(limit=2, offset=0)
        page2 = svc.query(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert {r["username"] for r in page1} & {r["username"] for r in page2} == set()


class TestAuditCount:

    def test_count_all(self, svc):
        for i in range(3):
            svc.log(username=f"u{i}", action="login")
        assert svc.count() == 3

    def test_count_by_action(self, svc):
        svc.log(username="a", action="login")
        svc.log(username="b", action="login")
        svc.log(username="c", action="logout")
        assert svc.count(action="login") == 2


class TestAuditDistinctActions:

    def test_returns_sorted_distinct_actions(self, svc):
        svc.log(username="a", action="login")
        svc.log(username="b", action="logout")
        svc.log(username="c", action="login")
        assert svc.distinct_actions() == ["login", "logout"]


class TestCleanupOldLogs:
    """audit_logs must be prunable, else the table grows unbounded
    (deep-review medium: maintenance pruned jobs/sessions but not audit_logs)."""

    def test_deletes_logs_older_than_retention(self, svc, session_factory):
        from datetime import datetime, timedelta

        from shyfem_ui.models.audit_log import AuditLog

        now = datetime.now()
        with session_factory() as s:
            s.add(AuditLog(username="a", action="old", timestamp=now - timedelta(days=100)))
            s.add(AuditLog(username="b", action="recent", timestamp=now - timedelta(days=10)))
            s.commit()

        removed = svc.cleanup_old_logs(days=90)

        assert removed == 1
        assert {r["action"] for r in svc.query()} == {"recent"}

    def test_keeps_all_when_none_old(self, svc):
        svc.log(username="a", action="x")
        assert svc.cleanup_old_logs(days=90) == 0

    def test_cutoff_computed_in_utc_not_local(self, svc, session_factory, monkeypatch):
        """L39: AuditLog.timestamp is server_default=func.now() (SQLite
        CURRENT_TIMESTAMP = UTC). The retention cutoff must be UTC too. Simulate
        a server whose local clock is far ahead of UTC: a row 20 days old in UTC
        must be KEPT under a 30-day retention. A naive-local cutoff would place
        the cutoff ahead and wrongly prune it."""
        from datetime import datetime, timedelta

        import shyfem_ui.services.audit_service as audit_mod
        from shyfem_ui.models.audit_log import AuditLog

        real_utc = datetime.utcnow()

        class _SkewedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                # Local clock 15 days ahead of UTC (an extreme offset that makes
                # the naive-local-vs-UTC bug observable within the 30d window).
                return real_utc + timedelta(days=15)

            @classmethod
            def utcnow(cls):
                return real_utc

        monkeypatch.setattr(audit_mod, "datetime", _SkewedDateTime)

        # Row is 20 days old in UTC -> inside a 30-day retention window.
        with session_factory() as s:
            s.add(
                AuditLog(
                    username="u",
                    action="keep_me",
                    timestamp=real_utc - timedelta(days=20),
                )
            )
            s.commit()

        removed = svc.cleanup_old_logs(days=30)

        assert removed == 0
        assert {r["action"] for r in svc.query()} == {"keep_me"}
        assert len(svc.query()) == 1
