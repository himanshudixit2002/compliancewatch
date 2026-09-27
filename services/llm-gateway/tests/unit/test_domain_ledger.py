from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from llm_gateway.domain.budgets import month_bounds
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import (
    MAX_CORRELATION_ID,
    MAX_ERROR_TYPE,
    MAX_GENERATION_ID,
    MAX_MODEL_ID,
    MAX_PROMPT_NAME,
    MAX_PROMPT_VERSION,
    MAX_PROVIDER,
    MAX_TRACE_ID,
    CostLedger,
    LedgerEntry,
)

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def _entry(**changes: object) -> LedgerEntry:
    entry_id = uuid4()
    fields: dict[str, object] = {
        "id": entry_id,
        "occurred_at": NOW,
        "tenant_id": TenantId.new(),
        "feature": Feature.SMOKE,
        "prompt_name": "smoke.echo",
        "prompt_version": "1",
        "model_requested": "fake/echo",
        "model_served": "fake/echo",
        "provider": "fake",
        "input_tokens": 10,
        "output_tokens": 5,
        "cached": False,
        "cost_usd": Decimal("0.000003"),
        "cost_inr": Decimal("0.0003"),
        "cost_source": CostSource.ESTIMATE,
        "latency_ms": 12,
        "correlation_id": "req-1",
        "trace_id": str(entry_id),
        "generation_id": "fake-abc",
        "status": CallStatus.OK,
    }
    fields.update(changes)
    return LedgerEntry(**fields)  # type: ignore[arg-type]


def test_valid_entries() -> None:
    entry = _entry()
    assert isinstance(entry.id, UUID)
    assert entry.error_type == ""
    regulatory = _entry(tenant_id=None, cost_usd=None, provider="")
    assert regulatory.tenant_id is None
    assert regulatory.cost_usd is None
    failed = _entry(status=CallStatus.ERROR, error_type="llm-provider-unavailable")
    assert failed.status is CallStatus.ERROR
    assert _entry(prompt_name="a" * MAX_PROMPT_NAME).prompt_name


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "x"}, "id must be UUID"),
        ({"occurred_at": datetime(2026, 9, 27)}, "occurred_at must be timezone-aware"),
        ({"tenant_id": "t"}, "tenant_id must be TenantId"),
        ({"feature": "smoke"}, "feature must be Feature"),
        ({"prompt_name": " "}, "prompt_name must not be blank"),
        ({"prompt_name": "a" * (MAX_PROMPT_NAME + 1)}, "prompt_name must be at most 120"),
        ({"prompt_version": "1" * (MAX_PROMPT_VERSION + 1)}, "prompt_version must be at most 40"),
        ({"model_requested": ""}, "model_requested must not be blank"),
        ({"model_served": "m" * (MAX_MODEL_ID + 1)}, "model_served must be at most 120"),
        ({"provider": "p" * (MAX_PROVIDER + 1)}, "provider must be at most 60"),
        ({"provider": None}, "provider must be str"),
        ({"input_tokens": -1}, "input_tokens must be at least 0"),
        ({"output_tokens": 1.0}, "output_tokens must be an integer"),
        ({"cached": "no"}, "cached must be bool"),
        ({"cost_usd": Decimal("-1")}, "cost_usd must be at least 0"),
        ({"cost_inr": 0.1}, "cost_inr must be a finite Decimal"),
        ({"cost_source": "estimate"}, "cost_source must be CostSource"),
        ({"latency_ms": -5}, "latency_ms must be at least 0"),
        ({"correlation_id": "c" * (MAX_CORRELATION_ID + 1)}, "correlation_id must be at most 64"),
        ({"trace_id": "t" * (MAX_TRACE_ID + 1)}, "trace_id must be at most 120"),
        ({"generation_id": "g" * (MAX_GENERATION_ID + 1)}, "generation_id must be at most 120"),
        ({"status": "ok"}, "status must be CallStatus"),
        ({"error_type": "e" * (MAX_ERROR_TYPE + 1)}, "error_type must be at most 80"),
        ({"error_type": "RuntimeError"}, "error_type is set exactly on error rows"),
        ({"status": CallStatus.ERROR}, "error_type is set exactly on error rows"),
    ],
)
def test_entry_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        _entry(**changes)


def test_entries_are_frozen_value_objects() -> None:
    entry = _entry()
    assert replace(entry, cached=True).cached is True
    with pytest.raises(AttributeError):
        entry.cached = True  # type: ignore[misc]


class _Ledger:
    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def add(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)

    def spent_inr(
        self, *, tenant_id: TenantId | None, feature: Feature | None, month: date
    ) -> Decimal:
        start, end = month_bounds(month)
        return sum(
            (
                e.cost_inr
                for e in self.entries
                if start <= e.occurred_at < end
                and (tenant_id is None or e.tenant_id == tenant_id)
                and (feature is None or e.feature is feature)
            ),
            Decimal("0.0000"),
        )

    def recent(self, limit: int) -> Sequence[LedgerEntry]:
        return tuple(reversed(self.entries))[:limit]


def test_ledger_protocol_is_structural() -> None:
    ledger: CostLedger = _Ledger()
    tenant = TenantId.new()
    ledger.add(_entry(tenant_id=tenant, cost_inr=Decimal("1.5000")))
    ledger.add(_entry(tenant_id=tenant, feature=Feature.QA, cost_inr=Decimal("2.0000")))
    ledger.add(_entry(tenant_id=None, cost_inr=Decimal("4.0000")))
    assert ledger.spent_inr(tenant_id=tenant, feature=None, month=date(2026, 9, 1)) == Decimal(
        "3.5"
    )
    assert ledger.spent_inr(tenant_id=tenant, feature=Feature.QA, month=date(2026, 9, 1)) == 2
    assert ledger.spent_inr(tenant_id=None, feature=Feature.SMOKE, month=date(2026, 9, 1)) == 5.5
    assert ledger.spent_inr(tenant_id=None, feature=None, month=date(2026, 8, 1)) == 0
    assert len(ledger.recent(2)) == 2
