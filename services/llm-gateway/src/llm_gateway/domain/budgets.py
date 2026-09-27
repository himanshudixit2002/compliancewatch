"""Monthly budgets per tenant and per feature, and the calendar arithmetic behind them.

Months are UTC: a call at 02:00 IST on the first belongs to the previous month's budget.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from domain_kernel._validation import require_aware, require_date, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from llm_gateway.domain.features import Feature
from llm_gateway.domain.pricing import require_decimal, require_positive_decimal


class BudgetScope(StrEnum):
    TENANT = "tenant"
    FEATURE = "feature"


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    """Monthly ceilings in rupees and the ratio at which the alarm fires."""

    tenant_monthly_inr: Decimal
    feature_monthly_inr: Decimal
    alarm_ratio: Decimal

    def __post_init__(self) -> None:
        require_positive_decimal(self.tenant_monthly_inr, "tenant_monthly_inr")
        require_positive_decimal(self.feature_monthly_inr, "feature_monthly_inr")
        ratio = require_positive_decimal(self.alarm_ratio, "alarm_ratio")
        if ratio > 1:
            raise InvariantViolationError(f"alarm_ratio must be within (0, 1], got {ratio}")

    def limit_for(self, scope: BudgetScope) -> Decimal:
        return self.tenant_monthly_inr if scope is BudgetScope.TENANT else self.feature_monthly_inr


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """How much of one budget a tenant or feature has used in a month."""

    scope: BudgetScope
    key: str
    month: date
    spent_inr: Decimal
    limit_inr: Decimal
    alarm_ratio: Decimal

    def __post_init__(self) -> None:
        require_instance(self.scope, BudgetScope, "scope")
        require_instance(self.key, str, "key")
        require_month(self.month, "month")
        require_decimal(self.spent_inr, "spent_inr", minimum=Decimal(0))
        require_positive_decimal(self.limit_inr, "limit_inr")
        require_positive_decimal(self.alarm_ratio, "alarm_ratio")

    @property
    def ratio(self) -> Decimal:
        """Spent over limit; above 1 once exceeded."""
        return self.spent_inr / self.limit_inr

    @property
    def alarmed(self) -> bool:
        return self.ratio >= self.alarm_ratio

    @property
    def exceeded(self) -> bool:
        return self.spent_inr >= self.limit_inr


def require_month(value: object, name: str) -> date:
    """Return ``value`` when it is the first day of a month."""
    month = require_date(value, name)
    if month.day != 1:
        raise InvariantViolationError(f"{name} must be the first day of a month, got {month}")
    return month


def month_of(at: datetime) -> date:
    """The UTC month an instant falls in, as its first day."""
    utc = require_aware(at, "at").astimezone(UTC)
    return date(utc.year, utc.month, 1)


def month_bounds(month: date) -> tuple[datetime, datetime]:
    """``[start, end)`` of a month as aware UTC instants."""
    first = require_month(month, "month")
    start = datetime(first.year, first.month, 1, tzinfo=UTC)
    return start, next_month_start(first)


def next_month_start(month: date) -> datetime:
    """The first instant of the following month, UTC."""
    first = require_month(month, "month")
    if first.month == 12:
        return datetime(first.year + 1, 1, 1, tzinfo=UTC)
    return datetime(first.year, first.month + 1, 1, tzinfo=UTC)


def budget_scopes(
    tenant_id: TenantId | None, feature: Feature
) -> tuple[tuple[BudgetScope, str], ...]:
    """The budgets a call is checked against: the tenant's when there is one, then the feature's."""
    require_instance(feature, Feature, "feature")
    scopes: list[tuple[BudgetScope, str]] = []
    if tenant_id is not None:
        require_instance(tenant_id, TenantId, "tenant_id")
        scopes.append((BudgetScope.TENANT, str(tenant_id)))
    scopes.append((BudgetScope.FEATURE, feature.value))
    return tuple(scopes)
