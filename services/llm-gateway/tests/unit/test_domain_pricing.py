from decimal import Decimal

import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.features import CostSource
from llm_gateway.domain.pricing import (
    DEFAULT_PRICE,
    INR_PLACES,
    PRICE_TABLE,
    USD_PLACES,
    Cost,
    ModelPrice,
    cost_for,
    estimate_cost_usd,
    quantize_inr,
    quantize_usd,
    require_decimal,
    require_positive_decimal,
    usd_to_inr,
)

RATE = Decimal("88.00")


def test_one_million_tokens_each_way_on_the_fake_model() -> None:
    assert estimate_cost_usd("fake/echo", 1_000_000, 1_000_000) == Decimal("0.500000")
    assert estimate_cost_usd("fake/echo", 0, 0) == Decimal("0.000000")


def test_rounding_is_half_up_at_six_places() -> None:
    assert estimate_cost_usd("fake/echo", 1, 0) == Decimal("0.000000")
    assert estimate_cost_usd("fake/echo", 5, 0) == Decimal("0.000001")
    assert quantize_usd(Decimal("0.0000005")) == Decimal("0.000001")
    assert quantize_inr(Decimal("0.00005")) == Decimal("0.0001")
    assert quantize_usd(Decimal("1")).as_tuple().exponent == USD_PLACES.as_tuple().exponent
    assert quantize_inr(Decimal("1")).as_tuple().exponent == INR_PLACES.as_tuple().exponent


def test_unknown_model_uses_the_high_default_price() -> None:
    assert ModelPrice(Decimal("1.00"), Decimal("3.00")) == DEFAULT_PRICE
    assert estimate_cost_usd("unknown/model", 1_000_000, 1_000_000) == Decimal("4.000000")
    assert estimate_cost_usd("fake/echo", 1_000_000, 0, table={}) == Decimal("1.000000")


def test_price_table_is_pinned_and_read_only() -> None:
    assert set(PRICE_TABLE) == {
        "deepseek/deepseek-v4-pro-0813",
        "zai/glm-5.3",
        "alibaba/qwen3.7-flash",
        "deepseek/deepseek-v4-flash-0731",
        "deepseek/deepseek-v4.1-flash",
        "google/gemini-3.1-flash-lite",
        "zai/glm-4.7-flash",
        "fake/echo",
        "voyage/voyage-3.5-lite",
        "fake/hash-ngram-512",
    }
    assert PRICE_TABLE["zai/glm-5.3"] == ModelPrice(Decimal("0.50"), Decimal("1.50"))
    assert PRICE_TABLE["fake/hash-ngram-512"].input_per_million_usd > 0
    assert PRICE_TABLE["voyage/voyage-3.5-lite"].output_per_million_usd == 0
    with pytest.raises(TypeError):
        PRICE_TABLE["x/y"] = DEFAULT_PRICE  # type: ignore[index]


def test_inr_conversion() -> None:
    assert usd_to_inr(Decimal("0.000123"), RATE) == Decimal("0.0108")
    assert usd_to_inr(Decimal("1"), Decimal("88.5")) == Decimal("88.5000")
    assert usd_to_inr(Decimal("0"), RATE) == Decimal("0.0000")


@pytest.mark.parametrize(
    ("usd", "rate", "message"),
    [
        (Decimal("1"), Decimal("0"), "rate must be positive"),
        (Decimal("1"), Decimal("-88"), "rate must be positive"),
        (Decimal("-1"), RATE, "usd must be at least 0"),
        (1.0, RATE, "usd must be a finite Decimal"),
        (Decimal("NaN"), RATE, "usd must be a finite Decimal"),
        (Decimal("1"), 88, "rate must be a finite Decimal"),
    ],
)
def test_conversion_rejects_bad_money(usd: object, rate: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        usd_to_inr(usd, rate)  # type: ignore[arg-type]


def test_estimate_rejects_bad_inputs() -> None:
    with pytest.raises(InvariantViolationError, match="input_tokens must be at least 0"):
        estimate_cost_usd("fake/echo", -1, 0)
    with pytest.raises(InvariantViolationError, match="output_tokens must be an integer"):
        estimate_cost_usd("fake/echo", 0, 1.5)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="model must not be blank"):
        estimate_cost_usd("", 0, 0)


