"""The engine's erasure consumer on the memory store: with the flag on it deletes the tenant's
review items, decisions and directory entries, keeps the rule-level fan-out runs, and answers
tenant.data.erased; off, it only logs. The handler runs through a consumer on a SQLite inbox, as
the worker runs it; tests/integration/test_erasure_postgres.py runs the Postgres eraser."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.domain.review import ReviewItem, ReviewReason
from applicability_engine.infrastructure.erasure import MemoryEngineEraser
from applicability_engine.infrastructure.memory import MemoryStore
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.erasure import TenantDataErased
from domain_kernel.ids import BusinessId, DecisionId, EventId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from py_common.erasure import erasure_component
from py_common.erasure_testing import FakeIdentity
from py_common.events import EventMessage, encode
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    processed_event,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer

SENT = EventId(UUID("a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d"))
START = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)

REGULAR = Predicate("registration_type", Operator.EQ, "regular")


def decision(tenant: TenantId, minutes: int, *, unsure: bool) -> Decision:
    result = Applicability.UNSURE if unsure else Applicability.APPLIES
    return Decision(
        decision_id=DecisionId.new(),
        tenant_id=tenant,
        business_id=BusinessId.new(),
        rule_version_id=RuleVersionId.new(),
        result=result,
        confidence=ZERO if unsure else CERTAIN,
        evaluated=(PredicateResult(REGULAR, result, ZERO if unsure else CERTAIN, "synthetic"),),
        profile_version=1,
        decided_at=START + timedelta(minutes=minutes),
        trigger=Trigger.PROFILE_UPDATED,
        as_of_fy=None,
    )


def keep(factory: UnitOfWorkFactory, tenant: TenantId, count: int) -> None:
    """``count`` decisions of the tenant, every other one unsure with its open review item, and
    a directory entry per business."""
    with factory(tenant) as uow:
        for index in range(count):
            made = decision(tenant, index, unsure=bool(index % 2))
            uow.decisions.add(made)
            uow.directory.add(
                DirectoryEntry(
                    tenant, made.business_id, AttributeLevel.ENTITY, None, made.business_id
                )
            )
            if index % 2:
                uow.reviews.add(ReviewItem.open(made, ReviewReason.FREE_TEXT))


def deletion(tenant: TenantId) -> InboundRecord:
    message = EventMessage.model_validate(
        {
            "event_id": str(SENT),
            "topic": "tenant.deletion.requested",
            "schema_version": "1.0.1",
            "occurred_at": START.isoformat(),
            "tenant_id": str(tenant),
            "correlation_id": "c2d3e4f5-a6b7-4c8d-8e9f-0a1b2c3d4e5f",
            "causation_id": None,
            "payload": {
                "requested_by": None,
                "requested_at": START.isoformat(),
                "deadline_at": (START + timedelta(days=30)).isoformat(),
                "retain_audit": True,
            },
        }
    )
    return InboundRecord(
        topic=message.topic, partition=0, offset=0, key=b"k", value=encode(message)
    )


def consume(
    store: MemoryStore,
    tenant: TenantId,
    tmp_path: Path,
    *,
    on: bool,
    identity: FakeIdentity | None = None,
) -> Outcome:
    component = erasure_component(
        "applicability-engine",
        lambda _: MemoryEngineEraser(store),
        enabled=lambda _: on,
        verifier=identity or FakeIdentity(SENT),
        clock=lambda: START,
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    consumer = IdempotentConsumer(
        group_id=component.group_id,
        store=read_first_store(engine, component.group_id),
        handler=component.handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    return asyncio.run(consumer.process(deletion(tenant)))


def rows_of(store: MemoryStore, tenant: TenantId) -> int:
    return (
        sum(d.tenant_id == tenant for d in store.decisions.values())
        + sum(item.tenant_id == tenant for item in store.reviews.values())
        + sum(entry.tenant_id == tenant for entry in store.directory.values())
    )


def test_with_the_flag_on_the_tenant_s_decisions_go(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant, other = TenantId.new(), TenantId.new()
    keep(store, tenant, 4)
    keep(store, other, 3)
    theirs = rows_of(store, other)
    assert consume(store, tenant, tmp_path, on=True) is Outcome.PROCESSED
    assert rows_of(store, tenant) == 0
    assert rows_of(store, other) == theirs
    (answer,) = [e for e in store.events if isinstance(e, TenantDataErased)]
    assert (answer.service, answer.tenant_id) == ("applicability-engine", tenant)
    assert (answer.tables["applicability_decision"], answer.tables["review_item"]) == (4, 2)
    assert answer.tables["business_directory"] == 4
    assert [item.table for item in answer.retained] == [
        "fanout_run",
        "fanout_hold",
        "erased_tenant",
        "outbox_event",
    ]
    (entry,) = [e for e in store.audit if e.action == "tenant.erased"]
    assert entry.actor.label == "system:applicability-engine"
    assert store.erased.is_erased(tenant)


def test_an_event_identity_did_not_send_erases_nothing(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant = TenantId.new()
    keep(store, tenant, 2)
    before = rows_of(store, tenant)
    identity = FakeIdentity(SENT, status="active")
    assert consume(store, tenant, tmp_path, on=True, identity=identity) is Outcome.REFUSED
    assert rows_of(store, tenant) == before
    assert not store.erased.is_erased(tenant)


def test_with_the_flag_off_it_only_logs(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant = TenantId.new()
    keep(store, tenant, 2)
    before = rows_of(store, tenant)
    assert consume(store, tenant, tmp_path, on=False) is Outcome.PROCESSED
    assert rows_of(store, tenant) == before
