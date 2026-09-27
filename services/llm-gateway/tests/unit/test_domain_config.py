from decimal import Decimal
from types import MappingProxyType

import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.budgets import BudgetLimits
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.features import Feature
from llm_gateway.domain.pricing import PRICE_TABLE, ModelPrice
from llm_gateway.domain.routing import DEFAULT_ROUTES, RoutingTable

LIMITS = BudgetLimits(Decimal("1500"), Decimal("20000"), Decimal("0.8"))


def test_default_config() -> None:
    config = GatewayConfig.default()
    assert config.routes == dict(DEFAULT_ROUTES)
    assert config.budgets == LIMITS
    assert config.usd_inr == Decimal("88.00")
    assert config.allow_unregistered_prompts is False
    assert config.price_table == PRICE_TABLE
    assert isinstance(config.routes, MappingProxyType)
    assert isinstance(config.price_table, MappingProxyType)


def test_overridden_routes_and_table() -> None:
    routing = RoutingTable.default().with_overrides({"qa": "zai/glm-4.7-flash"})
    table = {"zai/glm-4.7-flash": ModelPrice(Decimal("1"), Decimal("2"))}
    config = GatewayConfig(
        routes=routing.mapping,
        budgets=LIMITS,
        usd_inr=Decimal("90"),
        allow_unregistered_prompts=True,
        price_table=table,
    )
    assert config.routes[Feature.QA].source == "override"
    assert config.price_table == table
    table["x/y"] = ModelPrice(Decimal("0"), Decimal("0"))
    assert "x/y" not in config.price_table


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"routes": {}}, "no route for feature 'extraction'"),
        ({"budgets": None}, "budgets must be BudgetLimits"),
        ({"usd_inr": Decimal("0")}, "usd_inr must be positive"),
        ({"usd_inr": 88.0}, "usd_inr must be a finite Decimal"),
        ({"allow_unregistered_prompts": 0}, "allow_unregistered_prompts must be bool"),
        (
            {"price_table": [("fake/echo", ModelPrice(Decimal(1), Decimal(1)))]},
            "price_table must be",
        ),
        ({"price_table": {1: ModelPrice(Decimal(1), Decimal(1))}}, "price_table key must be str"),
        ({"price_table": {"fake/echo": (1, 1)}}, r"price_table\['fake/echo'\] must be ModelPrice"),
    ],
)
def test_config_invariants(changes: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "routes": DEFAULT_ROUTES,
        "budgets": LIMITS,
        "usd_inr": Decimal("88"),
    }
    fields.update(changes)
    with pytest.raises(InvariantViolationError, match=message):
        GatewayConfig(**fields)  # type: ignore[arg-type]
