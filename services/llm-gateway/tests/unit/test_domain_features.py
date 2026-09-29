import pytest

from llm_gateway.domain.errors import FeatureMismatchError, UnknownFeatureError
from llm_gateway.domain.features import (
    EMBEDDING_FEATURES,
    CallKind,
    CallStatus,
    CostSource,
    Feature,
    kind_of,
    parse_feature,
    require_kind,
)


def test_feature_values_are_the_six_callers() -> None:
    assert [feature.value for feature in Feature] == [
        "extraction",
        "judgement",
        "qa",
        "classification",
        "smoke",
        "retrieval",
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


def test_retrieval_is_the_only_embedding_feature() -> None:
    assert [kind.value for kind in CallKind] == ["completion", "embedding"]
    assert frozenset({Feature.RETRIEVAL}) == EMBEDDING_FEATURES
    assert kind_of(Feature.RETRIEVAL) is CallKind.EMBEDDING
    assert {kind_of(f) for f in Feature if f is not Feature.RETRIEVAL} == {CallKind.COMPLETION}


def test_require_kind_refuses_the_other_route() -> None:
    assert require_kind(Feature.QA, CallKind.COMPLETION) is Feature.QA
    assert require_kind(Feature.RETRIEVAL, CallKind.EMBEDDING) is Feature.RETRIEVAL
    with pytest.raises(FeatureMismatchError, match="'retrieval' is not served by completion"):
        require_kind(Feature.RETRIEVAL, CallKind.COMPLETION)
    with pytest.raises(FeatureMismatchError) as info:
        require_kind(Feature.QA, CallKind.EMBEDDING)
    assert (info.value.feature, info.value.kind) == ("qa", "embedding")
    assert isinstance(info.value, ValueError)
