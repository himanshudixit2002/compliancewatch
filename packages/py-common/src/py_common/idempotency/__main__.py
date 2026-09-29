"""``python -m py_common.idempotency purge``: delete the expired idempotency keys of every tenant
in the schema on ``CW_DATABASE_URL`` (its ``search_path``), for a daily schedule.

Exit codes: 0 when the purge ran, 1 when the schema has no ``idempotency_key`` table (the
service's migration must call ``create_idempotency_table(op)`` first), 2 for a usage error.
"""

import argparse
from collections.abc import Sequence

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from py_common.idempotency.schema import IDEMPOTENCY_TABLE
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore
from py_common.logging import configure_logging, get_logger
from py_common.settings import Settings

SERVICE_NAME = "idempotency-purge"

log = get_logger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m py_common.idempotency",
        description="Idempotency keys of the schema on CW_DATABASE_URL.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("purge", help="delete the expired keys of every tenant")
    parser.parse_args(argv)
    settings = Settings(service_name=SERVICE_NAME)
    configure_logging(
        service_name=SERVICE_NAME, log_level=settings.log_level, json_output=settings.log_json
    )
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
            return 1
        SqlAlchemyIdempotencyStore(engine).purge_expired()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
