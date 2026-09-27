from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from sqlalchemy import Engine, create_engine, select

from domain_kernel.events import DomainEvent
from domain_kernel.ids import ObligationId, TenantId
from py_common.events import EventMessage
from py_common.outbox.schema import metadata, outbox_event
from py_common.outbox.writer import OutboxWriter


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationCreated(DomainEvent):
    topic: ClassVar[str] = "obligation.created"
    obligation_id: ObligationId
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RulePublished(DomainEvent):
    topic: ClassVar[str] = "rule.published"
    title: str


NOW = datetime(2026, 10, 1, 2, 31, 5, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def rows(engine: Engine) -> list[dict[str, object]]:
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(select(outbox_event)).all()]


def test_write_inserts_the_wire_message(engine: Engine) -> None:
    tenant = TenantId.new()
    event = ObligationCreated(tenant_id=tenant, obligation_id=ObligationId.new(), title="File")
    writer = OutboxWriter(clock=lambda: NOW)
    with engine.begin() as connection:
        record = writer.write(connection, event)
    (row,) = rows(engine)
    assert record.event_id == event.event_id.value == row["id"]
    assert row["topic"] == "obligation.created"
    assert row["schema_version"] == "1.0.0"
    assert row["partition_key"] == str(tenant) == record.partition_key
    assert row["tenant_id"] == tenant.value
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["published_at"] is None
    assert row["last_error"] == ""
    message = row["message"]
    assert isinstance(message, dict)
    assert message["topic"] == "obligation.created"
    assert message["tenant_id"] == str(tenant)
    assert message["payload"] == {"obligation_id": str(event.obligation_id), "title": "File"}
    assert EventMessage.model_validate(message) == record.message


def test_regulatory_events_default_to_the_event_id_as_key(engine: Engine) -> None:
    event = RulePublished(title="x")
    with engine.begin() as connection:
        record = OutboxWriter().write(connection, event)
    assert record.partition_key == str(event.event_id)
    assert rows(engine)[0]["tenant_id"] is None


def test_an_explicit_partition_key_wins(engine: Engine) -> None:
    event = RulePublished(title="x")
    with engine.begin() as connection:
        record = OutboxWriter().write(connection, event, partition_key="rule-42")
    assert record.partition_key == "rule-42"
    with engine.begin() as connection, pytest.raises(ValueError, match="blank"):
        OutboxWriter().write(connection, event, partition_key="   ")


def test_a_rolled_back_transaction_writes_nothing(engine: Engine) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        OutboxWriter().write(connection, RulePublished(title="x"))
        transaction.rollback()
    assert rows(engine) == []


def test_two_events_in_one_transaction_land_together(engine: Engine) -> None:
    writer = OutboxWriter()
    with engine.begin() as connection:
        first = writer.write(connection, RulePublished(title="a"))
        second = writer.write(connection, RulePublished(title="b"))
    assert {row["id"] for row in rows(engine)} == {first.event_id, second.event_id}


def test_validator_runs_before_the_insert(engine: Engine) -> None:
    seen: list[EventMessage] = []

    def validator(message: EventMessage) -> None:
        seen.append(message)
        if message.payload["title"] == "bad":
            raise ValueError("title must not be bad")

    writer = OutboxWriter(validator=validator)
    with engine.begin() as connection:
        writer.write(connection, RulePublished(title="good"))
        with pytest.raises(ValueError, match="bad"):
            writer.write(connection, RulePublished(title="bad"))
    assert [message.payload["title"] for message in seen] == ["good", "bad"]
    assert [row["message"]["payload"]["title"] for row in rows(engine)] == ["good"]  # type: ignore[index]
