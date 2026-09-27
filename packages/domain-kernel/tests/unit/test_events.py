from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import ClassVar

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import SCHEMA_VERSION_PATTERN, TOPIC_PATTERN, DomainEvent, utc_now
from domain_kernel.ids import CorrelationId, EventId, ObligationId, TenantId


@dataclass(frozen=True, slots=True, kw_only=True)
class _Closed(DomainEvent):
    topic: ClassVar[str] = "obligation.closed"

    obligation_id: ObligationId
    reason: str = "completed"

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if not self.reason:
            raise InvariantViolationError("reason must not be empty")


def _event_class(topic_value: str, version: str = "1.0.0") -> type[DomainEvent]:
    @dataclass(frozen=True, slots=True, kw_only=True)
    class _Event(DomainEvent):
        topic: ClassVar[str] = topic_value
        schema_version: ClassVar[str] = version

    return _Event


def test_envelope_defaults() -> None:
    before = utc_now()
    event = _Closed(obligation_id=ObligationId.new())
    assert isinstance(event.event_id, EventId)
    assert isinstance(event.correlation_id, CorrelationId)
    assert event.tenant_id is None
    assert event.causation_id is None
    assert event.occurred_at.tzinfo is not None
    assert before <= event.occurred_at <= utc_now()
    assert event.topic == "obligation.closed"
    assert type(event).topic == "obligation.closed"
    assert event.schema_version == "1.0.0"
    assert event.reason == "completed"
    assert _Closed(obligation_id=ObligationId.new()).event_id != event.event_id


def test_base_event_cannot_be_instantiated() -> None:
    with pytest.raises(InvariantViolationError, match=r"DomainEvent\.topic"):
        DomainEvent()


@pytest.mark.parametrize("topic", ["rule.published", "rule_version.status.changed", "a1.b2_c"])
def test_valid_topics(topic: str) -> None:
    event = _event_class(topic)()
    assert type(event).topic == topic
    assert TOPIC_PATTERN.fullmatch(topic)


@pytest.mark.parametrize(
    "topic", ["", "rule", "Rule.published", "rule.Published", "rule..published", "1rule.x", "a.b."]
)
def test_invalid_topics(topic: str) -> None:
    with pytest.raises(InvariantViolationError, match=r"topic must look like object\.verb"):
        _event_class(topic)()


@pytest.mark.parametrize("version", ["1.0.0", "0.1.0", "12.34.56"])
def test_valid_schema_versions(version: str) -> None:
    event = _event_class("rule.published", version)()
    assert type(event).schema_version == version
    assert SCHEMA_VERSION_PATTERN.fullmatch(version)


@pytest.mark.parametrize("version", ["", "1", "1.0", "v1.0.0", "1.0.0-rc1", "1.0.0.0", "a.b.c"])
def test_invalid_schema_versions(version: str) -> None:
    with pytest.raises(InvariantViolationError, match="schema_version must be semver"):
        _event_class("rule.published", version)()


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(InvariantViolationError, match="occurred_at must be timezone-aware"):
        _Closed(obligation_id=ObligationId.new(), occurred_at=datetime(2026, 1, 1))


def test_other_timezones_are_accepted() -> None:
    at = datetime(2026, 1, 1, 9, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    event = _Closed(obligation_id=ObligationId.new(), occurred_at=at)
    assert event.occurred_at == at


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_id", "abc", "event_id must be EventId"),
        ("event_id", CorrelationId.new(), "event_id must be EventId"),
        ("tenant_id", "t1", "tenant_id must be TenantId"),
        ("correlation_id", EventId.new(), "correlation_id must be CorrelationId"),
        ("causation_id", CorrelationId.new(), "causation_id must be EventId"),
    ],
)
def test_envelope_field_types(field: str, value: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        _Closed(obligation_id=ObligationId.new(), **{field: value})  # type: ignore[arg-type]


def test_subclass_invariants_run_after_the_envelope() -> None:
    with pytest.raises(InvariantViolationError, match="reason must not be empty"):
        _Closed(obligation_id=ObligationId.new(), reason="")


def test_events_are_frozen_keyword_only_and_slotted() -> None:
    event = _Closed(obligation_id=ObligationId.new())
    with pytest.raises(FrozenInstanceError):
        event.reason = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        _Closed(ObligationId.new())  # type: ignore[arg-type, call-arg]
    assert not hasattr(event, "__dict__")
    assert "topic" not in _Closed.__slots__
    assert "schema_version" not in _Closed.__slots__


def test_causation_chain() -> None:
    tenant = TenantId.new()
    first = _Closed(obligation_id=ObligationId.new(), tenant_id=tenant)
    second = _Closed(
        obligation_id=ObligationId.new(),
        tenant_id=tenant,
        correlation_id=first.correlation_id,
        causation_id=first.event_id,
    )
    assert second.causation_id == first.event_id
    assert second.correlation_id == first.correlation_id
    assert second.tenant_id == tenant
    assert second.event_id != first.event_id
    assert utc_now().tzinfo is UTC
