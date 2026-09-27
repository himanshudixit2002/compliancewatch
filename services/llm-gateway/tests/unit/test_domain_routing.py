from types import MappingProxyType

import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.errors import UnknownFeatureError
from llm_gateway.domain.features import Feature
from llm_gateway.domain.routing import (
    DEFAULT_ROUTES,
    MODEL_ID,
    Route,
    RoutingTable,
    parse_route_override,
    provider_for,
    require_model_id,
)

EXPECTED = {
    Feature.EXTRACTION: Route(
        Feature.EXTRACTION,
        "deepseek/deepseek-v4-pro-0813",
        "zai/glm-5.3",
        only=("deepinfra", "parasail", "digitalocean", "morph", "togetherai"),
        has=("structured-output",),
        reasoning_effort="none",
        timeout_seconds=120.0,
    ),
    Feature.JUDGEMENT: Route(
        Feature.JUDGEMENT,
        "alibaba/qwen3.7-flash",
        "deepseek/deepseek-v4-flash-0731",
        only=("alibaba", "runware", "digitalocean"),
        timeout_seconds=20.0,
    ),
    Feature.QA: Route(
        Feature.QA,
        "deepseek/deepseek-v4.1-flash",
        "google/gemini-3.1-flash-lite",
        only=("togetherai", "runware", "deepinfra", "parasail", "fireworks", "google", "vertex"),
        sort="ttft",
        reasoning_effort="none",
        timeout_seconds=8.0,
    ),
    Feature.CLASSIFICATION: Route(
        Feature.CLASSIFICATION,
        "alibaba/qwen3.7-flash",
        "zai/glm-4.7-flash",
        only=("alibaba", "bedrock", "deepinfra"),
        timeout_seconds=15.0,
    ),
    Feature.SMOKE: Route(Feature.SMOKE, "fake/echo", timeout_seconds=5.0),
}


def test_the_five_default_routes() -> None:
    assert dict(DEFAULT_ROUTES) == EXPECTED
    assert all(route.source == "default" for route in DEFAULT_ROUTES.values())
    assert all(route.sort is None for f, route in DEFAULT_ROUTES.items() if f is not Feature.QA)
    assert DEFAULT_ROUTES[Feature.SMOKE].models == ("fake/echo",)
    assert DEFAULT_ROUTES[Feature.QA].models == (
        "deepseek/deepseek-v4.1-flash",
        "google/gemini-3.1-flash-lite",
    )


def test_no_default_route_pins_the_peak_priced_deepseek_hosts() -> None:
    for route in DEFAULT_ROUTES.values():
        assert "deepseek" not in route.only
        assert "alibaba" not in route.only or not route.primary.startswith("deepseek/")


def test_defaults_are_read_only() -> None:
    assert isinstance(DEFAULT_ROUTES, MappingProxyType)
    with pytest.raises(TypeError):
        DEFAULT_ROUTES[Feature.SMOKE] = EXPECTED[Feature.QA]  # type: ignore[index]


@pytest.mark.parametrize(
    ("model", "provider"),
    [("fake/echo", "fake"), ("fake/other-1", "fake"), ("zai/glm-5.3", "vercel")],
)
def test_provider_for(model: str, provider: str) -> None:
    assert provider_for(model) == provider


@pytest.mark.parametrize(
    "model", ["gpt-4", "Fake/echo", "/echo", "fake/", "fake/echo x", "", "a//b"]
)
def test_malformed_model_ids(model: str) -> None:
    with pytest.raises(InvariantViolationError):
        provider_for(model)
    assert not MODEL_ID.fullmatch(model)


def test_require_model_id_names_the_field() -> None:
    with pytest.raises(InvariantViolationError, match="primary must look like creator/model"):
        require_model_id("nope", "primary")
    assert require_model_id("a1/b.2_c-3", "x") == "a1/b.2_c-3"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("zai/glm-5.3", ("zai/glm-5.3", None)),
        (" zai/glm-5.3 , alibaba/qwen3.7-flash ", ("zai/glm-5.3", "alibaba/qwen3.7-flash")),
    ],
)
def test_parse_route_override_ok(text: str, expected: tuple[str, str | None]) -> None:
    assert parse_route_override(text) == expected


@pytest.mark.parametrize("text", ["", "a/b,", ",a/b", "a/b,c/d,e/f", "nope", "a/b,nope"])
def test_parse_route_override_bad(text: str) -> None:
    with pytest.raises(InvariantViolationError):
        parse_route_override(text)


def test_parse_route_override_needs_text() -> None:
    with pytest.raises(InvariantViolationError, match="route override must be str"):
        parse_route_override(None)  # type: ignore[arg-type]


