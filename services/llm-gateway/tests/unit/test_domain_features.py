import pytest

from llm_gateway.domain.errors import UnknownFeatureError
from llm_gateway.domain.features import CallStatus, CostSource, Feature, parse_feature


def test_feature_values_are_the_five_callers() -> None:
    assert [feature.value for feature in Feature] == [
        "extraction",
        "judgement",
        "qa",
        "classification",
        "smoke",
    ]
    assert Feature.QA.value == "qa"
    assert Feature("qa") is Feature.QA
    assert str(Feature.SMOKE) == "smoke"


@pytest.mark.parametrize("feature", list(Feature))
def test_parse_feature_accepts_every_name(feature: Feature) -> None:
    assert parse_feature(feature.value) is feature
    assert parse_feature(feature) is feature


@pytest.mark.parametrize("text", ["", "Extraction", "extract", "qa "])
def test_parse_feature_rejects_unknown_names(text: str) -> None:
    with pytest.raises(UnknownFeatureError, match=f"unknown feature {text!r}") as info:
        parse_feature(text)
    assert info.value.feature == text
    assert isinstance(info.value, ValueError)


def test_cost_source_and_call_status_values() -> None:
    assert [source.value for source in CostSource] == ["gateway", "estimate", "cache"]
    assert [status.value for status in CallStatus] == ["ok", "error"]
