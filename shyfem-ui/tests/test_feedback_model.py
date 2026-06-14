"""Tests for the Feedback model -- table creation, round-trip, defaults."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.feedback import Feedback


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_feedbacks_table_created():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert "feedbacks" in inspect(engine).get_table_names()


def test_insert_populates_id_created_at_status(session):
    fb = Feedback(feedback_type="bug", title="t", description="d")
    session.add(fb)
    session.commit()
    session.refresh(fb)
    assert fb.id is not None
    assert fb.created_at is not None
    assert fb.status == "new"  # server_default
    assert fb.severity is None and fb.contact_email is None


def test_optional_fields_accept_values(session):
    fb = Feedback(
        feedback_type="suggestion",
        title="t",
        description="d",
        severity="high",
        contact_email="a@b.c",
        page="IBM",
        app_version="0.2.0",
    )
    session.add(fb)
    session.commit()
    session.refresh(fb)
    assert fb.severity == "high"
    assert fb.contact_email == "a@b.c"
    assert fb.page == "IBM"
    assert fb.app_version == "0.2.0"