def test_with_overrides_keeps_filters_and_marks_the_source() -> None:
    table = RoutingTable.default().with_overrides(
        {"qa": "alibaba/qwen3.7-flash", "extraction": "zai/glm-5.3, zai/glm-4.7-flash"}
    )
    qa = table[Feature.QA]
    assert (qa.primary, qa.fallback, qa.source) == ("alibaba/qwen3.7-flash", None, "override")
    assert (qa.only, qa.sort, qa.reasoning_effort, qa.timeout_seconds) == (
        EXPECTED[Feature.QA].only,
        "ttft",
        "none",
        8.0,
    )
    extraction = table[Feature.EXTRACTION]
    assert extraction.models == ("zai/glm-5.3", "zai/glm-4.7-flash")
    assert extraction.has == ("structured-output",)
    assert extraction.source == "override"
    assert table[Feature.SMOKE] == EXPECTED[Feature.SMOKE]
    assert RoutingTable.default()[Feature.QA].source == "default"


def test_with_overrides_rejects_unknown_features_and_bad_models() -> None:
    with pytest.raises(UnknownFeatureError, match="unknown feature 'summary'"):
        RoutingTable.default().with_overrides({"summary": "zai/glm-5.3"})
    with pytest.raises(UnknownFeatureError, match="unknown feature 'QA'"):
        RoutingTable.default().with_overrides({"QA": "zai/glm-5.3"})
    with pytest.raises(InvariantViolationError, match="fallback must differ from primary"):
        RoutingTable.default().with_overrides({"qa": "zai/glm-5.3,zai/glm-5.3"})
    with pytest.raises(InvariantViolationError):
        RoutingTable.default().with_overrides({"qa": "glm"})


def test_routes_in_feature_order_and_read_only_mapping() -> None:
    table = RoutingTable.default()
    assert [route.feature for route in table.routes()] == list(Feature)
    assert table.mapping == dict(DEFAULT_ROUTES)
    assert isinstance(table.mapping, MappingProxyType)
    assert table.with_overrides({}) == table


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"feature": "qa"}, "feature must be Feature"),
        ({"primary": "glm"}, "primary must look like creator/model"),
        ({"fallback": "glm"}, "fallback must look like creator/model"),
        ({"fallback": "zai/glm-5.3"}, "fallback must differ from primary"),
        ({"only": "deepinfra"}, "only must be a sequence of names"),
        ({"only": ("deepinfra", "")}, "only entry must not be blank"),
        ({"has": ["structured-output", 3]}, "has entry must be str"),
        ({"sort": "price"}, "sort must be one of cost, ttft"),
        ({"reasoning_effort": "max"}, "reasoning_effort must be one of"),
        ({"timeout_seconds": 0}, "timeout_seconds must be positive"),
        ({"timeout_seconds": float("inf")}, "timeout_seconds must be a finite number"),
        ({"source": "env"}, "source must be default or override"),
    ],
)
def test_route_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {"feature": Feature.QA, "primary": "zai/glm-5.3"}
    fields.update(kwargs)
    with pytest.raises(InvariantViolationError, match=message):
        Route(**fields)  # type: ignore[arg-type]


def test_route_coerces_name_sequences_to_tuples() -> None:
    route = Route(Feature.QA, "zai/glm-5.3", only=["a", "b"], has=["x"])  # type: ignore[arg-type]
    assert route.only == ("a", "b")
    assert route.has == ("x",)


def test_routing_table_invariants() -> None:
    routes = dict(DEFAULT_ROUTES)
    del routes[Feature.SMOKE]
    with pytest.raises(InvariantViolationError, match="no route for feature 'smoke'"):
        RoutingTable(routes)
    swapped = dict(DEFAULT_ROUTES)
    swapped[Feature.SMOKE] = DEFAULT_ROUTES[Feature.QA]
    with pytest.raises(InvariantViolationError, match="route under 'smoke' is for 'qa'"):
        RoutingTable(swapped)
    extra: dict[object, Route] = dict(DEFAULT_ROUTES.items())
    extra["other"] = DEFAULT_ROUTES[Feature.SMOKE]
    with pytest.raises(InvariantViolationError, match="keyed by Feature only"):
        RoutingTable(extra)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="route for smoke must be Route"):
        RoutingTable({**DEFAULT_ROUTES, Feature.SMOKE: "fake/echo"})  # type: ignore[dict-item]
    with pytest.raises(InvariantViolationError, match="routes must be a mapping"):
        RoutingTable([])  # type: ignore[arg-type]


def test_model_ids_are_bounded_for_the_ledger() -> None:
    with pytest.raises(InvariantViolationError, match="at most 120"):
        RoutingTable.default().with_overrides({"smoke": "fake/" + "m" * 130})
