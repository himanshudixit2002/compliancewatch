"""Read-side use case: how much of a monthly budget a tenant or feature has used."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from llm_gateway.domain.budgets import (
    BudgetScope,
    BudgetStatus,
    month_of,
    next_month_start,
    require_month,
)
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.features import Feature
from llm_gateway.domain.ledger import CostLedger, LedgerEntry


@dataclass(frozen=True, slots=True)
class UsageReport:
    """One budget's month: the scope it is for, what was spent and when it resets."""

    scope: BudgetScope
    key: str
    month: date
    spent_inr: Decimal
    budget_inr: Decimal
    ratio: Decimal
    alarmed: bool
    resets_at: datetime


class Usage:
    def __init__(
        self, *, ledger: CostLedger, config: GatewayConfig, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._ledger = ledger
        self._config = config
        self._clock = clock

    def spent(
        self,
        *,
        tenant_id: TenantId | None,
        feature: Feature | None,
        month: date | None = None,
    ) -> UsageReport:
        """The tenant's budget when a tenant is given (a feature narrows the sum), else the
        feature's budget. One of the two is required. ``month`` defaults to the current one."""
        month = month_of(self._clock()) if month is None else require_month(month, "month")
        if tenant_id is not None:
            scope, key = BudgetScope.TENANT, str(tenant_id)
        elif feature is not None:
            scope, key = BudgetScope.FEATURE, feature.value
        else:
            raise InvariantViolationError("usage needs a tenant_id or a feature")
        spent = self._ledger.spent_inr(tenant_id=tenant_id, feature=feature, month=month)
        status = BudgetStatus(
            scope=scope,
            key=key,
            month=month,
            spent_inr=spent,
            limit_inr=self._config.budgets.limit_for(scope),
            alarm_ratio=self._config.budgets.alarm_ratio,
        )
        return UsageReport(
            scope=scope,
            key=key,
            month=month,
            spent_inr=status.spent_inr,
            budget_inr=status.limit_inr,
            ratio=status.ratio,
            alarmed=status.alarmed,
            resets_at=next_month_start(month),
        )

    def recent(self, limit: int = 50) -> Sequence[LedgerEntry]:
        """The newest ledger rows, for the operator's eyes."""
        return self._ledger.recent(limit)
