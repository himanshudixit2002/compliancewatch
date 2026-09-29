"""``python -m py_common.idempotency purge``: delete the expired idempotency keys of every tenant
in the schema on ``CW_DATABASE_URL`` (its ``search_path``) once. A worker runs the same purge
daily (``py_common.idempotency.purge.purge_job``).

Exit codes: 0 when the purge ran, 1 when the schema has no ``idempotency_key`` table (the
service's migration must call ``create_idempotency_table(op)`` first), 2 for a usage error.
"""

import argparse
from collections.abc import Sequence

from py_common.idempotency.purge import purge_expired_keys
from py_common.logging import configure_logging
from py_common.settings import Settings

SERVICE_NAME = "idempotency-purge"


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
    return 1 if purge_expired_keys(settings) is None else 0


if __name__ == "__main__":
    raise SystemExit(main())
