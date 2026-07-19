"""SQLAlchemy database configuration and session management."""

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from shyfem_ui.config import get_config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# Engine and session factory (lazily initialized)
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        is_sqlite = "sqlite" in config.database_url

        if is_sqlite:
            _engine = create_engine(
                config.database_url,
                connect_args={"check_same_thread": False},
                echo=False,
            )

            # Concurrency hardening for the multi-user SQLite deployment:
            # busy_timeout makes concurrent writers WAIT (default 0 raises
            # 'database is locked' immediately), and WAL lets readers run
            # alongside a writer. Applied on every pooled connection.
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - tiny
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA busy_timeout=5000")
                cur.execute("PRAGMA journal_mode=WAL")
                # SQLite ignores foreign keys unless this is set per-connection.
                # Without it a deleted user/project leaves dangling child rows
                # (the delete paths now clean up or SET NULL their children so
                # enforcement does not reject legitimate deletes).
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        else:
            _engine = create_engine(
                config.database_url,
                pool_size=config.db_pool_size,
                max_overflow=config.db_pool_overflow,
                pool_recycle=config.db_pool_recycle,
                pool_pre_ping=True,
                echo=False,
            )
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


def init_db() -> None:
    """Initialize the database using Alembic migrations.

    For new databases, runs all migrations from scratch.
    For existing databases without Alembic version tracking, stamps the
    current head so future migrations apply cleanly.
    Falls back to create_all() if Alembic is unavailable.
    """
    # Import models to register them with Base (every table, so the create_all
    # fallback is complete — audit_log was previously omitted, leaving
    # audit_logs absent on fresh/packaged installs without Alembic).
    from shyfem_ui.models import audit_log, feedback, project, user, workflow  # noqa: F401

    engine = get_engine()

    try:
        from pathlib import Path

        from alembic import command
        from alembic.config import Config as AlembicConfig

        ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"
        if not ini_path.exists():
            # Running from installed package — fall back to create_all
            logger.debug("alembic.ini not found, using create_all()")
            Base.metadata.create_all(bind=engine)
            return

        alembic_cfg = AlembicConfig(str(ini_path))
        alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))
        # set_main_option() above already forced alembic_cfg to read (and
        # memoize) the ini file with `here` resolved from ini_path, so every
        # later get_main_option() call (script_location, etc.) still works
        # correctly even though we clear config_file_name next. We clear it
        # so migrations/env.py's `if config.config_file_name is not None:
        # fileConfig(config.config_file_name)` boilerplate is skipped:
        # logging.config.fileConfig() defaults to disable_existing_loggers=
        # True, which permanently disables every logger already registered
        # at import time (e.g. every module-level logging.getLogger(__name__)
        # in this app) — silently breaking application logging the first
        # time a migration/stamp actually runs. Do NOT reorder these two
        # lines: nulling config_file_name before set_main_option would make
        # `here` resolve to the cwd instead of the ini's directory.
        alembic_cfg.config_file_name = None

        # Check if the DB already has tables but no alembic_version
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        has_tables = bool(set(tables) - {"alembic_version"})
        has_alembic = "alembic_version" in tables

        if has_tables and not has_alembic:
            # Existing DB created by create_all() — stamp current head
            logger.info("Existing database detected, stamping Alembic head")
            command.stamp(alembic_cfg, "head")
        else:
            # New DB or already tracked — run migrations
            command.upgrade(alembic_cfg, "head")

    except ImportError:
        logger.debug("Alembic not installed, using create_all()")
        Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields database sessions."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        logger.exception("Database session error, rolling back")
        session.rollback()
        raise
    finally:
        session.close()
