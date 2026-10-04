"""The worker's components and its profile.updated handler, on a SQLite inbox and the memory store.

The handler decodes the golden profile.updated examples and recomputes; what it cannot read is
dead-lettered through ``FakeProducer``. The reads run with no transaction open on the inbox's
connection. Postgres, where the decisions, their outbox rows and the inbox row commit together,
is covered by tests/integration/test_recompute_schema.py.
"""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

import ontology as ontology_package
from applicability_engine import worker
from applicability_engine.application.recompute import ApplyProfileUpdate
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.infrastructure.memory import MemoryStore
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import MemoryProfiles, MemoryRulebook, rule_in_force
from applicability_engine.wiring import Readers
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncUnit,
    processed_event,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
TOPIC = "profile.updated"
DLQ = "profile.updated.applicability-engine.profiles.dlq"
EXAMPLE = "turnover-band-by-user"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}


def golden(name: str = EXAMPLE) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES / TOPIC / f"{name}.json").read_text("utf-8"))
    return data


TENANT = TenantId(UUID(golden()["tenant_id"]))
NODE = BusinessId(UUID(golden()["payload"]["business_id"]))


def engine_settings(**overrides: Any) -> ApplicabilityEngineSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "applicability-engine-worker",
        "applicability_engine_store": "postgres",
        "database_url": "postgresql+psycopg://cw:cw@localhost:5432/compliancewatch",
    }
    values.update(overrides)
    return ApplicabilityEngineSettings(**values)


