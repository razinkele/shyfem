"""Database engine, session management, and migration support.

Functions:
    init_db: Initialize the database (runs Alembic migrations or falls back to create_all).
    get_engine: Get or create the SQLAlchemy engine (lazily initialized).
    get_db: Generator yielding database sessions (for dependency injection).
    db_session: Context manager for database sessions with auto-commit/rollback.

Classes:
    Base: Declarative base class for all SQLAlchemy models.
"""

from shyfem_ui.db.base import Base, db_session, get_db, get_engine, init_db

__all__ = ["Base", "db_session", "get_db", "get_engine", "init_db"]
