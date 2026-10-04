"""The rulebook worker: ``python -m rulebook.worker``, locally ``make worker SERVICE=rulebook``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what a
process that hosts several services adds to its own: with ``CW_RULEBOOK_PUBLISH_ENABLED`` on,
the daily sweep that moves each replaced version to superseded or withdrawn once its
replacement takes effect (``ApplyDueTransitions``, as ``rulebook-transitions`` runs it by hand),
at 00:05 IST, just after the day's replacements start. The sweep is idempotent, so a worker
that restarts and runs it twice in a day moves nothing twice. A failing run is logged and the
job runs again the next day; ``rulebook-transitions`` or ``POST /v1/rulebook/maintenance/
transitions`` catch up by hand. With the flag off there is nothing to run.

The sweep writes through Postgres, so the worker needs ``CW_RULEBOOK_STORE=postgres``. The
outbox relay that publishes the moves runs on its own (``make relay SERVICE=rulebook``) or in
the combined worker.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import time

from py_common.logging import get_logger
from py_common.runtime import (
    IST,
    PeriodicComponent,
    WorkerComponents,
    daily_at,
    run_worker_process,
)
from rulebook import __version__
from rulebook.application.publication import ApplyDueTransitions
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.settings import RulebookSettings

SERVICE_NAME = "rulebook-worker"
TRANSITIONS_JOB = "rulebook-transitions"
TRANSITIONS_AT = time(0, 5, tzinfo=IST)
"""00:05 IST: replacements take effect at the start of their day in India."""

log = get_logger(__name__)

Units = Callable[[], AbstractContextManager[KnowledgeUnitOfWorkFactory]]
"""Opens the store one sweep runs on and closes it after."""


def postgres_units(settings: RulebookSettings) -> Units:
    """The Postgres store on ``CW_DATABASE_URL``, its engine disposed after each sweep."""

    @contextmanager
    def units() -> Iterator[KnowledgeUnitOfWorkFactory]:
        factory = PostgresKnowledgeUnitOfWorkFactory.from_url(settings.database_url)
        try:
            yield factory
        finally:
            factory.engine.dispose()

    return units


def transitions_job(units: Units) -> Callable[[], None]:
    """One sweep as of today in India, logged with what it moved."""

    def run() -> None:
        with units() as store:
            report = ApplyDueTransitions(store, enabled=True).run()
        log.info(
            "rulebook.transitions_applied",
            as_of=report.as_of.isoformat(),
            moved=len(report.transitions),
            versions=[str(moved.target_id) for moved in report.transitions],
        )

    return run


def components(settings: RulebookSettings) -> WorkerComponents:
    """The daily transitions sweep while publishing is on; nothing while it is off."""
    if settings.rulebook_store != "postgres":
        raise ValueError("the rulebook worker needs CW_RULEBOOK_STORE=postgres")
    if not settings.rulebook_publish_enabled:
        return WorkerComponents()
    return WorkerComponents(
        periodic=(
            PeriodicComponent(
                TRANSITIONS_JOB,
                transitions_job(postgres_units(settings)),
                next_run=daily_at(TRANSITIONS_AT),
            ),
        )
    )


def main() -> None:
    run_worker_process(RulebookSettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
