"""Alembic environment for the rulebook service.

The database URL comes from py_common settings (CW_DATABASE_URL), never from alembic.ini;
CW_DB_SCHEMA selects the service schema and holds this service's own alembic_version table.
"""

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

from py_common.logging import configure_logging
from py_common.settings import Settings
from rulebook.infrastructure.models import Base

settings = Settings(service_name="rulebook")
configure_logging(service_name="rulebook-migrations", log_level=settings.log_level)

config = context.config
# ConfigParser interpolation: a literal % in the URL must be escaped.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata: MetaData = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema=settings.db_schema,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table_schema=settings.db_schema,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
