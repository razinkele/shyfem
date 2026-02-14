"""SQLAlchemy database configuration and session management."""

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect
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
        _engine = create_engine(
            config.database_url,
            connect_args={"check_same_thread": False} if "sqlite" in config.database_url else {},
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
    # Import models to register them with Base
    from shyfem_ui.models import project  # noqa: F401

    engine = get_engine()

    try:
        from pathlib import Path

        from alembic import command
        from alembic.config import Config as AlembicConfig

        ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
        if not ini_path.exists():
            # Running from installed package — fall back to create_all
            logger.debug("alembic.ini not found, using create_all()")
            Base.metadata.create_all(bind=engine)
            return

        alembic_cfg = AlembicConfig(str(ini_path))
        alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))

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
        session.rollback()
        raise
    finally:
        session.close()
