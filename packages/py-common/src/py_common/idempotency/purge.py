"""Deleting expired idempotency keys, once from the command line or daily in a worker.

``purge_expired_keys(settings)`` deletes the expired keys of every tenant in the schema on
``CW_DATABASE_URL`` (its ``search_path``) and returns how many went, or None when the schema has
no ``idempotency_key`` table (the service's migration must call ``create_idempotency_table(op)``
first). ``python -m py_common.idempotency purge`` runs it once. ``purge_job(settings)`` is the
worker's job, daily at 03:30 IST; a worker that hosts several services runs one per schema that
has the table.
"""

from datetime import time

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from py_common.idempotency.schema import IDEMPOTENCY_TABLE
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore
from py_common.logging import get_logger
from py_common.runtime import IST, PeriodicComponent, daily_at
from py_common.settings import Settings

JOB_NAME = "idempotency-purge"
PURGE_AT = time(3, 30, tzinfo=IST)
"""03:30 IST, when little else runs."""

log = get_logger(__name__)


def purge_expired_keys(settings: Settings) -> int | None:
    """Delete the schema's expired keys; how many were deleted, or None without the table."""
    engine = create_engine(settings.database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            present = inspect(connection).has_table(IDEMPOTENCY_TABLE)
        if not present:
            log.error(
                "idempotency.table_missing",
                table=IDEMPOTENCY_TABLE,
                db_schema=settings.db_schema,
                hint="the service's migration must call create_idempotency_table(op) first",
            )
            return None
        return SqlAlchemyIdempotencyStore(engine).purge_expired()
    finally:
        engine.dispose()


def purge_job(settings: Settings, *, at: time = PURGE_AT) -> PeriodicComponent:
    """The daily purge of the schema on the settings' database URL, as a worker component."""

    def purge() -> None:
        purge_expired_keys(settings)

    return PeriodicComponent(JOB_NAME, purge, next_run=daily_at(at))


__all__ = ["JOB_NAME", "PURGE_AT", "purge_expired_keys", "purge_job"]
