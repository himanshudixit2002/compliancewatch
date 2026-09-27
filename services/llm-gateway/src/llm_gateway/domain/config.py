"""Everything the use cases read from settings, as one validated value."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Self

from domain_kernel._validation import require_bool, require_instance
from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.budgets import BudgetLimits
from llm_gateway.domain.features import Feature
from llm_gateway.domain.pricing import PRICE_TABLE, ModelPrice, require_positive_decimal
from llm_gateway.domain.routing import DEFAULT_ROUTES, Route, RoutingTable


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    """Routes, budgets, the exchange rate and the price table one gateway instance runs with."""

    routes: Mapping[Feature, Route]
    budgets: BudgetLimits
    usd_inr: Decimal
    allow_unregistered_prompts: bool = False
    price_table: Mapping[str, ModelPrice] = PRICE_TABLE

    def __post_init__(self) -> None:
        object.__setattr__(self, "routes", RoutingTable(self.routes).mapping)
        require_instance(self.budgets, BudgetLimits, "budgets")
        require_positive_decimal(self.usd_inr, "usd_inr")
        require_bool(self.allow_unregistered_prompts, "allow_unregistered_prompts")
        if not isinstance(self.price_table, Mapping):
            raise InvariantViolationError("price_table must be a mapping of model id to price")
        for model, price in self.price_table.items():
            require_instance(model, str, "price_table key")
            require_instance(price, ModelPrice, f"price_table[{model!r}]")
        object.__setattr__(self, "price_table", MappingProxyType(dict(self.price_table)))

    @classmethod
    def default(cls) -> Self:
        """The shipped defaults: 1,500 INR per tenant, 20,000 INR per feature, alarm at 80%."""
        return cls(
            routes=DEFAULT_ROUTES,
            budgets=BudgetLimits(Decimal("1500"), Decimal("20000"), Decimal("0.8")),
            usd_inr=Decimal("88.00"),
        )
