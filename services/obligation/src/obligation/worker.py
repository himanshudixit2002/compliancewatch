"""The obligation worker: ``python -m obligation.worker``, locally
``make worker SERVICE=obligation``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what a
process that hosts several services adds to its own:

- a consumer in group ``obligation.decisions`` of applicability.decided. Each decision becomes
  ``ApplyDecision.run`` on units of work that join the consumer's own transaction
  (``PostgresUnitOfWorkFactory.on_connection``), so the obligations, their outbox rows and change
  rows, and the ``processed_event`` row commit together and a redelivered decision changes
  nothing twice. ``applies`` materialises the obligations of the business and the rule version,
  read from the rulebook at ``CW_RULEBOOK_URL``; ``not_applicable`` closes the open ones with
  ``profile_changed``; a decision that needs review is only marked processed. A message the
  handler cannot read, or whose rule version the rulebook cannot give, goes to
  ``applicability.decided.obligation.decisions.dlq`` after the consumer's retries.
- the reminder sweep, ``SendDueReminders.run``, every ``CW_OBLIGATION_SWEEP_INTERVAL_SECONDS``
  (an hour) when ``CW_OBLIGATION_SWEEP_ENABLED`` is on (off by default): obligation.due_soon for
  open obligations due within 7, 3 and 1 days, one tenant at a time through the
  ``obligation_tenant`` directory, once per obligation, due date and threshold.

The rule lifecycle events (rule.withdrawn, rule.superseded, rule.deadline_changed) carry no
tenant and are not consumed yet: applying them means one unit of work per tenant that holds
obligations of the rule version, which a later change builds on the same tenant directory.

The consumer writes through Postgres, so the worker needs ``CW_OBLIGATION_STORE=postgres``. The
outbox relay that publishes the obligation events runs on its own
(``make relay SERVICE=obligation``).
"""

from collections.abc import Callable

from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from cw_contracts.events.applicability_decided_v1 import ApplicabilityDecidedV1
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.predicates import Applicability
from obligation import __version__
from obligation.application.decisions import ApplyDecision, Decision
from obligation.application.reminders import SendDueReminders
from obligation.domain.ports import RuleVersionReader
from obligation.domain.repository import UnitOfWorkFactory
from obligation.infrastructure.repository import PostgresTenantDirectory, PostgresUnitOfWorkFactory
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from obligation.settings import ObligationSettings
from py_common.auth import service_auth_from
from py_common.events import EventMessage
from py_common.logging import get_logger
from py_common.outbox import sync_handler
from py_common.outbox.sync import SyncHandler
from py_common.runtime import (
    ConsumerComponent,
    PeriodicComponent,
    WorkerComponents,
    run_worker_process,
)

GROUP_ID = "obligation.decisions"
DECIDED_TOPIC = "applicability.decided"
TOPICS = (DECIDED_TOPIC,)
SWEEP_JOB = "obligation-reminder-sweep"
SERVICE_NAME = "obligation-worker"

log = get_logger(__name__)

UnitsOnConnection = Callable[[Connection], UnitOfWorkFactory]
"""Units of work inside the transaction the connection has begun."""


class MissingTenantError(ValueError):
    """An applicability decision without the tenant it belongs to."""


def decision_from(message: EventMessage) -> Decision:
    """The decision an applicability.decided message carries; a payload its contract refuses,
    or a message without its tenant, raises."""
    if message.tenant_id is None:
        raise MissingTenantError(f"{message.topic} event {message.event_id} carries no tenant")
    payload = ApplicabilityDecidedV1.model_validate(message.payload)
    return Decision(
        tenant_id=TenantId(message.tenant_id),
        decision_id=DecisionId(payload.decision_id),
        business_id=BusinessId(payload.business_id),
        rule_version_id=RuleVersionId(payload.rule_version_id),
        result=Applicability(payload.result.value),
        needs_review=payload.needs_review,
        decided_at=payload.decided_at,
    )


def decision_handler(
    rules: RuleVersionReader,
    *,
    units_on: UnitsOnConnection = PostgresUnitOfWorkFactory.on_connection,
) -> SyncHandler:
    """The handler of applicability.decided: apply each decision on the consumer's connection.
    ``units_on`` makes the units there; tests pass the memory store's."""

    def handle(message: EventMessage, connection: Connection) -> None:
        if message.topic != DECIDED_TOPIC:
            log.info(
                "obligation.event_ignored", topic=message.topic, event_id=str(message.event_id)
            )
            return
        decision = decision_from(message)
        applied = ApplyDecision(units_on(connection), rules).run(decision)
        log.info(
            "obligation.decision_applied",
            event_id=str(message.event_id),
            decision_id=str(decision.decision_id),
            outcome=applied.outcome.value,
            created=len(applied.created),
            closed=len(applied.closed),
        )

    return handle


def sweep_job(sweep: SendDueReminders) -> Callable[[], None]:
    """One reminder sweep, logged with what it published."""

    def run() -> None:
        swept = sweep.run()
        log.info(
            "obligation.reminders_swept",
            tenants=swept.tenants,
            reminded=len(swept.reminded),
            failed=len(swept.failed),
        )

    return run


def _sweep_failed(tenant_id: TenantId, exc: Exception) -> None:
    log.error(
        "obligation.reminder_sweep_failed",
        tenant_id=str(tenant_id),
        error=f"{type(exc).__name__}: {exc}",
        exc_info=exc,
    )


def components(
    settings: ObligationSettings, *, rules: RuleVersionReader | None = None
) -> WorkerComponents:
    """The decision consumer and, when ``CW_OBLIGATION_SWEEP_ENABLED`` is on, the reminder
    sweep; ``rules`` replaces the rulebook reader."""
    if settings.obligation_store != "postgres":
        raise ValueError("the obligation worker needs CW_OBLIGATION_STORE=postgres")
    reader = rules or HttpRuleVersionReader(settings.rulebook_url, auth=service_auth_from(settings))
    periodic: tuple[PeriodicComponent, ...] = ()
    if settings.obligation_sweep_enabled:
        engine = create_engine(settings.database_url, poolclass=NullPool)
        sweep = SendDueReminders(
            PostgresUnitOfWorkFactory(engine),
            PostgresTenantDirectory(engine),
            on_failure=_sweep_failed,
        )
        periodic = (
            PeriodicComponent(
                SWEEP_JOB,
                sweep_job(sweep),
                interval_seconds=settings.obligation_sweep_interval_seconds,
            ),
        )
    return WorkerComponents(
        consumers=(
            ConsumerComponent(
                group_id=GROUP_ID, topics=TOPICS, handler=sync_handler(decision_handler(reader))
            ),
        ),
        periodic=periodic,
    )


def main() -> None:
    run_worker_process(
        ObligationSettings(service_name=SERVICE_NAME), components, version=__version__
    )


if __name__ == "__main__":
    main()
