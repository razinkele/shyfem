"""Tests for database connection pool configuration."""

from unittest.mock import patch

import pytest


class TestPoolConfig:
    """Tests for pool-related config fields."""

    def test_default_pool_size(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")
        assert cfg.db_pool_size == 5

    def test_default_pool_overflow(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")
        assert cfg.db_pool_overflow == 10

    def test_default_pool_recycle(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")
        assert cfg.db_pool_recycle == 3600

    def test_custom_pool_size(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test", db_pool_size=20)
        assert cfg.db_pool_size == 20


class TestEnginePoolArgs:
    """Tests for pool args passed to create_engine."""

    def test_sqlite_no_pool_args(self):
        """SQLite engine should NOT receive pool args."""
        from shyfem_ui.config import Config
        cfg = Config(database_url="sqlite:///./test.db")

        with patch("shyfem_ui.db.base.get_config", return_value=cfg), \
             patch("shyfem_ui.db.base.create_engine") as mock_engine:
            import shyfem_ui.db.base as db_mod
            db_mod._engine = None  # reset cached engine
            try:
                db_mod.get_engine()
                _, kwargs = mock_engine.call_args
                assert "pool_size" not in kwargs
                assert "pool_pre_ping" not in kwargs
                assert kwargs["connect_args"] == {"check_same_thread": False}
            finally:
                db_mod._engine = None

    def test_postgresql_gets_pool_args(self):
        """PostgreSQL engine should receive pool args."""
        from shyfem_ui.config import Config
        cfg = Config(
            database_url="postgresql://localhost/test",
            db_pool_size=10,
            db_pool_overflow=20,
            db_pool_recycle=1800,
        )

        with patch("shyfem_ui.db.base.get_config", return_value=cfg), \
             patch("shyfem_ui.db.base.create_engine") as mock_engine:
            import shyfem_ui.db.base as db_mod
            db_mod._engine = None
            try:
                db_mod.get_engine()
                _, kwargs = mock_engine.call_args
                assert kwargs["pool_size"] == 10
                assert kwargs["max_overflow"] == 20
                assert kwargs["pool_recycle"] == 1800
                assert kwargs["pool_pre_ping"] is True
                assert "connect_args" not in kwargs
            finally:
                db_mod._engine = None

    def test_postgresql_default_pool_args(self):
        """PostgreSQL with default config values."""
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")

        with patch("shyfem_ui.db.base.get_config", return_value=cfg), \
             patch("shyfem_ui.db.base.create_engine") as mock_engine:
            import shyfem_ui.db.base as db_mod
            db_mod._engine = None
            try:
                db_mod.get_engine()
                _, kwargs = mock_engine.call_args
                assert kwargs["pool_size"] == 5
                assert kwargs["max_overflow"] == 10
                assert kwargs["pool_recycle"] == 3600
                assert kwargs["pool_pre_ping"] is True
            finally:
                db_mod._engine = None
