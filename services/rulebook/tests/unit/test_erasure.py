"""The rulebook's erasure consumer: the rulebook holds regulatory data, and the one table that
names a tenant is the review of its error reports, so with the flag on it nulls the tenant and
empties the text of the tenant's reviews, keeps their decisions, counts the outbox rows it prunes
(none on the memory store), lists what it keeps, and answers tenant.data.erased with its audit
entry, so the deletion request can complete; off, it only logs.
tests/integration/test_erasure_postgres.py runs the Postgres eraser, where the prune has rows."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.erasure import TenantDataErased
from domain_kernel.events import DomainEvent
from domain_kernel.ids import EventId, ObligationId, RuleVersionId, TenantId, UserId
from py_common.erasure import erasure_component
from py_common.erasure_testing import FakeIdentity
from py_common.events import EventMessage, encode, payload_of
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    processed_event,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer
from rulebook.domain.error_reports import (
    ErrorCategory,
    ErrorOutcome,
    ErrorReview,
    review_id_for,
)
from rulebook.infrastructure.erasure import MemoryRulebookEraser
from rulebook.infrastructure.memory import MemoryKnowledgeStore

SENT = EventId(UUID("a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d"))
NOW = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)


def consume(
    store: MemoryKnowledgeStore,
    outbox: list[DomainEvent],
    tenant: TenantId,
    path: Path,
    *,
    on: bool,
    identity: FakeIdentity | None = None,
) -> Outcome:
    component = erasure_component(
        "rulebook",
        lambda _: MemoryRulebookEraser(store, outbox),
        enabled=lambda _: on,
        verifier=identity or FakeIdentity(SENT),
        clock=lambda: NOW,
    )
    engine = create_engine(f"sqlite:///{path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    consumer = IdempotentConsumer(
        group_id=component.group_id,
        store=read_first_store(engine, component.group_id),
        handler=component.handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    message = EventMessage.model_validate(
        {
            "event_id": str(SENT),
            "topic": "tenant.deletion.requested",
            "schema_version": "1.0.1",
            "occurred_at": NOW.isoformat(),
            "tenant_id": str(tenant),
            "correlation_id": "c2d3e4f5-a6b7-4c8d-8e9f-0a1b2c3d4e5f",
            "causation_id": None,
            "payload": {
                "requested_by": None,
                "requested_at": NOW.isoformat(),
                "deadline_at": (NOW + timedelta(days=30)).isoformat(),
                "retain_audit": True,
            },
        }
    )
    record = InboundRecord(
        topic=message.topic, partition=0, offset=0, key=b"k", value=encode(message)
    )
    return asyncio.run(consumer.process(record))


def test_with_the_flag_on_it_answers_with_what_it_keeps(tmp_path: Path) -> None:
    store, outbox = MemoryKnowledgeStore(), list[DomainEvent]()
    tenant = TenantId.new()
    assert consume(store, outbox, tenant, tmp_path, on=True) is Outcome.PROCESSED
    (answer,) = outbox
    assert isinstance(answer, TenantDataErased)
    assert (answer.service, answer.tenant_id, dict(answer.tables)) == (
        "rulebook",
        tenant,
        {"error_report_review": 0, "outbox_event": 0},
    )
    payload = payload_of(answer)
    kept = {item["table"] for item in payload["retained"]}
    assert {"rule_candidate", "review_task", "rule_version_decision"} <= kept
    assert {"erased_tenant", "outbox_event"} <= kept
    assert all("no tenant" in item["reason"] for item in payload["retained"][:-2])
    (entry,) = store.audit_entries("tenant.erased")
    assert (entry.tenant_id, entry.actor.label) == (tenant, "system:rulebook")


def test_an_event_identity_did_not_send_is_refused(tmp_path: Path) -> None:
    store, outbox = MemoryKnowledgeStore(), list[DomainEvent]()
    tenant = TenantId.new()
    identity = FakeIdentity(SENT, internal=True)
    refused = consume(store, outbox, tenant, tmp_path, on=True, identity=identity)
    assert refused is Outcome.REFUSED
    assert outbox == []
    (entry,) = store.audit_entries("tenant.erasure_refused")
    assert entry.after is not None
    assert entry.after["refused"] == "the internal tenant is never erased"


def test_with_the_flag_off_it_only_logs(tmp_path: Path) -> None:
    store, outbox = MemoryKnowledgeStore(), list[DomainEvent]()
    assert consume(store, outbox, TenantId.new(), tmp_path, on=False) is Outcome.PROCESSED
    assert outbox == []
    assert store.audit_entries("tenant.erased") == []


def review_of(tenant: TenantId, version: RuleVersionId, text: str) -> ErrorReview:
    report_id = uuid4()
    return ErrorReview(
        review_id=review_id_for(report_id),
        report_id=report_id,
        tenant_id=tenant,
        obligation_id=ObligationId.new(),
        rule_version_id=version,
        category=ErrorCategory.DUE_DATE,
        description_masked=text,
        received_at=NOW,
    )


def test_with_the_flag_on_the_tenants_reviews_lose_their_tenant_and_text(tmp_path: Path) -> None:
    store, outbox = MemoryKnowledgeStore(), list[DomainEvent]()
    tenant, other = TenantId.new(), TenantId.new()
    _, version = store.add_rule("gstr3b_monthly", title="Monthly return (synthetic)")
    ours = review_of(tenant, version, "Example: the due date reads the 20th; call [PHONE].")
    theirs = review_of(other, version, "Example: the step list names a form we do not file.")
    with store() as uow:
        uow.error_reviews.add(ours)
        uow.error_reviews.add(theirs)
    decided = ours.decide(ErrorOutcome.REJECTED, by=UserId(UUID(int=41)), at=NOW, notes="n")
    with store() as uow:
        uow.error_reviews.save(decided)

    assert consume(store, outbox, tenant, tmp_path, on=True) is Outcome.PROCESSED

    (answer,) = outbox
    assert isinstance(answer, TenantDataErased)
    assert dict(answer.tables) == {"error_report_review": 1, "outbox_event": 0}
    by_report = {review.report_id: review for review in store.error_reviews()}
    erased = by_report[ours.report_id]
    assert (erased.tenant_id, erased.description_masked) == (None, "")
    assert (erased.status, erased.decided_by, erased.notes) == (
        decided.status,
        decided.decided_by,
        "n",
    ), "the decision stays as a fact about the rule"
    assert by_report[theirs.report_id] == theirs, "the other tenant's review is untouched"
