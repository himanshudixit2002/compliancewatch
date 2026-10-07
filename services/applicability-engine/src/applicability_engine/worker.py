"""The applicability-engine worker: ``python -m applicability_engine.worker``, locally
``make worker SERVICE=applicability-engine``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what a
process that hosts several services adds to its own: two consumers and a Temporal worker.

The consumer in group ``applicability-engine.profiles`` of profile.updated: each event becomes
``ApplyProfileUpdate`` in two steps, so no HTTP call is made inside a database transaction
(``py_common.outbox.sync.read_then_write``):

- the reads, with no transaction open: the changed node's snapshot and the registrations under
  it at the profile service (``CW_PROFILE_URL``) and, with ``CW_APPLICABILITY_RECOMPUTE_ENABLED``
  (flag ``applicability.recompute``, off by default), the snapshots and the rule versions in
  force, or superseded but still governing a period due, at the rulebook (``CW_RULEBOOK_URL``),
  evaluated there;
- the writes, on units of work in the consumer's own transaction
  (``PostgresUnitOfWorkFactory.on_connection``): the business directory, the decisions with
  their applicability.decided outbox rows, the review items and the ``processed_event`` row
  commit together, so a redelivered event changes nothing twice, and a replayed one stores
  nothing new either (decision ids derive from the event).

With the flag off the consumer still keeps the business directory, and evaluates nothing. A
message the handler cannot read, or an event whose reads fail after the consumer's retries,
goes to ``profile.updated.applicability-engine.profiles.dlq``.

The consumer in group ``applicability-engine.rules`` of rule.published and rule.withdrawn
(``application.rule_events``), with the same inbox pattern: the reads first, with no transaction
open (the version at the rulebook and, with ``CW_APPLICABILITY_FANOUT_ENABLED``, flag
``applicability.fanout``, the start of its fan-out workflow; both events also drop the cached
listing of the versions in force), then the run's row in the consumer's transaction. With the flag
off a publication records a ``disabled`` run and starts nothing. A withdrawal cancels the run of
its version that has not finished. A message it cannot handle goes to
``<topic>.applicability-engine.rules.dlq``.

The consumer in group ``applicability-engine.erasure`` of ``tenant.deletion.requested``
(``py_common.erasure``): while the flag ``identity.tenant_erasure`` is off for the tenant it only
logs ``erasure.off``; on, it deletes the tenant's review items, decisions, directory entries,
idempotency keys and published events (``infrastructure.erasure.PostgresEngineEraser``), keeps
the rule-level fan-out runs, and writes ``tenant.data.erased`` (service applicability-engine) and
its ``tenant.erased`` audit entry with the ``processed_event`` row.

The Temporal worker on task queue ``applicability`` runs ``FanOutWorkflow`` and its activities
(``application.fanout_activities``) on the same stores and readers.

The consumers and the activities write through Postgres, so the worker needs
``CW_APPLICABILITY_ENGINE_STORE=postgres``. The outbox relay that publishes the decisions runs on
its own (``make relay SERVICE=applicability-engine``), or in the combined worker.
"""

from collections.abc import Callable
from typing import Any, Final

from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from applicability_engine import __version__
from applicability_engine.application.fanout_activities import fanout_activities
from applicability_engine.application.recompute import (
    ApplyProfileUpdate,
    ProfileUpdate,
    Recomputed,
    RecomputePlan,
)
from applicability_engine.application.rule_events import (
    RuleEvents,
    RulePlan,
    RulePublished,
    RuleWithdrawn,
)
from applicability_engine.domain.fanout import FAN_OUT_TASK_QUEUE, FanOutRun
from applicability_engine.domain.ports import FanOutWorkflows
from applicability_engine.domain.repository import FanOutUnitOfWorkFactory, UnitOfWorkFactory
from applicability_engine.infrastructure.erasure import PostgresEngineEraser
from applicability_engine.infrastructure.repository import (
    PostgresBusinessDirectory,
    PostgresFanOutUnitOfWorkFactory,
    PostgresUnitOfWorkFactory,
)
from applicability_engine.infrastructure.temporal import TemporalFanOuts
from applicability_engine.main import http_readers
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.wiring import Readers
from applicability_engine.workflows import FanOutWorkflow
from cw_contracts.events.profile_updated_v1 import ProfileUpdatedV1
from cw_contracts.events.rule_published_v1 import RulePublishedV1
from cw_contracts.events.rule_withdrawn_v1 import RuleWithdrawnV1
from domain_kernel.ids import BusinessId, CorrelationId, EventId, RuleVersionId, TenantId
from domain_kernel.ontology import Ontology
from ontology import load as load_ontology
from py_common.erasure import Enabled, ErasureSwitch, erasure_component
from py_common.events import EventMessage
from py_common.logging import get_logger
from py_common.outbox import read_first_store, read_then_write
from py_common.outbox.consumer import Handler
from py_common.runtime import (
    ConsumerComponent,
    TemporalComponent,
    WorkerComponents,
    run_worker_process,
)
from py_common.temporal import WorkerConfig

