from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from llm_gateway.application.usage import Usage, UsageReport
from llm_gateway.domain.budgets import BudgetLimits, BudgetScope, month_bounds
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.routing import DEFAULT_ROUTES

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
TENANT_A = TenantId.new()
TENANT_B = TenantId.new()


class Ledger:
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


def _entry(tenant: TenantId | None, feature: Feature, inr: str, at: datetime = NOW) -> LedgerEntry:
    entry_id = uuid4()
    return LedgerEntry(
        id=entry_id,
        occurred_at=at,
        tenant_id=tenant,
        feature=feature,
        prompt_name="x.y",
        prompt_version="1",
        model_requested="fake/echo",
        model_served="fake/echo",
        provider="fake",
        input_tokens=1,
        output_tokens=1,
        cached=False,
        cost_usd=None,
        cost_inr=Decimal(inr),
        cost_source=CostSource.ESTIMATE,
        latency_ms=1,
        correlation_id="",
        trace_id=str(entry_id),
        generation_id="",
        status=CallStatus.OK,
    )


@pytest.fixture
def ledger() -> Ledger:
    ledger = Ledger()
    for entry in (
        _entry(TENANT_A, Feature.EXTRACTION, "10.5000"),
        _entry(TENANT_A, Feature.QA, "2.2500"),
        _entry(TENANT_B, Feature.EXTRACTION, "1.0000"),
        _entry(None, Feature.EXTRACTION, "4.0000"),
        _entry(TENANT_A, Feature.EXTRACTION, "100.0000", datetime(2026, 8, 31, 23, tzinfo=UTC)),
        _entry(TENANT_A, Feature.EXTRACTION, "7.0000", datetime(2026, 10, 1, tzinfo=UTC)),
    ):
        ledger.add(entry)
    return ledger


@pytest.fixture
def usage(ledger: Ledger) -> Usage:
    config = GatewayConfig(
        routes=DEFAULT_ROUTES,
        budgets=BudgetLimits(Decimal("15"), Decimal("20"), Decimal("0.8")),
        usd_inr=Decimal("88"),
    )
    return Usage(ledger=ledger, config=config, clock=lambda: NOW)


def test_tenant_scope_sums_the_current_month(usage: Usage) -> None:
    report = usage.spent(tenant_id=TENANT_A, feature=None)
    assert report == UsageReport(
        scope=BudgetScope.TENANT,
        key=str(TENANT_A),
        month=date(2026, 9, 1),
        spent_inr=Decimal("12.7500"),
        budget_inr=Decimal("15"),
        ratio=Decimal("0.85"),
        alarmed=True,
        resets_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def test_feature_narrows_the_tenant_sum(usage: Usage) -> None:
    report = usage.spent(tenant_id=TENANT_A, feature=Feature.EXTRACTION)
    assert (report.scope, report.spent_inr, report.budget_inr) == (
        BudgetScope.TENANT,
        Decimal("10.5000"),
        Decimal("15"),
    )
    assert report.alarmed is False
    assert usage.spent(tenant_id=TENANT_B, feature=Feature.QA).spent_inr == 0


def test_feature_scope_without_a_tenant(usage: Usage) -> None:
    report = usage.spent(tenant_id=None, feature=Feature.EXTRACTION)
    assert (report.scope, report.key, report.spent_inr, report.budget_inr) == (
        BudgetScope.FEATURE,
        "extraction",
        Decimal("15.5000"),
        Decimal("20"),
    )
    assert report.ratio == Decimal("0.775")
    assert report.alarmed is False


def test_explicit_month(usage: Usage) -> None:
    assert usage.spent(tenant_id=TENANT_A, feature=None, month=date(2026, 8, 1)).spent_inr == 100
    october = usage.spent(tenant_id=TENANT_A, feature=None, month=date(2026, 10, 1))
    assert october.spent_inr == 7
    assert october.resets_at == datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(InvariantViolationError, match="month must be the first day"):
        usage.spent(tenant_id=TENANT_A, feature=None, month=date(2026, 8, 2))


def test_neither_tenant_nor_feature_is_an_invariant_violation(usage: Usage) -> None:
    with pytest.raises(InvariantViolationError, match="tenant_id or a feature"):
        usage.spent(tenant_id=None, feature=None)


def test_recent_delegates_to_the_ledger(usage: Usage, ledger: Ledger) -> None:
    assert list(usage.recent(2)) == list(reversed(ledger.entries))[:2]
    assert len(usage.recent()) == 6
