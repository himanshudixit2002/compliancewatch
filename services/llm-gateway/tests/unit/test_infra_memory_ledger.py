"""The in-memory ledger: sums by tenant, feature and month; newest first; thread safety."""

import threading
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.infrastructure.ledger.memory import MemoryLedger

SEPTEMBER = date(2026, 9, 1)
TENANT_A = TenantId.new()
TENANT_B = TenantId.new()


def entry(**changes: Any) -> LedgerEntry:
    entry_id = uuid4()
    fields: dict[str, Any] = {
        "id": entry_id,
        "occurred_at": datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        "tenant_id": TENANT_A,
        "feature": Feature.EXTRACTION,
        "prompt_name": "extraction.rule_candidate",
        "prompt_version": "0",
        "model_requested": "fake/echo",
        "model_served": "fake/echo",
        "provider": "fake",
        "input_tokens": 10,
        "output_tokens": 5,
        "cached": False,
        "cost_usd": Decimal("0.000100"),
        "cost_inr": Decimal("1.0000"),
        "cost_source": CostSource.ESTIMATE,
        "latency_ms": 12,
        "correlation_id": "req-1",
        "trace_id": str(entry_id),
        "generation_id": "fake-abc",
        "status": CallStatus.OK,
    }
    fields.update(changes)
    return LedgerEntry(**fields)


def seeded() -> MemoryLedger:
    ledger = MemoryLedger()
    for row in (
        entry(cost_inr=Decimal("10.5"), occurred_at=datetime(2026, 9, 15, tzinfo=UTC)),
        entry(
            cost_inr=Decimal("2.25"),
            feature=Feature.QA,
            occurred_at=datetime(2026, 9, 16, tzinfo=UTC),
        ),
        entry(
            cost_inr=Decimal("1.0"),
            tenant_id=TENANT_B,
            occurred_at=datetime(2026, 9, 17, tzinfo=UTC),
        ),
        entry(
            cost_inr=Decimal("4.0"), tenant_id=None, occurred_at=datetime(2026, 9, 18, tzinfo=UTC)
        ),
        entry(cost_inr=Decimal("100"), occurred_at=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)),
        entry(cost_inr=Decimal("7"), occurred_at=datetime(2026, 10, 1, tzinfo=UTC)),
    ):
        ledger.add(row)
    return ledger


def test_entries_keep_insertion_order_and_ping_is_true() -> None:
    ledger = MemoryLedger()
    first, second = entry(), entry()
    ledger.add(first)
    ledger.add(second)
    assert ledger.entries() == (first, second)
    assert ledger.ping() is True


def test_add_rejects_anything_but_an_entry() -> None:
    with pytest.raises(InvariantViolationError, match="entry must be LedgerEntry"):
        MemoryLedger().add("row")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tenant", "feature", "month", "expected"),
    [
        (TENANT_A, None, SEPTEMBER, "12.7500"),
        (None, Feature.EXTRACTION, SEPTEMBER, "15.5000"),
        (TENANT_A, Feature.EXTRACTION, SEPTEMBER, "10.5000"),
        (None, None, SEPTEMBER, "17.7500"),
        (TENANT_A, None, date(2026, 8, 1), "100.0000"),
        (TENANT_B, Feature.QA, SEPTEMBER, "0.0000"),
        (None, Feature.QA, SEPTEMBER, "2.2500"),
        (TENANT_A, None, date(2026, 10, 1), "7.0000"),
    ],
)
def test_spent_inr_filters_by_tenant_feature_and_month(
    tenant: TenantId | None, feature: Feature | None, month: date, expected: str
) -> None:
    spent = seeded().spent_inr(tenant_id=tenant, feature=feature, month=month)
    assert isinstance(spent, Decimal)
    assert str(spent) == expected


def test_spent_inr_needs_the_first_day_of_a_month() -> None:
    with pytest.raises(InvariantViolationError, match="first day"):
        MemoryLedger().spent_inr(tenant_id=None, feature=None, month=date(2026, 9, 2))


def test_recent_is_newest_first_and_limited() -> None:
    ledger = seeded()
    assert [row.cost_inr for row in ledger.recent(3)] == [
        Decimal("7"),
        Decimal("4.0"),
        Decimal("1.0"),
    ]
    assert len(ledger.recent(100)) == 6
    assert ledger.recent(0) == ()


def test_recent_breaks_ties_by_latest_added_first() -> None:
    ledger = MemoryLedger()
    at = datetime(2026, 9, 15, tzinfo=UTC)
    first, second = entry(occurred_at=at), entry(occurred_at=at)
    ledger.add(first)
    ledger.add(second)
    assert ledger.recent(2) == (second, first)


def test_recent_rejects_a_negative_limit() -> None:
    with pytest.raises(InvariantViolationError, match="limit must be at least 0"):
        MemoryLedger().recent(-1)


def test_concurrent_adds_are_all_kept() -> None:
    ledger = MemoryLedger()

    def worker() -> None:
        for _ in range(50):
            ledger.add(entry())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(ledger.entries()) == 400
    assert ledger.spent_inr(tenant_id=TENANT_A, feature=None, month=SEPTEMBER) == Decimal("400")
