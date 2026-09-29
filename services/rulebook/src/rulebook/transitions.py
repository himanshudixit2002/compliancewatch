"""``rulebook-transitions``: the daily sweep that moves replaced rule versions.

A version replaced by one dated in the future stays published, with its ``effective_to`` cut,
until the replacement takes effect; this command moves every such version whose replacement's
``effective_from`` is today in India (or ``--as-of``, never later) to superseded or withdrawn and
writes its event to the outbox. It is idempotent, so running it more than once a day is safe.
With ``CW_RULEBOOK_PUBLISH_ENABLED`` off it changes nothing. ``POST /v1/rulebook/maintenance/
transitions`` runs the same sweep.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from domain_kernel.errors import DomainError
from py_common.logging import configure_logging
from rulebook.application.publication import ApplyDueTransitions
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.settings import RulebookSettings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulebook-transitions", description=__doc__)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="day to sweep up to (YYYY-MM-DD)"
    )
    args = parser.parse_args(argv)
    settings = RulebookSettings(service_name="rulebook-transitions")
    configure_logging(service_name="rulebook-transitions", log_level=settings.log_level)
    if not settings.rulebook_publish_enabled:
        sys.stdout.write("transitions: CW_RULEBOOK_PUBLISH_ENABLED is off; nothing moved\n")
        return 0
    factory = PostgresKnowledgeUnitOfWorkFactory.from_url(settings.database_url)
    try:
        report = ApplyDueTransitions(factory, enabled=True).run(args.as_of)
    except DomainError as exc:
        sys.stderr.write(f"transitions: {exc.detail}\n")
        return 1
    finally:
        factory.engine.dispose()
    sys.stdout.write(f"transitions as of {report.as_of}: {len(report.transitions)} moved\n")
    for moved in report.transitions:
        sys.stdout.write(
            f"  {moved.target_id} -> {moved.moves_to.value} by {moved.replacing_id}"
            f" from {moved.replacing_from}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