def test_model_price_rejects_negative_and_non_decimal() -> None:
    with pytest.raises(InvariantViolationError, match="input_per_million_usd must be at least 0"):
        ModelPrice(Decimal("-0.1"), Decimal("1"))
    with pytest.raises(InvariantViolationError, match="output_per_million_usd must be a finite"):
        ModelPrice(Decimal("0.1"), 1.0)  # type: ignore[arg-type]
    assert ModelPrice(Decimal("0"), Decimal("0")).input_per_million_usd == 0


def test_require_decimal_helpers() -> None:
    assert require_decimal(Decimal("1.5"), "x") == Decimal("1.5")
    assert require_positive_decimal(Decimal("0.0001"), "x") == Decimal("0.0001")
    with pytest.raises(InvariantViolationError, match="x must be positive, got 0"):
        require_positive_decimal(Decimal("0"), "x")
    with pytest.raises(InvariantViolationError, match="x must be a finite Decimal"):
        require_decimal(Decimal("Infinity"), "x")
    with pytest.raises(InvariantViolationError, match="x must be at least 2"):
        require_decimal(Decimal("1"), "x", minimum=Decimal(2))


def test_cost_for_cache_hit_books_nothing() -> None:
    cost = cost_for(
        model="fake/echo",
        input_tokens=1000,
        output_tokens=100,
        gateway_cost_usd=Decimal("0.5"),
        cached=True,
        usd_inr=RATE,
    )
    assert cost == Cost(Decimal("0.000000"), Decimal("0.0000"), CostSource.CACHE)


def test_cost_for_prefers_the_gateway_figure() -> None:
    cost = cost_for(
        model="unknown/model",
        input_tokens=1000,
        output_tokens=100,
        gateway_cost_usd=Decimal("0.0012345"),
        cached=False,
        usd_inr=RATE,
    )
    assert cost.source is CostSource.GATEWAY
    assert cost.usd == Decimal("0.001235")
    assert cost.inr == Decimal("0.1087")


@pytest.mark.parametrize("gateway_cost", [None, Decimal("-0.01")])
def test_cost_for_estimates_without_a_usable_gateway_figure(gateway_cost: Decimal | None) -> None:
    cost = cost_for(
        model="fake/echo",
        input_tokens=1000,
        output_tokens=52,
        gateway_cost_usd=gateway_cost,
        cached=False,
        usd_inr=RATE,
    )
    assert cost == Cost(Decimal("0.000121"), Decimal("0.0106"), CostSource.ESTIMATE)


def test_cost_for_uses_the_given_table() -> None:
    table = {"fake/echo": ModelPrice(Decimal("10"), Decimal("10"))}
    cost = cost_for(
        model="fake/echo",
        input_tokens=100_000,
        output_tokens=0,
        gateway_cost_usd=None,
        cached=False,
        usd_inr=RATE,
        table=table,
    )
    assert cost.usd == Decimal("1.000000")


def test_cost_for_rejects_bad_flags_and_figures() -> None:
    with pytest.raises(InvariantViolationError, match="cached must be bool"):
        cost_for(
            model="fake/echo",
            input_tokens=1,
            output_tokens=1,
            gateway_cost_usd=None,
            cached=1,  # type: ignore[arg-type]
            usd_inr=RATE,
        )
    with pytest.raises(InvariantViolationError, match="gateway_cost_usd must be a finite Decimal"):
        cost_for(
            model="fake/echo",
            input_tokens=1,
            output_tokens=1,
            gateway_cost_usd=0.5,  # type: ignore[arg-type]
            cached=False,
            usd_inr=RATE,
        )


def test_cost_invariants() -> None:
    assert Cost(None, Decimal("0"), CostSource.ESTIMATE).usd is None
    with pytest.raises(InvariantViolationError, match="usd must be at least 0"):
        Cost(Decimal("-1"), Decimal("0"), CostSource.GATEWAY)
    with pytest.raises(InvariantViolationError, match="inr must be a finite Decimal"):
        Cost(Decimal("1"), 1, CostSource.GATEWAY)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="source must be a CostSource"):
        Cost(Decimal("1"), Decimal("1"), "gateway")  # type: ignore[arg-type]