@pytest.fixture
def inbox(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    yield engine
    engine.dispose()


class Setup:
    def __init__(self, inbox: Engine, *, enabled: bool = True) -> None:
        self.store = MemoryStore()
        self.profiles = MemoryProfiles()
        self.rulebook = MemoryRulebook()
        self.rule = self.rulebook.put_in_force(rule_in_force(REGULAR))
        self.profiles.put(
            {"registration_type": "regular"},
            tenant_id=TENANT,
            business_id=NODE,
            lineage=[BusinessId.new()],
        )
        self.producer = FakeProducer()
        self.transactions: list[bool] = []
        recompute = ApplyProfileUpdate(
            self.profiles, self.rulebook, ontology_package.load(), enabled=enabled
        )
        self.consumer = IdempotentConsumer(
            group_id=worker.GROUP_ID,
            store=read_first_store(inbox, worker.GROUP_ID),
            handler=worker.profile_handler(recompute, units_on=self.units_on),
            producer=self.producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )

    def units_on(self, connection: Connection) -> UnitOfWorkFactory:
        return self.store

    def decided(self) -> list[ApplicabilityDecided]:
        return [e for e in self.store.events if isinstance(e, ApplicabilityDecided)]


def record(offset: int = 0, *, topic: str = TOPIC, **changes: Any) -> InboundRecord:
    data = golden()
    data["event_id"] = str(uuid4())
    data["topic"] = topic
    data.update(changes)
    return InboundRecord(
        topic=topic, partition=0, offset=offset, key=b"k", value=json.dumps(data).encode()
    )


async def test_a_profile_change_is_recomputed_once(inbox: Engine) -> None:
    setup = Setup(inbox)
    event = record()
    assert await setup.consumer.process(event) is Outcome.PROCESSED
    assert await setup.consumer.process(event) is Outcome.SKIPPED, "a redelivery"
    (decided,) = setup.decided()
    assert (decided.tenant_id, decided.business_id, decided.rule_version_id) == (
        TENANT,
        NODE,
        setup.rule.rule_version_id,
    )
    assert decided.causation_id is not None
    assert str(decided.causation_id.value) == json.loads(event.value)["event_id"]
    assert NODE in setup.store.directory
    assert setup.producer.sent == []


async def test_the_reads_happen_with_no_transaction_open(
    inbox: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = Setup(inbox)
    units: list[SyncUnit] = []
    seen: list[bool] = []
    original = setup.profiles.snapshot

    class Remembering:
        """The inbox store, remembering each unit so a read can look at its connection."""

        def __init__(self) -> None:
            self.store = read_first_store(inbox, worker.GROUP_ID)

        def unit(self) -> Any:
            return self._unit()

        @asynccontextmanager
        async def _unit(self) -> AsyncIterator[Any]:
            async with self.store.unit() as unit:
                assert isinstance(unit, SyncUnit)
                units.append(unit)
                yield unit

    def watching(*args: Any) -> Any:
        seen.append(units[-1].connection.in_transaction())
        return original(*args)

    monkeypatch.setattr(setup.profiles, "snapshot", watching)
    recompute = ApplyProfileUpdate(
        setup.profiles, setup.rulebook, ontology_package.load(), enabled=True
    )
    consumer = IdempotentConsumer(
        group_id=worker.GROUP_ID,
        store=Remembering(),
        handler=worker.profile_handler(recompute, units_on=setup.units_on),
        producer=setup.producer,
    )
    assert await consumer.process(record()) is Outcome.PROCESSED
    assert seen == [False], "no transaction is open while the profile is read"
    assert len(setup.decided()) == 1


async def test_with_recompute_off_only_the_directory_is_kept(inbox: Engine) -> None:
    setup = Setup(inbox, enabled=False)
    assert await setup.consumer.process(record()) is Outcome.PROCESSED
    assert setup.store.decisions == {}
    assert setup.decided() == []
    assert setup.store.directory[NODE].level is AttributeLevel.REGISTRATION


async def test_an_unreadable_event_or_one_without_its_tenant_is_dead_lettered(
    inbox: Engine,
) -> None:
    setup = Setup(inbox)
    no_tenant = record(tenant_id=None)
    assert await setup.consumer.process(no_tenant) is Outcome.DEAD
    bad = record(offset=1, payload={"business_id": "not-a-uuid"})
    assert await setup.consumer.process(bad) is Outcome.DEAD
    assert setup.producer.topics() == [DLQ, DLQ]
    assert b"carries no tenant" in (setup.producer.sent[0].header("error") or b"")
    assert setup.store.decisions == {}


async def test_another_topic_is_ignored(inbox: Engine) -> None:
    setup = Setup(inbox)
    other = record(topic="rule.published")
    assert await setup.consumer.process(other) is Outcome.PROCESSED
    assert setup.store.directory == {}
    assert setup.store.decisions == {}


async def test_a_failing_read_is_retried_then_dead_lettered(
    inbox: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = Setup(inbox)

    def down(*args: Any) -> Any:
        raise ConnectionError("profile unreachable")

    monkeypatch.setattr(setup.profiles, "snapshot", down)
    assert await setup.consumer.process(record()) is Outcome.DEAD
    assert setup.producer.sent[0].header("attempts") == b"2"
    assert setup.store.directory == {}


def test_the_components_are_one_consumer_that_reads_first() -> None:
    readers = Readers(profiles=MemoryProfiles(), rulebook=MemoryRulebook())
    components = worker.components(engine_settings(), readers=readers)
    (consumer,) = components.consumers
    assert (consumer.group_id, consumer.topics) == ("applicability-engine.profiles", (TOPIC,))
    assert consumer.dead_letter_topics() == (DLQ,)
    assert consumer.store_factory is read_first_store
    assert not components.relays
    assert not components.periodic


def test_the_recompute_follows_the_settings() -> None:
    readers = Readers(profiles=MemoryProfiles(), rulebook=MemoryRulebook())
    off = worker.recompute_of(engine_settings(), readers)
    on = worker.recompute_of(engine_settings(applicability_recompute_enabled=True), readers)
    assert (off.enabled, on.enabled) == (False, True)


def test_the_worker_needs_the_postgres_store() -> None:
    with pytest.raises(ValueError, match="CW_APPLICABILITY_ENGINE_STORE=postgres"):
        worker.components(engine_settings(applicability_engine_store="memory"))
