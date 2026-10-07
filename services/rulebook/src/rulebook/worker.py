"""The rulebook worker: ``python -m rulebook.worker``, locally ``make worker SERVICE=rulebook``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what a
process that hosts several services adds to its own:

- with ``CW_RULEBOOK_PUBLISH_ENABLED`` on, the daily sweep that moves each replaced version to
  superseded or withdrawn once its replacement takes effect (``ApplyDueTransitions``, as
  ``rulebook-transitions`` runs it by hand), at 00:05 IST, just after the day's replacements
  start. The sweep is idempotent, so a worker that restarts and runs it twice in a day moves
  nothing twice. A failing run is logged and the job runs again the next day;
  ``rulebook-transitions`` or ``POST /v1/rulebook/maintenance/transitions`` catch up by hand.
- with ``CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED`` on (flag ``rulebook.candidate_intake``), a
  consumer in group ``rulebook.rule-candidates`` of rule.candidate.created
  (``IngestRuleCandidate``): each candidate the pipeline extracts becomes one stored candidate
  and one review task of kind ``candidate``. The handler runs on the consumer's own connection
  (``ConnectionKnowledgeUnitOfWorkFactory``), so the candidate, its task and the
  ``processed_event`` row commit together or not at all, and a redelivered event changes
  nothing. A payload the contract refuses, or a candidate whose document the rulebook does not
  store yet, fails, is retried, and then goes to
  ``rule.candidate.created.rulebook.rule-candidates.dlq``; replaying it once the document is
  registered takes it in. With the flag off no group reads the topic, so the candidates wait
  there (it keeps a month) and the group, once it starts, reads them from the beginning.

- a consumer in group ``rulebook.erasure`` of ``tenant.deletion.requested``
  (``py_common.erasure``), always: while the flag ``identity.tenant_erasure`` is off for the
  tenant it only logs ``erasure.off``; on, it erases nothing, since the rulebook holds regulatory
  data of no tenant, and answers ``tenant.data.erased`` (service rulebook) with the tables it
  keeps and its ``tenant.erased`` audit entry (``infrastructure.erasure``).

They write through Postgres, so the worker needs ``CW_RULEBOOK_STORE=postgres``. The outbox relay
that publishes the moves and the rejections runs on its own (``make relay SERVICE=rulebook``) or
in the combined worker.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import time
from typing import Final

from sqlalchemy import Connection

from cw_contracts.events.rule_candidate_created_v1 import RuleCandidateCreatedV1
from py_common.erasure import Enabled, ErasureSwitch, erasure_component
from py_common.events import EventMessage
from py_common.logging import get_logger
from py_common.outbox import sync_handler
from py_common.outbox.consumer import Handler
from py_common.runtime import (
    IST,
    ConsumerComponent,
    PeriodicComponent,
    WorkerComponents,
    daily_at,
    run_worker_process,
)
from rulebook import __version__
from rulebook.application.alignment import Clock, default_clock
from rulebook.application.intake import IngestRuleCandidate
from rulebook.application.publication import ApplyDueTransitions
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.infrastructure.erasure import PostgresRulebookEraser
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.settings import RulebookSettings

SERVICE_NAME = "rulebook-worker"
ERASURE_SERVICE = "rulebook"
TRANSITIONS_JOB = "rulebook-transitions"
TRANSITIONS_AT = time(0, 5, tzinfo=IST)
"""00:05 IST: replacements take effect at the start of their day in India."""
CANDIDATES_GROUP_ID: Final = "rulebook.rule-candidates"
CANDIDATE_TOPIC: Final = "rule.candidate.created"
CANDIDATE_TOPICS: Final = (CANDIDATE_TOPIC,)

log = get_logger(__name__)

Units = Callable[[], AbstractContextManager[KnowledgeUnitOfWorkFactory]]
"""Opens the store one sweep runs on and closes it after."""
UnitsOnConnection = Callable[[Connection], KnowledgeUnitOfWorkFactory]
"""Units of work inside the transaction the connection has begun."""


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


def candidate_handler(
    *,
    units_on: UnitsOnConnection = PostgresKnowledgeUnitOfWorkFactory.on_connection,
    clock: Clock = default_clock,
) -> Handler:
    """The handler of rule.candidate.created: the payload checked against its contract, then
    the intake on the consumer's connection, in the transaction that records the event as
    processed. ``units_on`` makes the units there; tests pass the memory store's."""

    def handle(message: EventMessage, connection: Connection) -> None:
        if message.topic != CANDIDATE_TOPIC:
            log.info("rulebook.event_ignored", topic=message.topic, event_id=str(message.event_id))
            return
        RuleCandidateCreatedV1.model_validate(message.payload)
        intake = IngestRuleCandidate(units_on(connection), clock).run(
            message.payload, message.event_id
        )
        candidate, task = intake.candidate, intake.task
        log.info(
            "rulebook.candidate_received",
            event_id=str(message.event_id),
            candidate_id=str(candidate.candidate_id),
            document_id=str(candidate.document_id),
            regulator=candidate.regulator,
            outcome=candidate.outcome.value,
            created=intake.created,
            task_id=None if task is None else str(task.task_id),
            priority=None if task is None else task.priority,
            suggested_rule_key=candidate.suggested_rule_key,
        )

    return sync_handler(handle)


def components(settings: RulebookSettings, *, erasure: Enabled | None = None) -> WorkerComponents:
    """The daily transitions sweep while publishing is on, the candidate intake while its flag
    is on, and the erasure consumer always; ``erasure`` replaces its flag."""
    if settings.rulebook_store != "postgres":
        raise ValueError("the rulebook worker needs CW_RULEBOOK_STORE=postgres")
    periodic: tuple[PeriodicComponent, ...] = ()
    if settings.rulebook_publish_enabled:
        periodic = (
            PeriodicComponent(
                TRANSITIONS_JOB,
                transitions_job(postgres_units(settings)),
                next_run=daily_at(TRANSITIONS_AT),
            ),
        )
    consumers: tuple[ConsumerComponent, ...] = ()
    if settings.rulebook_candidate_intake_enabled:
        consumers = (
            ConsumerComponent(
                group_id=CANDIDATES_GROUP_ID, topics=CANDIDATE_TOPICS, handler=candidate_handler()
            ),
        )
    erasure_consumer = erasure_component(
        ERASURE_SERVICE, PostgresRulebookEraser, enabled=erasure or ErasureSwitch(settings)
    )
    return WorkerComponents(consumers=(*consumers, erasure_consumer), periodic=periodic)


def main() -> None:
    run_worker_process(RulebookSettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
