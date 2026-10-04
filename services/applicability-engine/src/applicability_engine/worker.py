"""The applicability-engine worker: ``python -m applicability_engine.worker``, locally
``make worker SERVICE=applicability-engine``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what a
process that hosts several services adds to its own: a consumer in group
``applicability-engine.profiles`` of profile.updated. Each event becomes
``ApplyProfileUpdate`` in two steps, so no HTTP call is made inside a database transaction
(``py_common.outbox.sync.read_then_write``):

- the reads, with no transaction open: the changed node's snapshot and the registrations under
  it at the profile service (``CW_PROFILE_URL``) and, with ``CW_APPLICABILITY_RECOMPUTE_ENABLED``
  (flag ``applicability.recompute``, off by default), the snapshots and the rule versions in
  force at the rulebook (``CW_RULEBOOK_URL``), evaluated there;
- the writes, on units of work in the consumer's own transaction
  (``PostgresUnitOfWorkFactory.on_connection``): the business directory, the decisions with
  their applicability.decided outbox rows, the review items and the ``processed_event`` row
  commit together, so a redelivered event changes nothing twice, and a replayed one stores
  nothing new either (decision ids derive from the event).

With the flag off the consumer still keeps the business directory, and evaluates nothing. A
message the handler cannot read, or an event whose reads fail after the consumer's retries,
goes to ``profile.updated.applicability-engine.profiles.dlq``.

The consumer writes through Postgres, so the worker needs ``CW_APPLICABILITY_ENGINE_STORE=
postgres``. The outbox relay that publishes the decisions runs on its own
(``make relay SERVICE=applicability-engine``), or in the combined worker.
"""

from collections.abc import Callable
from typing import Final

from sqlalchemy import Connection

from applicability_engine import __version__
from applicability_engine.application.recompute import (
    ApplyProfileUpdate,
    ProfileUpdate,
    Recomputed,
    RecomputePlan,
)
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.infrastructure.repository import PostgresUnitOfWorkFactory
from applicability_engine.main import http_readers
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.wiring import Readers
from cw_contracts.events.profile_updated_v1 import ProfileUpdatedV1
from domain_kernel.ids import BusinessId, CorrelationId, EventId, TenantId
from domain_kernel.ontology import Ontology
from ontology import load as load_ontology
from py_common.events import EventMessage
from py_common.logging import get_logger
from py_common.outbox import read_first_store, read_then_write
from py_common.outbox.consumer import Handler
from py_common.runtime import ConsumerComponent, WorkerComponents, run_worker_process

GROUP_ID: Final = "applicability-engine.profiles"
PROFILE_TOPIC: Final = "profile.updated"
TOPICS: Final = (PROFILE_TOPIC,)
SERVICE_NAME: Final = "applicability-engine-worker"

log = get_logger(__name__)

UnitsOnConnection = Callable[[Connection], UnitOfWorkFactory]
"""Units of work inside the consumer's transaction on the connection."""


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
    )


def components(
    settings: ApplicabilityEngineSettings, *, readers: Readers | None = None
) -> WorkerComponents:
    """The profile.updated consumer; ``readers`` replaces the profile and rulebook clients."""
    if settings.applicability_engine_store != "postgres":
        raise ValueError(
            "the applicability-engine worker needs CW_APPLICABILITY_ENGINE_STORE=postgres"
        )
    recompute = recompute_of(settings, readers)
    return WorkerComponents(
        consumers=(
            ConsumerComponent(
                group_id=GROUP_ID,
                topics=TOPICS,
                handler=profile_handler(recompute),
                store_factory=read_first_store,
            ),
        ),
    )


def main() -> None:
    run_worker_process(
        ApplicabilityEngineSettings(service_name=SERVICE_NAME), components, version=__version__
    )


if __name__ == "__main__":
    main()
