"""SEC-06: session and WS-auth tokens are stored hashed.

The browser (cookie) and the WebSocket client still get the raw 256-bit
token, but the database keeps only ``sha256(raw).hexdigest()`` in
``auth_sessions.token``, ``ws_auth_tokens.token`` and
``ws_auth_tokens.session_token``, so a copy of the database file can no longer
be replayed as a live login. The hash is computed independently here (not by
importing the service helper) so these tests pin the storage format itself.
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models import project as _p  # noqa: F401 -- register models
from shyfem_ui.models import user as _u  # noqa: F401 -- register models
from shyfem_ui.models.user import AuthSession, WSAuthToken
from shyfem_ui.services.auth_service import AuthService

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.fixture()
def auth_service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return AuthService(session_factory=sessionmaker(bind=engine))


@pytest.fixture()
def user(auth_service):
    return auth_service.create_user("alice", "pass", email="alice@example.com")


def _all_rows(auth_service, model):
    with auth_service._session_factory() as db:
        return [(r.token, getattr(r, "session_token", None)) for r in db.query(model).all()]


class TestSessionTokenStorage:
    def test_raw_session_token_is_not_stored(self, auth_service, user):
        raw = auth_service.create_session(user["id"])
        rows = _all_rows(auth_service, AuthSession)
        assert len(rows) == 1
        assert rows[0][0] != raw
        assert raw not in rows[0][0]

    def test_stored_session_token_is_sha256_of_raw(self, auth_service, user):
        raw = auth_service.create_session(user["id"])
        assert _all_rows(auth_service, AuthSession)[0][0] == _sha(raw)

    def test_raw_token_validates_and_deletes(self, auth_service, user):
        raw = auth_service.create_session(user["id"])
        assert auth_service.validate_session(raw)["id"] == user["id"]
        assert auth_service.delete_session(raw) is True
        assert auth_service.validate_session(raw) is None
        assert _all_rows(auth_service, AuthSession) == []

    def test_the_stored_hash_is_not_a_usable_cookie(self, auth_service, user):
        """What a DB reader sees must not itself validate."""
        auth_service.create_session(user["id"])
        stored = _all_rows(auth_service, AuthSession)[0][0]
        assert auth_service.validate_session(stored) is None
        assert auth_service.delete_session(stored) is False

    def test_legacy_plaintext_row_does_not_validate(self, auth_service, user):
        legacy = "a" * 64
        with auth_service._session_factory() as db:
            db.add(
                AuthSession(
                    token=legacy,
                    user_id=user["id"],
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
            db.commit()
        assert auth_service.validate_session(legacy) is None


class TestWSTokenStorage:
    def test_raw_ws_and_session_tokens_are_not_stored(self, auth_service, user):
        sess = auth_service.create_session(user["id"])
        ws = auth_service.create_ws_token(user["id"], sess)
        rows = _all_rows(auth_service, WSAuthToken)
        assert len(rows) == 1
        token, session_token = rows[0]
        assert ws not in token and sess not in token
        assert sess not in session_token and ws not in session_token

    def test_stored_ws_values_are_sha256_of_raw(self, auth_service, user):
        sess = auth_service.create_session(user["id"])
        ws = auth_service.create_ws_token(user["id"], sess)
        assert _all_rows(auth_service, WSAuthToken) == [(_sha(ws), _sha(sess))]

    def test_raw_ws_token_validates(self, auth_service, user):
        sess = auth_service.create_session(user["id"])
        ws = auth_service.create_ws_token(user["id"], sess)
        assert auth_service.validate_ws_token(ws)["id"] == user["id"]

    def test_stored_ws_hash_does_not_validate(self, auth_service, user):
        sess = auth_service.create_session(user["id"])
        auth_service.create_ws_token(user["id"], sess)
        stored = _all_rows(auth_service, WSAuthToken)[0][0]
        assert auth_service.validate_ws_token(stored) is None

    def test_legacy_plaintext_ws_row_does_not_validate(self, auth_service, user):
        sess = auth_service.create_session(user["id"])
        # Positive control: a properly created WS token on this session works,
        # so the refusal below can only come from the WS token lookup itself.
        assert auth_service.validate_ws_token(auth_service.create_ws_token(user["id"], sess))
        # Link to the parent exactly as the parent row stores it, so the parent
        # always resolves whatever the storage format is.
        parent_stored = _all_rows(auth_service, AuthSession)[0][0]
        legacy = "b" * 64
        with auth_service._session_factory() as db:
            db.add(
                WSAuthToken(
                    token=legacy,
                    session_token=parent_stored,
                    user_id=user["id"],
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
            db.commit()
        assert auth_service.validate_ws_token(legacy) is None

    def test_logout_purges_the_sessions_ws_tokens_only(self, auth_service, user):
        sess = auth_service.create_session(user["id"])
        other = auth_service.create_session(user["id"])
        auth_service.create_ws_token(user["id"], sess)
        auth_service.create_ws_token(user["id"], sess)
        keep = auth_service.create_ws_token(user["id"], other)
        with auth_service._session_factory() as db:
            assert db.query(WSAuthToken).filter_by(session_token=_sha(sess)).count() == 2
        assert auth_service.delete_session(sess) is True
        with auth_service._session_factory() as db:
            assert db.query(WSAuthToken).filter_by(session_token=_sha(sess)).count() == 0
            assert db.query(WSAuthToken).count() == 1
        assert auth_service.validate_ws_token(keep)["id"] == user["id"]


# ----------------------------------------------------------------------
# Migration: pre-existing (plaintext) rows are purged on upgrade
# ----------------------------------------------------------------------

_PRE_REVISION = "85f9efff4f5e"


def _alembic_cfg(db: Path):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    cfg.config_file_name = None
    return cfg


def _seed_plaintext_rows(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        uid = conn.execute("SELECT id FROM users WHERE username = 'mig'").fetchone()
        if uid is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active) "
                "VALUES ('mig', 'h', 'user', 1)"
            )
            uid = conn.execute("SELECT id FROM users WHERE username = 'mig'").fetchone()
        uid = uid[0]
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO auth_sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            ("c" * 64, uid, exp),
        )
        conn.execute(
            "INSERT INTO ws_auth_tokens (token, session_token, user_id, expires_at) "
            "VALUES (?, ?, ?, ?)",
            ("d" * 64, "c" * 64, uid, exp),
        )
        conn.commit()
    finally:
        conn.close()


def _counts(db: Path) -> tuple[int, int, int]:
    conn = sqlite3.connect(db)
    try:
        return tuple(
            conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("auth_sessions", "ws_auth_tokens", "users")
        )
    finally:
        conn.close()


def test_migration_upgrade_and_downgrade_purge_token_rows(tmp_path):
    from alembic import command
    from alembic.config import Config as AlembicConfig  # noqa: F401
    from alembic.script import ScriptDirectory

    db = tmp_path / "sec06.db"
    cfg = _alembic_cfg(db)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head != _PRE_REVISION, "SEC-06 needs a revision after 85f9efff4f5e"

    command.upgrade(cfg, _PRE_REVISION)
    _seed_plaintext_rows(db)
    assert _counts(db) == (1, 1, 1)

    command.upgrade(cfg, "head")
    assert _counts(db) == (0, 0, 1), "upgrade must purge plaintext token rows, keep users"

    _seed_plaintext_rows(db)
    command.downgrade(cfg, _PRE_REVISION)
    assert _counts(db) == (0, 0, 1), "downgrade must purge (hashes cannot be un-hashed)"
