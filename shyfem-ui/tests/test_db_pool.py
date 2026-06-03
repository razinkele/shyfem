"""Tests for database connection pool configuration."""

from unittest.mock import patch


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

        with (
            patch("shyfem_ui.db.base.get_config", return_value=cfg),
            patch("shyfem_ui.db.base.create_engine") as mock_engine,
            patch("shyfem_ui.db.base.event.listens_for"),
        ):
            # event.listens_for is no-op'd here: create_engine is mocked, so the
            # real SQLite pragma listener can't bind to the MagicMock engine.
            # This test only inspects the create_engine kwargs.
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

        with (
            patch("shyfem_ui.db.base.get_config", return_value=cfg),
            patch("shyfem_ui.db.base.create_engine") as mock_engine,
        ):
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

        with (
            patch("shyfem_ui.db.base.get_config", return_value=cfg),
            patch("shyfem_ui.db.base.create_engine") as mock_engine,
        ):
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


class TestModelRegistration:
    """All ORM models must be registered on Base.metadata so init_db()'s
    create_all() fallback (used on fresh/packaged installs without Alembic)
    creates every table — incl. audit_logs, which was previously omitted and
    caused 'no such table: audit_logs' on first audit write."""

    def test_audit_logs_registered_via_models_package(self):
        import importlib

        import shyfem_ui.models as models_pkg
        from shyfem_ui.db.base import Base

        importlib.reload(models_pkg)
        assert "audit_logs" in Base.metadata.tables

    def test_init_db_imports_cover_all_model_tables(self):
        """init_db imports a subset of models for create_all; that subset must
        register every table the full models package does (no silent omission)."""
        import shyfem_ui.models  # noqa: F401 -- side-effect import registers all models
        from shyfem_ui.db.base import Base

        expected = {
            "projects",
            "grids",
            "simulations",
            "jobs",
            "project_files",
            "users",
            "auth_sessions",
            "project_permissions",
            "workflows",
            "audit_logs",
        }
        assert expected.issubset(set(Base.metadata.tables.keys()))


class TestSqlitePragmas:
    """The SQLite engine must set busy_timeout (so concurrent writers wait
    instead of raising 'database is locked' immediately) and WAL journal mode
    (concurrent readers + one writer) — the production laguna DB is SQLite."""

    def test_busy_timeout_and_wal_set_on_connect(self, tmp_path, monkeypatch):
        import shyfem_ui.config as cfg_mod
        import shyfem_ui.db.base as db_mod

        monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
        cfg_mod._config = None
        db_mod._engine = None
        db_mod._SessionLocal = None
        try:
            engine = db_mod.get_engine()
            with engine.connect() as conn:
                busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
                jmode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            assert busy == 5000
            assert str(jmode).lower() == "wal"
        finally:
            db_mod._engine = None
            db_mod._SessionLocal = None
            cfg_mod._config = None
