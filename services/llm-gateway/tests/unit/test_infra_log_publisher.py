"""The log publisher: envelope fields as top-level keys, the payload stringified."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from structlog.testing import capture_logs

from domain_kernel.ids import CorrelationId, EventId, TenantId
from llm_gateway.domain.budgets import BudgetScope
from llm_gateway.domain.events import BudgetAlarmed, LLMCallCompleted
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.infrastructure.events.log import LogPublisher

TENANT = TenantId.new()
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def entry() -> LedgerEntry:
    entry_id = uuid4()
    return LedgerEntry(
        id=entry_id,
        occurred_at=NOW,
        tenant_id=TENANT,
        feature=Feature.EXTRACTION,
        prompt_name="extraction.rule_candidate",
        prompt_version="0",
        model_requested="fake/echo",
        model_served="fake/echo",
        provider="fake",
        input_tokens=1008,
        output_tokens=52,
        cached=False,
        cost_usd=Decimal("0.000122"),
        cost_inr=Decimal("0.0107"),
        cost_source=CostSource.ESTIMATE,
        latency_ms=5,
        correlation_id="req-1",
        trace_id=str(entry_id),
        generation_id="fake-1",
        status=CallStatus.OK,
    )


def test_a_call_completed_event_is_one_info_line_with_the_entry_as_payload() -> None:
    row = entry()
    cause = EventId.new()
    event = LLMCallCompleted(
        entry=row, tenant_id=TENANT, correlation_id=CorrelationId.new(), causation_id=cause
    )
    with capture_logs() as logs:
        LogPublisher().publish(event)

    [line] = logs
    assert line["event"] == "event.published"
    assert line["log_level"] == "info"
    assert line["topic"] == "llm.call.completed"
    assert line["event_id"] == str(event.event_id)
    assert line["occurred_at"] == event.occurred_at.isoformat()
    assert line["tenant_id"] == str(TENANT)
    assert line["correlation_id"] == str(event.correlation_id)
    assert line["causation_id"] == str(cause)
    payload = line["payload"]
    assert list(payload) == ["entry"]
    assert payload["entry"]["id"] == str(row.id)
    assert payload["entry"]["feature"] == "extraction"
    assert payload["entry"]["tenant_id"] == str(TENANT)
    assert payload["entry"]["cost_inr"] == "0.0107"
    assert payload["entry"]["status"] == "ok"
    assert payload["entry"]["occurred_at"] == "2026-09-27 10:00:00+00:00"


def test_a_budget_alarm_has_a_flat_payload_of_strings() -> None:
    event = BudgetAlarmed(
        scope=BudgetScope.TENANT,
        key=str(TENANT),
        month=date(2026, 9, 1),
        spent_inr=Decimal("1200.0000"),
        limit_inr=Decimal("1500"),
        ratio=Decimal("0.8"),
        tenant_id=TENANT,
    )
    with capture_logs() as logs:
        LogPublisher().publish(event)

    [line] = logs
    assert line["topic"] == "llm.budget.alarmed"
    assert line["causation_id"] is None
    assert line["payload"] == {
        "scope": "tenant",
        "key": str(TENANT),
        "month": "2026-09-01",
        "spent_inr": "1200.0000",
        "limit_inr": "1500",
        "ratio": "0.8",
    }


def test_a_regulatory_event_has_no_tenant() -> None:
    event = LLMCallCompleted(entry=entry(), tenant_id=None)
    with capture_logs() as logs:
        LogPublisher().publish(event)
    [line] = logs
    assert line["tenant_id"] is None