GROUP_ID: Final = "applicability-engine.profiles"
PROFILE_TOPIC: Final = "profile.updated"
TOPICS: Final = (PROFILE_TOPIC,)
RULES_GROUP_ID: Final = "applicability-engine.rules"
PUBLISHED_TOPIC: Final = "rule.published"
WITHDRAWN_TOPIC: Final = "rule.withdrawn"
RULE_TOPICS: Final = (PUBLISHED_TOPIC, WITHDRAWN_TOPIC)
SERVICE_NAME: Final = "applicability-engine-worker"
ERASURE_SERVICE: Final = "applicability-engine"

log = get_logger(__name__)

UnitsOnConnection = Callable[[Connection], UnitOfWorkFactory]
"""Units of work inside the consumer's transaction on the connection."""
FanOutUnitsOnConnection = Callable[[Connection], FanOutUnitOfWorkFactory]
"""Fan-out units inside the consumer's transaction on the connection."""


class MissingTenantError(ValueError):
    """A profile.updated event without the tenant it belongs to."""


def update_from(message: EventMessage) -> ProfileUpdate:
    """The profile change a profile.updated message carries; a payload its contract refuses, or
    a message without its tenant, raises."""
    if message.tenant_id is None:
        raise MissingTenantError(f"{message.topic} event {message.event_id} carries no tenant")
    payload = ProfileUpdatedV1.model_validate(message.payload)
    return ProfileUpdate(
        tenant_id=TenantId(message.tenant_id),
        event_id=EventId(message.event_id),
        business_id=BusinessId(payload.business_id),
        profile_version=payload.profile_version,
        changed_attributes=tuple(attribute.root for attribute in payload.changed_attributes),
        correlation_id=CorrelationId(message.correlation_id),
    )


def profile_handler(
    recompute: ApplyProfileUpdate,
    *,
    units_on: UnitsOnConnection = PostgresUnitOfWorkFactory.on_connection,
) -> Handler:
    """The handler of profile.updated: read with no transaction open, then write on the
    consumer's connection. ``units_on`` makes the units there; tests pass the memory store's."""

    def read(message: EventMessage) -> RecomputePlan | None:
        if message.topic != PROFILE_TOPIC:
            log.info(
                "applicability.event_ignored", topic=message.topic, event_id=str(message.event_id)
            )
            return None
        return recompute.plan(update_from(message))

    def write(message: EventMessage, plan: RecomputePlan | None, connection: Connection) -> None:
        if plan is None:
            return
        done = recompute.apply(plan, units_on(connection))
        _log_recomputed(message, done)

    return read_then_write(read, write)


def _log_recomputed(message: EventMessage, done: Recomputed) -> None:
    plan = done.plan
    log.info(
        "applicability.profile_recomputed",
        event_id=str(message.event_id),
        tenant_id=str(plan.update.tenant_id),
        business_id=str(plan.update.business_id),
        found=plan.found,
        evaluated=plan.evaluated,
        nodes=len(plan.directory),
        listed=done.listed,
        decided=len(done.appended),
        published=len(done.published),
        reviews={change.value: count for change, count in done.reviews.items()},
    )


def recompute_of(
    settings: ApplicabilityEngineSettings,
    readers: Readers | None = None,
    ontology: Ontology | None = None,
) -> ApplyProfileUpdate:
    """The recompute the settings describe, reading over HTTP unless ``readers`` are given."""
    readers = readers or http_readers(settings)
    return ApplyProfileUpdate(
        readers.profiles,
        readers.rulebook,
        ontology or load_ontology(),
        enabled=settings.applicability_recompute_enabled,
        lookahead_days=settings.applicability_engine_recompute_lookahead_days,
        superseded_lookback_days=settings.applicability_engine_superseded_lookback_days,
    )


def published_from(message: EventMessage) -> RulePublished:
    """The publication a rule.published message carries; a payload its contract refuses
    raises."""
    payload = RulePublishedV1.model_validate(message.payload)
    return RulePublished(
        event_id=EventId(message.event_id),
        rule_version_id=RuleVersionId(payload.rule_version_id),
        supersedes=tuple(RuleVersionId(item) for item in payload.supersedes),
        correlation_id=CorrelationId(message.correlation_id),
    )


