from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from llm_gateway.domain.budgets import (
    BudgetLimits,
    BudgetScope,
    BudgetStatus,
    budget_scopes,
    month_bounds,
    month_of,
    next_month_start,
    require_month,
)
from llm_gateway.domain.features import Feature

IST = timezone(timedelta(hours=5, minutes=30))


def test_month_of_is_the_utc_month() -> None:
    assert month_of(datetime(2026, 10, 1, 2, 0, tzinfo=IST)) == date(2026, 9, 1)
    assert month_of(datetime(2026, 10, 1, 5, 30, tzinfo=IST)) == date(2026, 10, 1)
    assert month_of(datetime(2026, 9, 27, 23, 59, tzinfo=UTC)) == date(2026, 9, 1)
    with pytest.raises(InvariantViolationError, match="at must be timezone-aware"):
        month_of(datetime(2026, 9, 27))


def test_month_bounds_and_next_month() -> None:
    start, end = month_bounds(date(2026, 9, 1))
    assert start == datetime(2026, 9, 1, tzinfo=UTC)
    assert end == datetime(2026, 10, 1, tzinfo=UTC)
    assert next_month_start(date(2026, 12, 1)) == datetime(2027, 1, 1, tzinfo=UTC)
    assert next_month_start(date(2026, 2, 1)) == datetime(2026, 3, 1, tzinfo=UTC)


def test_month_must_be_a_first_day() -> None:
    assert require_month(date(2026, 9, 1), "month") == date(2026, 9, 1)
    with pytest.raises(InvariantViolationError, match="month must be the first day of a month"):
        month_bounds(date(2026, 9, 2))
    with pytest.raises(InvariantViolationError, match="month must be a date without a time"):
        next_month_start(datetime(2026, 9, 1, tzinfo=UTC))


def test_budget_scopes() -> None:
    tenant = TenantId.new()
    assert budget_scopes(tenant, Feature.QA) == (
        (BudgetScope.TENANT, str(tenant)),
        (BudgetScope.FEATURE, "qa"),
    )
    assert budget_scopes(None, Feature.EXTRACTION) == ((BudgetScope.FEATURE, "extraction"),)
    with pytest.raises(InvariantViolationError, match="feature must be Feature"):
        budget_scopes(None, "qa")  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="tenant_id must be TenantId"):
        budget_scopes("t", Feature.QA)  # type: ignore[arg-type]


def _status(spent: str, limit: str = "100", alarm: str = "0.8") -> BudgetStatus:
    return BudgetStatus(
        BudgetScope.FEATURE, "qa", date(2026, 9, 1), Decimal(spent), Decimal(limit), Decimal(alarm)
    )


def test_status_at_eighty_and_hundred_percent() -> None:
    below = _status("79.9999")
    assert (below.alarmed, below.exceeded) == (False, False)
    at_alarm = _status("80")
    assert (at_alarm.ratio, at_alarm.alarmed, at_alarm.exceeded) == (Decimal("0.8"), True, False)
    full = _status("100")
    assert (full.ratio, full.alarmed, full.exceeded) == (Decimal("1"), True, True)
    over = _status("150")
    assert over.ratio == Decimal("1.5")
    assert _status("0").ratio == 0
    assert _status("100", alarm="1").alarmed is True
    assert _status("99.99", alarm="1").alarmed is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"scope": "tenant"}, "scope must be BudgetScope"),
        ({"key": None}, "key must be str"),
        ({"month": date(2026, 9, 2)}, "month must be the first day"),
        ({"spent_inr": Decimal("-1")}, "spent_inr must be at least 0"),
        ({"limit_inr": Decimal("0")}, "limit_inr must be positive"),
        ({"alarm_ratio": Decimal("0")}, "alarm_ratio must be positive"),
    ],
)
def test_status_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "scope": BudgetScope.TENANT,
        "key": "t",
        "month": date(2026, 9, 1),
        "spent_inr": Decimal("1"),
        "limit_inr": Decimal("10"),
        "alarm_ratio": Decimal("0.8"),
    }
    fields.update(kwargs)
    with pytest.raises(InvariantViolationError, match=message):
        BudgetStatus(**fields)  # type: ignore[arg-type]


def test_limits() -> None:
    limits = BudgetLimits(Decimal("1500"), Decimal("20000"), Decimal("0.8"))
    assert limits.limit_for(BudgetScope.TENANT) == Decimal("1500")
    assert limits.limit_for(BudgetScope.FEATURE) == Decimal("20000")
    assert BudgetLimits(Decimal("0.0001"), Decimal("1"), Decimal("1")).alarm_ratio == 1


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((Decimal("0"), Decimal("1"), Decimal("0.8")), "tenant_monthly_inr must be positive"),
        ((Decimal("1"), Decimal("-1"), Decimal("0.8")), "feature_monthly_inr must be positive"),
        ((Decimal("1"), Decimal("1"), Decimal("0")), "alarm_ratio must be positive"),
        ((Decimal("1"), Decimal("1"), Decimal("1.5")), r"alarm_ratio must be within \(0, 1\]"),
        ((1500, Decimal("1"), Decimal("0.8")), "tenant_monthly_inr must be a finite Decimal"),
        ((Decimal("1"), Decimal("1"), 0.8), "alarm_ratio must be a finite Decimal"),
    ],
)
def test_limit_invariants(args: tuple[object, object, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        BudgetLimits(*args)  # type: ignore[arg-type]
