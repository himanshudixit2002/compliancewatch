"""The worker's components and its decision handler, on a SQLite inbox and the memory store.

The handler decodes the golden applicability.decided examples and applies them; what it cannot
read is dead-lettered through ``FakeProducer``. Postgres, where the obligations, their outbox
rows and the inbox row commit together, is covered by
tests/integration/test_obligation_reminders.py.
"""

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.ids import RuleVersionId, TenantId
from obligation import worker
from obligation.application.reminders import SendDueReminders
from obligation.domain.events import ObligationCreated
from obligation.domain.repository import UnitOfWorkFactory
from obligation.infrastructure.memory import MemoryStore
from obligation.settings import ObligationSettings
from obligation.testing import FakeRuleVersionReader, rule
from py_common.events import EventMessage
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
    sync_handler,
)
from py_common.outbox.testing import FakeProducer

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
TOPIC = "applicability.decided"
DLQ = "applicability.decided.obligation.decisions.dlq"
RULE_VERSION = RuleVersionId(UUID("4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b"))
TENANT = TenantId(UUID("5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a"))


def obligation_settings(**overrides: Any) -> ObligationSettings:
    """Settings that ignore the repo ``.env``; the memory store unless overridden."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "obligation-worker",
        "obligation_store": "memory",
        "database_url": "postgresql+psycopg://cw:cw@localhost:5432/compliancewatch",
    }
    values.update(overrides)
    return ObligationSettings(**values)


@pytest.fixture
def inbox(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    yield engine
    engine.dispose()


class Setup:
    def __init__(self, inbox: Engine) -> None:
        self.store = MemoryStore()
        self.rules = FakeRuleVersionReader([replace(rule(), rule_version_id=RULE_VERSION)])
        self.producer = FakeProducer()
        handler = worker.decision_handler(self.rules, units_on=self.units_on)
        self.consumer = IdempotentConsumer(
            group_id=worker.GROUP_ID,
            store=SyncProcessedStore(inbox, group_id=worker.GROUP_ID),
            handler=sync_handler(handler),
            producer=self.producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )

    def units_on(self, connection: Connection) -> UnitOfWorkFactory:
        assert connection.in_transaction(), "the handler runs in the inbox transaction"
        return self.store

    def created(self) -> list[ObligationCreated]:
        return [e for e in self.store.events if isinstance(e, ObligationCreated)]


def record(name: str, offset: int = 0, **payload: Any) -> InboundRecord:
    data = json.loads((EXAMPLES / TOPIC / f"{name}.json").read_text(encoding="utf-8"))
    data["payload"].update(payload)
    data["event_id"] = str(uuid4())
    return InboundRecord(
        topic=TOPIC, partition=0, offset=offset, key=b"k", value=json.dumps(data).encode()
    )


async def test_an_applying_decision_materialises_once(inbox: Engine) -> None:
    setup = Setup(inbox)
    applies = record("applies-after-rule-published")
    assert await setup.consumer.process(applies) is Outcome.PROCESSED
    assert await setup.consumer.process(applies) is Outcome.SKIPPED, "a redelivery"
    created = setup.created()
    assert len(created) == 2
    assert {e.tenant_id for e in created} == {TENANT}
    assert {str(e.decision_id) for e in created} == {"7b8c9d0e-1f2a-4b3c-8d4e-5f6a7b8c9d0e"}
    assert setup.rules.reads == [RULE_VERSION]
    assert setup.producer.sent == []


async def test_a_flip_to_not_applicable_closes_and_review_changes_nothing(inbox: Engine) -> None:
    setup = Setup(inbox)
    assert await setup.consumer.process(record("applies-after-rule-published")) is (
        Outcome.PROCESSED
    )
    unsure = record("unsure-free-text-predicate", offset=1, decision_id=str(uuid4()))
    assert await setup.consumer.process(unsure) is Outcome.PROCESSED
    assert all(o.is_open for o in setup.store.obligations.values())

    flipped = record(
        "applies-after-rule-published", offset=2, result="not_applicable", trigger="profile_updated"
    )
    assert await setup.consumer.process(flipped) is Outcome.PROCESSED
    assert not any(o.is_open for o in setup.store.obligations.values())


async def test_unreadable_decisions_are_dead_lettered(inbox: Engine) -> None:
    setup = Setup(inbox)
    unknown_result = record("applies-after-rule-published", result="maybe")
    assert await setup.consumer.process(unknown_result) is Outcome.DEAD
    data = json.loads(
        (EXAMPLES / TOPIC / "applies-after-rule-published.json").read_text(encoding="utf-8")
    )
    data["tenant_id"] = None
    tenantless = InboundRecord(
        topic=TOPIC, partition=0, offset=1, key=b"k", value=json.dumps(data).encode()
    )
    assert await setup.consumer.process(tenantless) is Outcome.DEAD
    unknown_rule = record("applies-after-rule-published", offset=2, rule_version_id=str(uuid4()))
    assert await setup.consumer.process(unknown_rule) is Outcome.DEAD
    assert setup.producer.topics() == [DLQ, DLQ, DLQ]
    assert setup.store.obligations == {}


def test_another_topic_is_ignored(inbox: Engine) -> None:
    setup = Setup(inbox)
    handle = worker.decision_handler(setup.rules, units_on=setup.units_on)
    message = EventMessage(
        event_id=uuid4(),
        topic="profile.updated",
        schema_version="1.0.0",
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        tenant_id=TENANT.value,
        correlation_id=uuid4(),
        causation_id=None,
        payload={},
    )
    with inbox.begin() as connection:
        handle(message, connection)
    assert setup.store.events == []


def test_the_components_are_the_consumer_and_the_sweep_when_enabled() -> None:
    rules = FakeRuleVersionReader()
    settings = obligation_settings(obligation_store="postgres")
    components = worker.components(settings, rules=rules)
    (consumer,) = components.consumers
    assert consumer.group_id == "obligation.decisions"
    assert consumer.topics == ("applicability.decided",)
    assert consumer.dead_letter_topics() == (DLQ,)
    assert components.periodic == (), "the sweep is off by default"
    assert components.relays == ()
    assert components.temporal == ()

    enabled = obligation_settings(
        obligation_store="postgres",
        obligation_sweep_enabled=True,
        obligation_sweep_interval_seconds=120,
    )
    (sweep,) = worker.components(enabled, rules=rules).periodic
    assert (sweep.name, sweep.interval_seconds) == ("obligation-reminder-sweep", 120)
    assert worker.components(settings).consumers[0].group_id == worker.GROUP_ID
    with pytest.raises(ValueError, match="postgres"):
        worker.components(obligation_settings(), rules=rules)


def test_the_sweep_job_logs_what_it_did(caplog: pytest.LogCaptureFixture) -> None:
    store = MemoryStore()
    job = worker.sweep_job(SendDueReminders(store, store))
    with caplog.at_level("INFO"):
        job()
    assert "obligation.reminders_swept" in caplog.text
    with caplog.at_level("ERROR"):
        worker._sweep_failed(TENANT, RuntimeError("boom"))
    assert "obligation.reminder_sweep_failed" in caplog.text


def test_main_runs_the_components_as_a_worker_process(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(settings: Any, components: Any, *, version: str) -> None:
        seen.update(settings=settings, components=components, version=version)

    monkeypatch.setattr(worker, "run_worker_process", fake_run)
    worker.main()
    assert seen["components"] is worker.components
    assert seen["settings"].service_name == "obligation-worker"
