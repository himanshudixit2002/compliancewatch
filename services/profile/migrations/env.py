"""Alembic environment for the profile service.

The database URL comes from py_common settings (CW_DATABASE_URL), never from alembic.ini;
CW_DB_SCHEMA selects the service schema and holds this service's own alembic_version table. It
is required, and it leads the URL's search_path (py_common.settings.with_search_path) whatever
its options say, so the unqualified tables land in it even on an owner's URL that names none;
without it they would land in public.
"""

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

from profile_service.infrastructure.models import Base
from py_common.logging import configure_logging
from py_common.settings import Settings, with_search_path

settings = Settings(service_name="profile")
configure_logging(service_name="profile-migrations", log_level=settings.log_level)

schema = settings.db_schema
if not schema:
    raise RuntimeError(
        "CW_DB_SCHEMA is not set: the migrations run in the service's own schema, which holds "
        "its alembic_version (make migrate and cw-mvp migrate set it)"
    )

config = context.config
# ConfigParser interpolation: a literal % in the URL must be escaped.
config.set_main_option(
    "sqlalchemy.url", with_search_path(settings.database_url, schema).replace("%", "%%")
)

target_metadata: MetaData = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema=schema,
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
            version_table_schema=schema,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
