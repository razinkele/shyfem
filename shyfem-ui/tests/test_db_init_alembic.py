"""Regression tests for init_db()'s Alembic migration branch (N12).

Bug being guarded: ``db/base.py`` computed
``ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"``.
``parents[1]`` from ``shyfem_ui/db/base.py`` is the ``shyfem_ui`` package
directory, but ``alembic.ini`` actually lives one level higher, at
``shyfem-ui/alembic.ini`` (``parents[2]``). ``ini_path.exists()`` was
therefore always False, so ``init_db()`` silently fell back to
``Base.metadata.create_all()`` for every real (non-test) install — which
never creates an ``alembic_version`` table, so installs were never
migrated or stamped by Alembic.

These tests exercise the real Alembic branch specifically: they assert
that ``alembic_version`` exists and is pinned at the repo's head revision,
which ``create_all()`` alone can never produce.
"""

from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from shyfem_ui.db.base import Base

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _head_revision() -> str:
    """Return the repo's current Alembic head revision id."""
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


def _fresh_engine(tmp_path, monkeypatch, db_name):
    """Point base.py's global engine/session-factory at an isolated temp DB.

    Mirrors the pattern in test_db_fk.py: monkeypatch the cached config and
    engine/session globals so init_db() operates on a throwaway SQLite file
    under tmp_path rather than the real shyfem-ui/shyfem_ui.db.
    """
    import shyfem_ui.config as cfg
    import shyfem_ui.db.base as base

    db = tmp_path / db_name
    monkeypatch.setattr(cfg, "_config", cfg.Config(database_url=f"sqlite:///{db}"))
    monkeypatch.setattr(base, "_engine", None)
    monkeypatch.setattr(base, "_SessionLocal", None)
    return base


def test_fresh_db_is_migrated_to_head(tmp_path, monkeypatch):
    """init_db() on an empty DB must run real Alembic migrations to head."""
    base = _fresh_engine(tmp_path, monkeypatch, "fresh.db")

    base.init_db()

    engine = base.get_engine()
    tables = set(inspect(engine).get_table_names())

    assert "alembic_version" in tables, (
        "init_db() did not create alembic_version -- the Alembic branch never "
        "ran (silently fell back to create_all(), which never stamps a "
        "migration version)"
    )
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == _head_revision()
    assert "feedbacks" in tables


def test_legacy_create_all_db_is_stamped(tmp_path, monkeypatch):
    """A pre-existing create_all()-produced DB must be stamped at head
    (not re-migrated), and none of its existing tables may be dropped."""
    base = _fresh_engine(tmp_path, monkeypatch, "legacy.db")

    # Import every model module so Base.metadata is fully populated, then
    # simulate a database that predates Alembic tracking: schema created via
    # create_all(), no alembic_version table.
    from shyfem_ui.models import audit_log, feedback, project, user, workflow  # noqa: F401

    engine = base.get_engine()
    Base.metadata.create_all(bind=engine)
    tables_before = set(inspect(engine).get_table_names())
    assert "alembic_version" not in tables_before
    assert "feedbacks" in tables_before

    base.init_db()

    tables_after = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables_after, (
        "init_db() did not stamp the legacy create_all() database -- the "
        "Alembic branch never ran"
    )
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == _head_revision()
    assert tables_before <= tables_after, "stamping must not drop existing tables"
