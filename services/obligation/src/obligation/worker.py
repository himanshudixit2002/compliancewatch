"""The obligation worker: ``python -m obligation.worker``, locally
``make worker SERVICE=obligation``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what a
process that hosts several services adds to its own:

- a consumer in group ``obligation.decisions`` of applicability.decided, in two steps
  (``py_common.outbox.read_then_write``): ``ApplyDecision.plan`` reads the rule version of a
  decision that applies, with no transaction open, and ``ApplyDecision.apply`` writes on units of
  work that join the consumer's own transaction (``PostgresUnitOfWorkFactory.on_connection``), so
  the obligations, their outbox and change rows, the cached rule version, the applied decision and
  the ``processed_event`` row commit together and a redelivered decision changes nothing twice.
  ``applies`` materialises the obligations of the business and the rule version, read from the
  rulebook at ``CW_RULEBOOK_URL``, unless the guard refuses (a withdrawn version, one without a
  verified citation, or the periods a superseded one no longer governs: each logged as
  ``obligation.decision_guarded`` and counted in ``obligation_guard_refusals_total``);
  ``not_applicable`` closes the open ones with ``profile_changed``; a decision that needs review is
  only marked processed. A message the handler cannot read, or whose rule version the rulebook
  cannot give, goes to ``applicability.decided.obligation.decisions.dlq`` after the retries. A
  decision of a tenant the service has erased writes nothing and is only marked processed
  (``py_common.erasure.skip_erased_write``, outcome ``erased_tenant``).
- a consumer in group ``obligation.rules`` of rule.published, rule.superseded, rule.withdrawn and
  rule.deadline_changed (``application.rule_events``), with the same two steps: a fresh read of
  the version, then the cache and one unit of work per tenant of the ``obligation_tenant``
  directory, every one on the consumer's connection, each setting its own tenant so row-level
  security holds, all committing with the ``processed_event`` row. With
  ``CW_OBLIGATION_RULE_EVENTS_ENABLED`` (flag ``obligation.rule_events``) off it still consumes,
  so its offsets keep up, and changes nothing. What it cannot handle goes to
  ``<topic>.obligation.rules.dlq``.
- a consumer in group ``obligation.erasure`` of ``tenant.deletion.requested``
  (``py_common.erasure``): while the flag ``identity.tenant_erasure`` is off for the tenant it
  only logs ``erasure.off``; on, it checks the event with identity (one identity did not send is
  refused, audited and dead-lettered), then deletes the tenant's obligations with their changes,
  comments and reminders, its applied decisions, its directory entry, idempotency keys and
  published events (``infrastructure.erasure.PostgresObligationEraser``), keeps the rule-level
  cache of rule versions, and writes ``tenant.data.erased`` (service obligation), its
  ``tenant.erased`` audit entry and the erased marker with the ``processed_event`` row.
- with ``CW_OBLIGATION_SWEEP_ENABLED`` on (off by default), the reminder sweep,
  ``SendDueReminders.run``, every ``CW_OBLIGATION_SWEEP_INTERVAL_SECONDS`` (an hour), and the
  rolling window, ``RollWindow.run``, daily at 02:30 IST, both one tenant at a time through the
  ``obligation_tenant`` directory. ``obligation-sweep --once`` (``obligation.sweep``) runs both
  once.

Both consumers share one rulebook reader, so a rule event's fresh read reaches the decision
consumer of the same process at once. The consumers write through Postgres, so the worker needs
``CW_OBLIGATION_STORE=postgres``. The outbox relay that publishes the obligation events runs on
its own (``make relay SERVICE=obligation``).
"""

from collections.abc import Callable
from datetime import time
from typing import Final