def withdrawn_from(message: EventMessage) -> RuleWithdrawn:
    """The withdrawal a rule.withdrawn message carries; a payload its contract refuses raises."""
    payload = RuleWithdrawnV1.model_validate(message.payload)
    return RuleWithdrawn(
        event_id=EventId(message.event_id),
        rule_version_id=RuleVersionId(payload.rule_version_id),
        correlation_id=CorrelationId(message.correlation_id),
    )


def rules_handler(
    events: RuleEvents,
    *,
    units_on: FanOutUnitsOnConnection = PostgresFanOutUnitOfWorkFactory.on_connection,
) -> Handler:
    """The handler of rule.published and rule.withdrawn: read (and start the workflow) with no
    transaction open, then write the run on the consumer's connection. ``units_on`` makes the
    fan-out units there; tests pass the memory store's."""

    def read(message: EventMessage) -> RulePlan | None:
        if message.topic == PUBLISHED_TOPIC:
            return events.plan_published(published_from(message))
        if message.topic == WITHDRAWN_TOPIC:
            return events.plan_withdrawn(withdrawn_from(message))
        log.info("applicability.event_ignored", topic=message.topic, event_id=str(message.event_id))
        return None

    def write(message: EventMessage, plan: RulePlan | None, connection: Connection) -> None:
        if plan is None:
            return
        run = events.apply(plan, units_on(connection))
        _log_rule_event(message, plan, run)

    return read_then_write(read, write)


def _log_rule_event(message: EventMessage, plan: RulePlan, run: FanOutRun | None) -> None:
    subject = plan.published or plan.withdrawn
    log.info(
        "applicability.rule_event",
        topic=message.topic,
        event_id=str(message.event_id),
        rule_version_id=None if subject is None else str(subject.rule_version_id),
        run_status=None if run is None else run.status.value,
        started=plan.started,
        disabled=plan.disabled,
        skipped=plan.skipped or None,
    )


def rule_events_of(
    settings: ApplicabilityEngineSettings,
    readers: Readers,
    workflows: FanOutWorkflows | None = None,
) -> RuleEvents:
    """The rule events handling the settings describe: Temporal unless ``workflows`` is given."""
    return RuleEvents(
        readers.rulebook,
        workflows or TemporalFanOuts(settings),
        enabled=settings.applicability_fanout_enabled,
    )


def components(
    settings: ApplicabilityEngineSettings,
    *,
    readers: Readers | None = None,
    workflows: FanOutWorkflows | None = None,
    ontology: Ontology | None = None,
    erasure: Enabled | None = None,
) -> WorkerComponents:
    """The three consumers and the fan-out's Temporal worker; ``readers`` replaces the profile
    and rulebook clients, ``workflows`` the Temporal client that starts fan-outs and ``erasure``
    the flag of the erasure consumer. The profile and rule consumers share the readers, so a
    rule event drops the listing the recompute caches."""
    if settings.applicability_engine_store != "postgres":
        raise ValueError(
            "the applicability-engine worker needs CW_APPLICABILITY_ENGINE_STORE=postgres"
        )
    readers = readers or http_readers(settings)
    ontology = ontology or load_ontology()
    recompute = recompute_of(settings, readers, ontology)
    engine = create_engine(settings.database_url, poolclass=NullPool)
    activities: list[Any] = fanout_activities(
        fanouts=PostgresFanOutUnitOfWorkFactory(engine),
        directory=PostgresBusinessDirectory(engine),
        unit_of_work=PostgresUnitOfWorkFactory(engine),
        profiles=readers.profiles,
        rulebook=readers.rulebook,
        ontology=ontology,
    )
    return WorkerComponents(
        consumers=(
            ConsumerComponent(
                group_id=GROUP_ID,
                topics=TOPICS,
                handler=profile_handler(recompute),
                store_factory=read_first_store,
            ),
            ConsumerComponent(
                group_id=RULES_GROUP_ID,
                topics=RULE_TOPICS,
                handler=rules_handler(rule_events_of(settings, readers, workflows)),
                store_factory=read_first_store,
            ),
            erasure_component(
                ERASURE_SERVICE, PostgresEngineEraser, enabled=erasure or ErasureSwitch(settings)
            ),
        ),
        temporal=(
            TemporalComponent(
                WorkerConfig(task_queue=FAN_OUT_TASK_QUEUE), (FanOutWorkflow,), activities
            ),
        ),
    )


def main() -> None:
    run_worker_process(
        ApplicabilityEngineSettings(service_name=SERVICE_NAME), components, version=__version__
    )


if __name__ == "__main__":
    main()
