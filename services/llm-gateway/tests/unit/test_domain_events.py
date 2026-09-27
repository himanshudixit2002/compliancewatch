from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import CorrelationId, TenantId
from llm_gateway.domain.budgets import BudgetScope
from llm_gateway.domain.events import (
    BudgetAlarmed,
    EventPublisher,
    LLMCallCompleted,
    correlation_id_from,
)
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry


def _entry() -> LedgerEntry:
    entry_id = uuid4()
    return LedgerEntry(
        id=entry_id,
        occurred_at=datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
        tenant_id=None,
        feature=Feature.SMOKE,
        prompt_name="smoke.echo",
        prompt_version="1",
        model_requested="fake/echo",
        model_served="fake/echo",
        provider="fake",
        input_tokens=1,
        output_tokens=1,
        cached=False,
        cost_usd=Decimal("0.000001"),
        cost_inr=Decimal("0.0001"),
        cost_source=CostSource.ESTIMATE,
        latency_ms=1,
        correlation_id="req-1",
        trace_id=str(entry_id),
        generation_id="",
        status=CallStatus.OK,
    )


def _alarm(**changes: object) -> BudgetAlarmed:
    fields: dict[str, object] = {
        "scope": BudgetScope.TENANT,
        "key": str(TenantId.new()),
        "month": date(2026, 9, 1),
        "spent_inr": Decimal("1200"),
        "limit_inr": Decimal("1500"),
        "ratio": Decimal("0.8"),
    }
    fields.update(changes)
    return BudgetAlarmed(**fields)  # type: ignore[arg-type]


def test_topics() -> None:
    assert LLMCallCompleted.topic == "llm.call.completed"
    assert BudgetAlarmed.topic == "llm.budget.alarmed"


def test_call_completed_carries_the_entry_in_the_envelope() -> None:
    entry = _entry()
    tenant = TenantId.new()
    event = LLMCallCompleted(entry=entry, tenant_id=tenant)
    assert event.entry is entry
    assert event.tenant_id == tenant
    assert isinstance(event.correlation_id, CorrelationId)
    assert isinstance(event, DomainEvent)
    with pytest.raises(InvariantViolationError, match="entry must be LedgerEntry"):
        LLMCallCompleted(entry="row")  # type: ignore[arg-type]


def test_budget_alarmed_fields() -> None:
    event = _alarm()
    assert (event.scope, event.month, event.ratio) == (
        BudgetScope.TENANT,
        date(2026, 9, 1),
        Decimal("0.8"),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"scope": "tenant"}, "scope must be BudgetScope"),
        ({"key": 1}, "key must be str"),
        ({"month": date(2026, 9, 15)}, "month must be the first day"),
        ({"spent_inr": Decimal("-1")}, "spent_inr must be at least 0"),
        ({"limit_inr": Decimal("0")}, "limit_inr must be positive"),
        ({"ratio": -0.5}, "ratio must be a finite Decimal"),
        ({"tenant_id": "t"}, "tenant_id must be TenantId"),
    ],
)
def test_budget_alarmed_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        _alarm(**changes)


def test_correlation_id_from_hex_dashed_and_opaque_text() -> None:
    hexed = uuid4().hex
    assert correlation_id_from(hexed) == CorrelationId(UUID(hexed))
    dashed = str(uuid4())
    assert str(correlation_id_from(dashed)) == dashed
    first = correlation_id_from("req-123")
    assert isinstance(first, CorrelationId)
    assert first != correlation_id_from("req-123")
    assert isinstance(correlation_id_from(""), CorrelationId)


class _Publisher:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def test_publisher_protocol_is_structural() -> None:
    stub = _Publisher()
    publisher: EventPublisher = stub
    publisher.publish(_alarm())
    publisher.publish(LLMCallCompleted(entry=_entry()))
    assert [type(e).topic for e in stub.events] == ["llm.budget.alarmed", "llm.call.completed"]
