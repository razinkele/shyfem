"""Tests for FeedbackService -- create, list, count, set_status, validation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.services.feedback_service import FeedbackService


@pytest.fixture
def svc():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return FeedbackService(session_factory=sessionmaker(bind=engine, expire_on_commit=False))


def test_create_normalizes_and_returns_full_dict(svc):
    rec = svc.create(
        feedback_type="Bug",
        title="  Crash  ",
        description="boom",
        severity="HIGH",
        contact_email="a@b.c",
        page="IBM",
        app_version="0.2.0",
    )
    assert rec["id"] >= 1
    assert rec["feedback_type"] == "bug"  # lower-cased
    assert rec["title"] == "Crash"  # stripped
    assert rec["severity"] == "high"
    assert rec["status"] == "new"
    assert rec["created_at"]


def test_list_newest_first_and_pagination(svc):
    for i in range(3):
        svc.create(feedback_type="bug", title=f"t{i}", description="d")
    assert [r["title"] for r in svc.list()] == ["t2", "t1", "t0"]
    assert len(svc.list(limit=1)) == 1
    assert svc.list(offset=1)[0]["title"] == "t1"


def test_count_and_type_filter(svc):
    svc.create(feedback_type="bug", title="b", description="d")
    svc.create(feedback_type="suggestion", title="s", description="d")
    assert svc.count() == 2
    assert svc.count(feedback_type="bug") == 1
    assert [r["feedback_type"] for r in svc.list(feedback_type="suggestion")] == ["suggestion"]


def test_set_status(svc):
    rec = svc.create(feedback_type="bug", title="t", description="d")
    assert svc.set_status(rec["id"], "triaged") is True
    assert svc.list(status="triaged")[0]["id"] == rec["id"]
    assert svc.set_status(999999, "resolved") is False  # missing row


@pytest.mark.parametrize(
    "kwargs",
    [
        {"feedback_type": "spam", "title": "t", "description": "d"},
        {"feedback_type": "bug", "title": "", "description": "d"},
        {"feedback_type": "bug", "title": "t", "description": ""},
        {"feedback_type": "bug", "title": "t", "description": "d", "severity": "huge"},
    ],
)
def test_create_rejects_invalid(svc, kwargs):
    with pytest.raises(ValueError):
        svc.create(**kwargs)


def test_set_status_rejects_invalid(svc):
    rec = svc.create(feedback_type="bug", title="t", description="d")
    with pytest.raises(ValueError):
        svc.set_status(rec["id"], "bogus")


# --- F47: contact_email format validation + control-char sanitation ---


@pytest.mark.parametrize("bad_email", ["not-an-email", "a@", "@b", "a@b", "a b@c.de", "a@@b.de"])
def test_create_rejects_malformed_email(svc, bad_email):
    with pytest.raises(ValueError):
        svc.create(feedback_type="bug", title="t", description="d", contact_email=bad_email)


@pytest.mark.parametrize("empty_email", [None, "", "   "])
def test_create_allows_missing_email_anonymous(svc, empty_email):
    """Feedback is anonymous -- omitting contact_email must still succeed."""
    rec = svc.create(feedback_type="bug", title="t", description="d", contact_email=empty_email)
    assert rec["contact_email"] is None


def test_create_accepts_well_formed_email(svc):
    rec = svc.create(
        feedback_type="bug", title="t", description="d", contact_email="user@example.com"
    )
    assert rec["contact_email"] == "user@example.com"


def test_create_strips_control_chars_from_title_and_description(svc):
    rec = svc.create(
        feedback_type="bug",
        title="Cra\x07sh\x00",
        description="It br\x0boke\x1f here",
    )
    assert "\x07" not in rec["title"]
    assert "\x00" not in rec["title"]
    assert "\x0b" not in rec["description"]
    assert "\x1f" not in rec["description"]
    assert rec["title"] == "Crash"
    assert rec["description"] == "It broke here"


def test_create_preserves_newlines_and_tabs_in_description(svc):
    rec = svc.create(feedback_type="bug", title="t", description="line1\nline2\ttabbed")
    assert rec["description"] == "line1\nline2\ttabbed"


# --- F52: retention pruning ---


def test_cleanup_old_removes_only_stale_rows(svc):
    from datetime import datetime, timedelta

    from shyfem_ui.models.feedback import Feedback

    now = datetime.now()
    session = svc._session_factory()
    try:
        session.add(
            Feedback(
                feedback_type="bug",
                title="old",
                description="d",
                created_at=now - timedelta(days=200),
            )
        )
        session.add(
            Feedback(
                feedback_type="bug",
                title="recent",
                description="d",
                created_at=now - timedelta(days=1),
            )
        )
        session.commit()
    finally:
        session.close()

    removed = svc.cleanup_old(days=180)

    assert removed == 1
    assert [r["title"] for r in svc.list()] == ["recent"]


def test_cleanup_old_keeps_all_when_none_stale(svc):
    svc.create(feedback_type="bug", title="t", description="d")
    assert svc.cleanup_old(days=180) == 0
    assert len(svc.list()) == 1