from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from cw_contracts.events.applicability_decided_v1 import ApplicabilityDecidedV1
from cw_contracts.events.rule_deadline_changed_v1 import RuleDeadlineChangedV1
from cw_contracts.events.rule_published_v1 import RulePublishedV1
from cw_contracts.events.rule_superseded_v1 import RuleSupersededV1
from cw_contracts.events.rule_withdrawn_v1 import RuleWithdrawnV1
from domain_kernel.ids import BusinessId, DecisionId, EventId, RuleVersionId, TenantId
from domain_kernel.predicates import Applicability
from obligation import __version__
from obligation.application.decisions import ApplyDecision, Decision, DecisionApplied, DecisionPlan
from obligation.application.reminders import SendDueReminders
from obligation.application.rule_events import (
    RuleDeadlineChanged,
    RuleEvent,
    RuleEvents,
    RulePlan,
    RulePublished,
    RuleSuperseded,
    RuleWithdrawn,
)
from obligation.application.window import RollWindow
from obligation.domain.events import RescheduleReason
from obligation.domain.ports import RuleVersionReader
from obligation.domain.repository import RuleVersionRefs, TenantDirectory, UnitOfWorkFactory
from obligation.infrastructure.erasure import PostgresObligationEraser
from obligation.infrastructure.metrics import GuardMetrics
from obligation.infrastructure.repository import (
    ConnectionTenantDirectory,
    PostgresTenantDirectory,
    PostgresUnitOfWorkFactory,
    SqlAlchemyRuleVersionRefs,
)
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from obligation.settings import ObligationSettings
from py_common.auth import service_auth_from
from py_common.erasure import (
    Enabled,
    ErasedOn,
    ErasureVerifier,
    erased_on_connection,
    erasure_component,
    erasure_switch,
    skip_erased_write,
    verifier_from,
)
from py_common.events import EventMessage
from py_common.logging import get_logger
from py_common.outbox import read_first_store, read_then_write
from py_common.outbox.consumer import Handler
from py_common.runtime import (
    IST,
    ConsumerComponent,
    PeriodicComponent,
    WorkerComponents,
    daily_at,
    run_worker_process,
)

GROUP_ID: Final = "obligation.decisions"
DECIDED_TOPIC: Final = "applicability.decided"
TOPICS: Final = (DECIDED_TOPIC,)
RULES_GROUP_ID: Final = "obligation.rules"
PUBLISHED_TOPIC: Final = "rule.published"
SUPERSEDED_TOPIC: Final = "rule.superseded"
WITHDRAWN_TOPIC: Final = "rule.withdrawn"
DEADLINE_TOPIC: Final = "rule.deadline_changed"
RULE_TOPICS: Final = (PUBLISHED_TOPIC, SUPERSEDED_TOPIC, WITHDRAWN_TOPIC, DEADLINE_TOPIC)
SWEEP_JOB: Final = "obligation-reminder-sweep"
WINDOW_JOB: Final = "obligation-window"
WINDOW_AT: Final = time(2, 30, tzinfo=IST)
"""02:30 IST: the day's periods are in the window before anyone looks at them."""
SERVICE_NAME: Final = "obligation-worker"
ERASURE_SERVICE: Final = "obligation"
DECISION_SOURCE: Final = "decision"
WINDOW_SOURCE: Final = "window"

log = get_logger(__name__)

UnitsOnConnection = Callable[[Connection], UnitOfWorkFactory]
"""Units of work inside the transaction the connection has begun."""
RefsOnConnection = Callable[[Connection], RuleVersionRefs]
"""The cached rule versions on the connection."""
TenantsOnConnection = Callable[[Connection], TenantDirectory]
"""The tenant directory read on the connection."""


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
        profile_version=payload.profile_version,
    )


def decision_handler(
    apply: ApplyDecision,
    *,
    units_on: UnitsOnConnection = PostgresUnitOfWorkFactory.on_connection,
    erased_on: ErasedOn = erased_on_connection,
    metrics: GuardMetrics | None = None,
) -> Handler:
    """The handler of applicability.decided: read with no transaction open, then write on the
    consumer's connection, unless the decision's tenant is erased here. ``units_on`` and
    ``erased_on`` make the units and the erased markers there; tests pass the memory store's."""
    counter = metrics or GuardMetrics()

    def read(message: EventMessage) -> DecisionPlan | None:
        if message.topic != DECIDED_TOPIC:
            log.info(
                "obligation.event_ignored", topic=message.topic, event_id=str(message.event_id)
            )
            return None
        return apply.plan(decision_from(message))

    def write(message: EventMessage, plan: DecisionPlan | None, connection: Connection) -> None:
        if plan is None:
            return
        applied = apply.apply(plan, units_on(connection))
        _log_decision(message, plan.decision, applied, counter)

    return read_then_write(read, skip_erased_write(ERASURE_SERVICE, write, erased_on=erased_on))


