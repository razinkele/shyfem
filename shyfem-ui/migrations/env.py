"""Alembic environment configuration.

Uses the app's Config to get the database URL and Base.metadata
for autogenerate support. SQLite batch mode is enabled for ALTER TABLE
compatibility.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Alembic Config object
config = context.config

# Set up loggers from the .ini file. disable_existing_loggers=False is
# load-bearing: fileConfig's default (True) permanently disables every logger
# that already exists -- every module-level logging.getLogger(__name__) in the
# app -- the first time a migration runs in-process. init_db() additionally
# skips this block (it nulls config_file_name, see db/base.py) so alembic.ini
# does not also replace the root logger's handlers; this kwarg is the guard
# for every other caller (tests/test_alembic_logging.py).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Import every model module so Base.metadata is fully populated for
# autogenerate. Skipping a module here causes autogenerate to silently
# propose dropping its tables (see audit_logs incident, 2026-05-28).
from shyfem_ui.db.base import Base
from shyfem_ui.models import audit_log  # noqa: F401
from shyfem_ui.models import feedback  # noqa: F401
from shyfem_ui.models import project  # noqa: F401
from shyfem_ui.models import user  # noqa: F401
from shyfem_ui.models import workflow  # noqa: F401

target_metadata = Base.metadata

# If no URL was set on the command line, read it from the app config
if not config.get_main_option("sqlalchemy.url"):
    from shyfem_ui.config import get_config

    app_config = get_config()
    config.set_main_option("sqlalchemy.url", app_config.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (apply to live database)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
