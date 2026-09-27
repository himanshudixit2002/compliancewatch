"""Events the gateway emits and the publisher protocol that carries them."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import ClassVar, Protocol

from domain_kernel._validation import require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import CorrelationId
from llm_gateway.domain.budgets import BudgetScope, require_month
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.pricing import require_decimal, require_positive_decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class LLMCallCompleted(DomainEvent):
    """A call succeeded (live or from cache) and its ledger row is written."""

    topic: ClassVar[str] = "llm.call.completed"

    entry: LedgerEntry

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.entry, LedgerEntry, "entry")


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetAlarmed(DomainEvent):
    """A tenant or feature crossed the alarm ratio of its monthly budget. Emitted once per month."""

    topic: ClassVar[str] = "llm.budget.alarmed"

    scope: BudgetScope
    key: str
    month: date
    spent_inr: Decimal
    limit_inr: Decimal
    ratio: Decimal

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.scope, BudgetScope, "scope")
        require_instance(self.key, str, "key")
        require_month(self.month, "month")
        require_decimal(self.spent_inr, "spent_inr", minimum=Decimal(0))
        require_positive_decimal(self.limit_inr, "limit_inr")
        require_decimal(self.ratio, "ratio", minimum=Decimal(0))


class EventPublisher(Protocol):
    def publish(self, event: DomainEvent) -> None: ...


def correlation_id_from(text: str) -> CorrelationId:
    """The request's correlation id when it is a UUID (hex or dashed), else a fresh one.

    The ledger row keeps the raw request id either way.
    """
    try:
        return CorrelationId.parse(text)
    except InvariantViolationError:
        return CorrelationId.new()
