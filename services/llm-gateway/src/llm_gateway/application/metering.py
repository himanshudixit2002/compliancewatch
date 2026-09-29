"""Metering shared by the use cases that call a provider: budgets, ledger bounds, error rows.

One ``BudgetGuard`` is wired into every such use case, so a budget alarm fires once per scope and
month whichever kind of call crossed the ratio.
"""

import logging
import threading
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from domain_kernel.errors import DomainError
from domain_kernel.ids import TenantId
from llm_gateway.domain.budgets import (
    BudgetScope,
    BudgetStatus,
    budget_scopes,
    month_of,
    next_month_start,
)
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.errors import BudgetExceededError
from llm_gateway.domain.events import BudgetAlarmed, EventPublisher, correlation_id_from
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import (
    MAX_CORRELATION_ID,
    MAX_ERROR_TYPE,
    MAX_MODEL_ID,
    CostLedger,
    LedgerEntry,
    require_bounded,
)
from llm_gateway.domain.pricing import Cost, quantize_inr, quantize_usd
from llm_gateway.domain.prompts import PromptRef

log = logging.getLogger(__name__)

ZERO_COST = Cost(quantize_usd(Decimal(0)), quantize_inr(Decimal(0)), CostSource.ESTIMATE)
"""What an error row books: nothing, as an estimate."""


class BudgetGuard:
    """Refuses a call whose tenant or feature budget is used up; alarms once per scope and month.

    Thread-safe. The alarm markers live in the instance, so every use case shares one.
    """

    def __init__(
        self, *, ledger: CostLedger, publisher: EventPublisher, config: GatewayConfig
    ) -> None:
        self._ledger = ledger
        self._publisher = publisher
        self._config = config
        self._alarmed: set[tuple[BudgetScope, str, date]] = set()
        self._alarm_lock = threading.Lock()

    def check(
        self,
        *,
        tenant_id: TenantId | None,
        feature: Feature,
        at: datetime,
        correlation_id: str,
    ) -> None:
        """Raise ``BudgetExceededError`` when a budget of the month ``at`` falls in is spent."""
        month = month_of(at)
        for scope, scope_key in budget_scopes(tenant_id, feature):
            tenant = tenant_id if scope is BudgetScope.TENANT else None
            scoped_feature = feature if scope is BudgetScope.FEATURE else None
            spent = self._ledger.spent_inr(tenant_id=tenant, feature=scoped_feature, month=month)
            status = BudgetStatus(
                scope=scope,
                key=scope_key,
                month=month,
                spent_inr=spent,
                limit_inr=self._config.budgets.limit_for(scope),
                alarm_ratio=self._config.budgets.alarm_ratio,
            )
            if status.exceeded:
                raise BudgetExceededError(
                    f"{scope.value} budget for {scope_key} is used up for {month:%Y-%m}: "
                    f"{status.spent_inr} of {status.limit_inr} INR",
                    scope=scope.value,
                    spent_inr=status.spent_inr,
                    limit_inr=status.limit_inr,
                    resets_at=next_month_start(month),
                )
            if status.alarmed:
                self._alarm_once(status, tenant_id=tenant_id, correlation_id=correlation_id)

    def _alarm_once(
        self, status: BudgetStatus, *, tenant_id: TenantId | None, correlation_id: str
    ) -> None:
        marker = (status.scope, status.key, status.month)
        with self._alarm_lock:
            if marker in self._alarmed:
                return
            self._alarmed.add(marker)
        log.warning(
            "llm budget alarm: %s %s at %.0f%% of %s INR for %s",
            status.scope.value,
            status.key,
            status.ratio * 100,
            status.limit_inr,
            status.month.strftime("%Y-%m"),
        )
        event = BudgetAlarmed(
            scope=status.scope,
            key=status.key,
            month=status.month,
            spent_inr=status.spent_inr,
            limit_inr=status.limit_inr,
            ratio=status.ratio,
            tenant_id=tenant_id,
            correlation_id=correlation_id_from(correlation_id),
        )
        try:
            self._publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed", BudgetAlarmed.topic)


def require_ledger_bounds(models: tuple[str, ...], correlation_id: str) -> None:
    """Refuse what the ledger could not store before anything is spent on the call.

    ``LedgerEntry`` checks the same bounds, but by then the provider has been paid.
    """
    require_bounded(correlation_id, "correlation_id", MAX_CORRELATION_ID)
    for model in models:
        require_bounded(model, "model", MAX_MODEL_ID, required=True)


def error_entry(
    exc: Exception,
    *,
    occurred_at: datetime,
    tenant_id: TenantId | None,
    feature: Feature,
    ref: PromptRef,
    model_requested: str,
    model_served: str,
    provider: str,
    latency_ms: int,
    correlation_id: str,
) -> LedgerEntry:
    """The ledger row of a failed call: zero tokens and cost, the error's slug or class name.

    ``provider`` is the registered name the attempt went to; a failed call has no response to
    name the host that would have served it.
    """
    error_type = exc.type_slug if isinstance(exc, DomainError) else type(exc).__name__
    entry_id = uuid4()
    return LedgerEntry(
        id=entry_id,
        occurred_at=occurred_at,
        tenant_id=tenant_id,
        feature=feature,
        prompt_name=ref.name,
        prompt_version=ref.version,
        model_requested=model_requested,
        model_served=model_served,
        provider=provider,
        input_tokens=0,
        output_tokens=0,
        cached=False,
        cost_usd=ZERO_COST.usd,
        cost_inr=ZERO_COST.inr,
        cost_source=ZERO_COST.source,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
        trace_id=str(entry_id),
        generation_id="",
        status=CallStatus.ERROR,
        error_type=error_type[:MAX_ERROR_TYPE],
    )
