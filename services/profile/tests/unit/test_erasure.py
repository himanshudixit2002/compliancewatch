"""Profile's erasure consumer on the memory store: with the flag on it deletes the tenant's
nodes, attributes, versions and review tasks, and answers tenant.data.erased with its audit
entry; off, it only logs. The handler runs through a consumer on a SQLite inbox, as the worker
runs it; tests/integration/test_erasure_postgres.py runs the Postgres eraser."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

import ontology as ontology_package
from domain_kernel.erasure import TenantDataErased
from domain_kernel.ids import TenantId
from profile_service.application.attributes import SetAttributes
from profile_service.application.registration import RegisterNodes
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ValueState
from profile_service.infrastructure.erasure import MemoryProfileEraser
from profile_service.infrastructure.memory import MemoryStore
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_KARNATAKA
from profile_service.worker import components
from py_common.erasure import erasure_component
from py_common.events import EventMessage, encode
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
)
from py_common.outbox.testing import FakeProducer

NOW = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)


def stocked(store: MemoryStore, tenant: TenantId, name: str) -> None:
    register = RegisterNodes(store, clock=lambda: NOW)
    registered = register.registration(
        tenant, GSTIN_KARNATAKA, f"{name} Bengaluru", entity_name=name
    )
    entity = registered.node.parent_id
    assert entity is not None
    SetAttributes(store, ontology_package.load(), clock=lambda: NOW).run(
        tenant,
        entity,
        [
            AttributeChange("state_codes", ["29"]),
            AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE),
        ],
        source=ChangeSource.USER_INPUT,
    )


def deletion(tenant: TenantId) -> bytes:
    return encode(
        EventMessage.model_validate(
            {
                "event_id": "a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d",
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
    )


def consume(store: MemoryStore, tenant: TenantId, tmp_path: Path, *, on: bool) -> Outcome:
    component = erasure_component(
        "profile", lambda _: MemoryProfileEraser(store), enabled=lambda _: on, clock=lambda: NOW
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    consumer = IdempotentConsumer(
        group_id=component.group_id,
        store=SyncProcessedStore(engine, group_id=component.group_id),
        handler=component.handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    record = InboundRecord(
        topic="tenant.deletion.requested", partition=0, offset=0, key=b"k", value=deletion(tenant)
    )
    return asyncio.run(consumer.process(record))


def rows_of(store: MemoryStore, tenant: TenantId) -> int:
    return (
        sum(node.tenant_id == tenant for node in store.nodes.values())
        + sum(task.tenant_id == tenant for task in store.tasks.values())
        + sum(version.tenant_id == tenant for version in store.versions.values())
        + sum(case.get("tenant_id") == str(tenant) for case in store.eval_cases)
    )


def test_with_the_flag_on_the_tenant_s_profile_goes(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant, other = TenantId.new(), TenantId.new()
    stocked(store, tenant, "Example Traders")
    stocked(store, other, "Example Other")
    assert rows_of(store, tenant) > 0
    assert consume(store, tenant, tmp_path, on=True) is Outcome.PROCESSED
    assert rows_of(store, tenant) == 0
    assert rows_of(store, other) > 0, "another tenant's profile stays"
    (answer,) = [e for e in store.events if isinstance(e, TenantDataErased)]
    assert (answer.service, answer.tenant_id) == ("profile", tenant)
    assert answer.tables["profile_node"] == 2
    assert answer.tables["review_task"] == 1
    assert [item.table for item in answer.retained] == ["outbox_event"]
    (entry,) = [e for e in store.audit if e.action == "tenant.erased"]
    assert entry.actor.label == "system:profile"
    assert consume(store, tenant, tmp_path, on=True) is Outcome.SKIPPED


def test_with_the_flag_off_it_only_logs(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant = TenantId.new()
    stocked(store, tenant, "Example Traders")
    before = rows_of(store, tenant)
    assert consume(store, tenant, tmp_path, on=False) is Outcome.PROCESSED
    assert rows_of(store, tenant) == before
    assert not [e for e in store.events if isinstance(e, TenantDataErased)]


def test_the_worker_hosts_the_erasure_group_on_postgres_only() -> None:
    hosted = components(
        ProfileSettings(_env_file=None, service_name="profile-worker"), enabled=lambda _: False
    )
    assert [consumer.group_id for consumer in hosted.consumers] == ["profile.erasure"]
    with pytest.raises(ValueError, match="postgres"):
        components(ProfileSettings(_env_file=None, service_name="x", profile_store="memory"))
