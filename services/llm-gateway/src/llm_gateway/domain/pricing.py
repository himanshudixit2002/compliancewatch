"""Money: quantisation rules, the fallback price table and the cost of one call.

The upstream gateway reports the actual USD cost of most calls; the table below is the estimate
used when it does not (the fake provider, a missing field). INR is the ledger currency.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

from domain_kernel._validation import require_bool, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.features import CostSource

USD_PLACES = Decimal("0.000001")
INR_PLACES = Decimal("0.0001")
_ONE_MILLION = Decimal(1_000_000)


def require_decimal(value: object, name: str, *, minimum: Decimal | None = None) -> Decimal:
    """Return ``value`` when it is a finite Decimal of at least ``minimum``."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolationError(f"{name} must be a finite Decimal, got {value!r}")
    if minimum is not None and value < minimum:
        raise InvariantViolationError(f"{name} must be at least {minimum}, got {value}")
    return value


def require_positive_decimal(value: object, name: str) -> Decimal:
    """Return ``value`` when it is a finite Decimal above zero."""
    decimal = require_decimal(value, name)
    if decimal <= 0:
        raise InvariantViolationError(f"{name} must be positive, got {decimal}")
    return decimal


def quantize_usd(value: Decimal) -> Decimal:
    """Six decimal places, half up: the precision of the ledger's ``cost_usd`` column."""
    return value.quantize(USD_PLACES, rounding=ROUND_HALF_UP)


def quantize_inr(value: Decimal) -> Decimal:
    """Four decimal places, half up: the precision of the ledger's ``cost_inr`` column."""
    return value.quantize(INR_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """List price in USD per million tokens, input and output."""

    input_per_million_usd: Decimal
    output_per_million_usd: Decimal

    def __post_init__(self) -> None:
        require_decimal(self.input_per_million_usd, "input_per_million_usd", minimum=Decimal(0))
        require_decimal(self.output_per_million_usd, "output_per_million_usd", minimum=Decimal(0))


def _price(input_usd: str, output_usd: str) -> ModelPrice:
    return ModelPrice(Decimal(input_usd), Decimal(output_usd))


PRICE_TABLE: Mapping[str, ModelPrice] = MappingProxyType(
    {
        "deepseek/deepseek-v4-pro-0813": _price("0.60", "1.80"),
        "zai/glm-5.3": _price("0.50", "1.50"),
        "alibaba/qwen3.7-flash": _price("0.08", "0.30"),
        "deepseek/deepseek-v4-flash-0731": _price("0.10", "0.40"),
        "deepseek/deepseek-v4.1-flash": _price("0.10", "0.40"),
        "google/gemini-3.1-flash-lite": _price("0.10", "0.40"),
        "zai/glm-4.7-flash": _price("0.07", "0.25"),
        "fake/echo": _price("0.10", "0.40"),
        # An estimate: nothing in the repo sources a Voyage price. Check it before trusting
        # the ledger for retrieval; the gateway's reported cost wins whenever it gives one.
        "voyage/voyage-3.5-lite": _price("0.02", "0"),
        "fake/hash-ngram-512": _price("0.10", "0"),
    }
)
"""Estimates pinned on 2026-09-27; only used when the gateway omits the actual cost.

Embedding models price input tokens only. The fake embedder has a price so budgets bite in tests.
"""

DEFAULT_PRICE = _price("1.00", "3.00")
"""A deliberately high estimate for a model the table does not know."""


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    table: Mapping[str, ModelPrice] = PRICE_TABLE,
) -> Decimal:
    """List-price cost of a call, quantised to ``USD_PLACES``."""
    require_text(model, "model")
    require_int(input_tokens, "input_tokens", minimum=0)
    require_int(output_tokens, "output_tokens", minimum=0)
    price = table.get(model, DEFAULT_PRICE)
    usd = (
        input_tokens * price.input_per_million_usd + output_tokens * price.output_per_million_usd
    ) / _ONE_MILLION
    return quantize_usd(usd)


def usd_to_inr(usd: Decimal, rate: Decimal) -> Decimal:
    """Convert at ``rate`` rupees per dollar, quantised to ``INR_PLACES``."""
    require_decimal(usd, "usd", minimum=Decimal(0))
    require_positive_decimal(rate, "rate")
    return quantize_inr(usd * rate)


@dataclass(frozen=True, slots=True)
class Cost:
    """What one call cost and where the figure came from.

    ``usd`` is optional because the ledger column is nullable; every path here fills it.
    """

    usd: Decimal | None
    inr: Decimal
    source: CostSource

    def __post_init__(self) -> None:
        if self.usd is not None:
            require_decimal(self.usd, "usd", minimum=Decimal(0))
        require_decimal(self.inr, "inr", minimum=Decimal(0))
        if not isinstance(self.source, CostSource):
            raise InvariantViolationError(f"source must be a CostSource, got {self.source!r}")


def cost_for(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    gateway_cost_usd: Decimal | None,
    cached: bool,
    usd_inr: Decimal,
    table: Mapping[str, ModelPrice] = PRICE_TABLE,
) -> Cost:
    """The cost to book: zero for a cache hit, the gateway's figure when given, else an estimate."""
    require_bool(cached, "cached")
    if cached:
        return Cost(quantize_usd(Decimal(0)), quantize_inr(Decimal(0)), CostSource.CACHE)
    if gateway_cost_usd is not None and require_decimal(gateway_cost_usd, "gateway_cost_usd") >= 0:
        usd = quantize_usd(gateway_cost_usd)
        return Cost(usd, usd_to_inr(usd, usd_inr), CostSource.GATEWAY)
    usd = estimate_cost_usd(model, input_tokens, output_tokens, table)
    return Cost(usd, usd_to_inr(usd, usd_inr), CostSource.ESTIMATE)