def _log_decision(
    message: EventMessage, decision: Decision, applied: DecisionApplied, counter: GuardMetrics
) -> None:
    log.info(
        "obligation.decision_applied",
        event_id=str(message.event_id),
        decision_id=str(decision.decision_id),
        outcome=applied.outcome.value,
        created=len(applied.created),
        closed=len(applied.closed),
    )
    if applied.refusal is None:
        return
    ref = applied.ref
    log.info(
        "obligation.decision_guarded",
        event_id=str(message.event_id),
        decision_id=str(decision.decision_id),
        tenant_id=str(decision.tenant_id),
        business_id=str(decision.business_id),
        rule_version_id=str(decision.rule_version_id),
        refusal=applied.refusal.value,
        refused_periods=list(applied.refused_periods),
        status=None if ref is None else ref.status.value,
        effective_to=None if ref is None or ref.effective_to is None else str(ref.effective_to),
        cached=applied.cached,
    )
    counter.refused(applied.refusal.value, DECISION_SOURCE, max(1, len(applied.refused_periods)))


def rule_event_from(message: EventMessage) -> RuleEvent | None:
    """The rule event a message carries; None for a topic the group does not act on. A payload
    its contract refuses raises."""
    event_id = EventId(message.event_id)
    if message.topic == PUBLISHED_TOPIC:
        published = RulePublishedV1.model_validate(message.payload)
        return RulePublished(event_id, RuleVersionId(published.rule_version_id))
    if message.topic == WITHDRAWN_TOPIC:
        withdrawn = RuleWithdrawnV1.model_validate(message.payload)
        return RuleWithdrawn(
            event_id, RuleVersionId(withdrawn.rule_version_id), withdrawn.effective_from
        )
    if message.topic == SUPERSEDED_TOPIC:
        superseded = RuleSupersededV1.model_validate(message.payload)
        return RuleSuperseded(
            event_id,
            RuleVersionId(superseded.rule_version_id),
            RuleVersionId(superseded.superseded_by_rule_version_id),
            superseded.effective_from,
        )
    if message.topic == DEADLINE_TOPIC:
        changed = RuleDeadlineChangedV1.model_validate(message.payload)
        return RuleDeadlineChanged(
            event_id,
            RuleVersionId(changed.rule_version_id),
            RuleVersionId(changed.caused_by_rule_version_id),
            changed.period_label,
            changed.new_due_on,
            RescheduleReason(changed.reason.value),
        )
    return None


def rules_handler(
    events: RuleEvents,
    *,
    units_on: UnitsOnConnection = PostgresUnitOfWorkFactory.on_connection,
    refs_on: RefsOnConnection = SqlAlchemyRuleVersionRefs,
    tenants_on: TenantsOnConnection = ConnectionTenantDirectory,
) -> Handler:
    """The handler of the rule events: read with no transaction open, then write the cache and
    every tenant's changes on the consumer's connection. The ``*_on`` factories make the stores
    there; tests pass the memory store's."""

    def read(message: EventMessage) -> RulePlan | None:
        event = rule_event_from(message)
        if event is None:
            log.info(
                "obligation.event_ignored", topic=message.topic, event_id=str(message.event_id)
            )
            return None
        plan = events.plan(event)
        if plan is None:
            log.info(
                "obligation.rule_event_off",
                topic=message.topic,
                event_id=str(message.event_id),
                rule_version_id=str(event.rule_version_id),
            )
        return plan

    def write(message: EventMessage, plan: RulePlan | None, connection: Connection) -> None:
        if plan is None:
            return
        done = events.apply(plan, units_on(connection), refs_on(connection), tenants_on(connection))
        cached = done.cached
        log.info(
            "obligation.rule_event",
            topic=message.topic,
            event_id=str(message.event_id),
            rule_version_id=str(plan.event.rule_version_id),
            tenants=done.tenants,
            changed=len(done.changed),
            unchanged=done.unchanged,
            status=None if cached is None else cached.status.value,
            effective_to=None
            if cached is None or cached.effective_to is None
            else str(cached.effective_to),
            unread=plan.unread or None,
        )

    return read_then_write(read, write)


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


