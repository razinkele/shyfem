"""Tests for the /api/feedback endpoints in SessionAuthMiddleware.

Anonymous rate-limiting is supplied by the separate (already-tested)
RateLimitMiddleware; these tests cover the SessionAuthMiddleware handlers:
admin-only GET and anonymous POST with validation.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.middleware.session_auth import SessionAuthMiddleware
from shyfem_ui.services.feedback_service import FeedbackService


def _svc():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return FeedbackService(session_factory=sessionmaker(bind=engine, expire_on_commit=False))


def _mw(role=None, feedback_service=None):
    auth = MagicMock()
    auth.validate_session.return_value = (
        None if role is None else {"id": 1, "username": "u", "role": role}
    )
    return SessionAuthMiddleware(AsyncMock(), auth, feedback_service=feedback_service)


def _http(path, method, cookie=None):
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return {
        "type": "http",
        "path": path,
        "method": method,
        "headers": headers,
        "query_string": b"",
    }


async def _drive(mw, scope, body=b""):
    sent = []
    pending = [{"type": "http.request", "body": body, "more_body": False}]

    async def send(m):
        sent.append(m)

    async def receive():
        return (
            pending.pop(0) if pending else {"type": "http.request", "body": b"", "more_body": False}
        )

    await mw(scope, receive, send)
    return sent


def _status(sent):
    return sent[0]["status"]


def _json(sent):
    return json.loads(sent[1]["body"])


@pytest.mark.asyncio
async def test_post_anonymous_creates_201():
    svc = _svc()
    mw = _mw(feedback_service=svc)
    body = json.dumps({"type": "bug", "title": "x", "description": "y"}).encode()
    sent = await _drive(mw, _http("/api/feedback", "POST"), body=body)
    assert _status(sent) == 201
    assert _json(sent)["status"] == "new"
    assert svc.count() == 1


@pytest.mark.asyncio
async def test_post_bad_json_400():
    sent = await _drive(_mw(feedback_service=_svc()), _http("/api/feedback", "POST"), body=b"{nope")
    assert _status(sent) == 400


@pytest.mark.asyncio
async def test_post_oversized_body_413():
    svc = _svc()
    big = json.dumps({"type": "bug", "title": "x", "description": "y" * 70000}).encode()
    sent = await _drive(_mw(feedback_service=svc), _http("/api/feedback", "POST"), body=big)
    assert _status(sent) == 413
    assert svc.count() == 0  # never reached the DB


@pytest.mark.asyncio
async def test_post_missing_description_400():
    svc = _svc()
    body = json.dumps({"type": "bug", "title": "x"}).encode()
    sent = await _drive(_mw(feedback_service=svc), _http("/api/feedback", "POST"), body=body)
    assert _status(sent) == 400
    assert svc.count() == 0


@pytest.mark.asyncio
async def test_post_invalid_type_400():
    body = json.dumps({"type": "spam", "title": "x", "description": "y"}).encode()
    sent = await _drive(_mw(feedback_service=_svc()), _http("/api/feedback", "POST"), body=body)
    assert _status(sent) == 400


@pytest.mark.asyncio
async def test_get_no_cookie_403():
    sent = await _drive(_mw(role=None, feedback_service=_svc()), _http("/api/feedback", "GET"))
    assert _status(sent) == 403


@pytest.mark.asyncio
async def test_get_non_admin_403():
    mw = _mw(role="user", feedback_service=_svc())
    sent = await _drive(mw, _http("/api/feedback", "GET", cookie="shyfem_session=tok"))
    assert _status(sent) == 403


@pytest.mark.asyncio
async def test_get_admin_returns_data():
    svc = _svc()
    svc.create(feedback_type="bug", title="x", description="y")
    mw = _mw(role="admin", feedback_service=svc)
    sent = await _drive(mw, _http("/api/feedback", "GET", cookie="shyfem_session=tok"))
    assert _status(sent) == 200
    payload = _json(sent)
    assert payload["total"] == 1
    assert payload["data"][0]["title"] == "x"