def window_job(roll: RollWindow, metrics: GuardMetrics | None = None) -> Callable[[], None]:
    """One run of the rolling window, logged with what it made and what the guard refused."""
    counter = metrics or GuardMetrics()

    def run() -> None:
        rolled = roll.run()
        for reason, count in rolled.refused:
            counter.refused(reason.value, WINDOW_SOURCE, count)
        log.info(
            "obligation.window_rolled",
            tenants=rolled.tenants,
            created=len(rolled.created),
            refused={reason.value: count for reason, count in rolled.refused},
            failed=len(rolled.failed),
        )

    return run


def _sweep_failed(tenant_id: TenantId, exc: Exception) -> None:
    log.error(
        "obligation.reminder_sweep_failed",
        tenant_id=str(tenant_id),
        error=f"{type(exc).__name__}: {exc}",
        exc_info=exc,
    )


def _window_failed(tenant_id: TenantId, exc: Exception) -> None:
    log.error(
        "obligation.window_failed",
        tenant_id=str(tenant_id),
        error=f"{type(exc).__name__}: {exc}",
        exc_info=exc,
    )


def reader_of(settings: ObligationSettings) -> HttpRuleVersionReader:
    """The rulebook at ``CW_RULEBOOK_URL``, with the service's token when it has a secret."""
    return HttpRuleVersionReader(settings.rulebook_url, auth=service_auth_from(settings))


def components(
    settings: ObligationSettings,
    *,
    rules: RuleVersionReader | None = None,
    erasure: Enabled | None = None,
    verifier: ErasureVerifier | None = None,
) -> WorkerComponents:
    """The three consumers and, when ``CW_OBLIGATION_SWEEP_ENABLED`` is on, the reminder sweep
    and the rolling window; ``rules`` replaces the rulebook reader, ``erasure`` the flag of the
    erasure consumer and ``verifier`` identity's check."""
    if settings.obligation_store != "postgres":
        raise ValueError("the obligation worker needs CW_OBLIGATION_STORE=postgres")
    reader = rules or reader_of(settings)
    metrics = GuardMetrics()
    periodic: tuple[PeriodicComponent, ...] = ()
    if settings.obligation_sweep_enabled:
        engine = create_engine(settings.database_url, poolclass=NullPool)
        units = PostgresUnitOfWorkFactory(engine)
        directory = PostgresTenantDirectory(engine)
        sweep = SendDueReminders(units, directory, on_failure=_sweep_failed)
        roll = RollWindow(units, directory, reader, on_failure=_window_failed)
        periodic = (
            PeriodicComponent(
                SWEEP_JOB,
                sweep_job(sweep),
                interval_seconds=settings.obligation_sweep_interval_seconds,
            ),
            PeriodicComponent(WINDOW_JOB, window_job(roll, metrics), next_run=daily_at(WINDOW_AT)),
        )
    events = RuleEvents(reader, enabled=settings.obligation_rule_events_enabled)
    return WorkerComponents(
        consumers=(
            ConsumerComponent(
                group_id=GROUP_ID,
                topics=TOPICS,
                handler=decision_handler(ApplyDecision(reader), metrics=metrics),
                store_factory=read_first_store,
            ),
            ConsumerComponent(
                group_id=RULES_GROUP_ID,
                topics=RULE_TOPICS,
                handler=rules_handler(events),
                store_factory=read_first_store,
            ),
            erasure_component(
                ERASURE_SERVICE,
                PostgresObligationEraser,
                enabled=erasure or erasure_switch(settings),
                verifier=verifier or verifier_from(settings),
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
