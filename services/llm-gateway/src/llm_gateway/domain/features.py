"""The features that call a model, and the small enums the ledger records per call."""

from enum import StrEnum

from llm_gateway.domain.errors import FeatureMismatchError, UnknownFeatureError


class Feature(StrEnum):
    """What a call is for. Routing, budgets and the ledger are keyed by it."""

    EXTRACTION = "extraction"
    JUDGEMENT = "judgement"
    QA = "qa"
    CLASSIFICATION = "classification"
    SMOKE = "smoke"
    RETRIEVAL = "retrieval"


class CallKind(StrEnum):
    """What a call asks the model for: text from a prompt, or vectors for retrieval."""

    COMPLETION = "completion"
    EMBEDDING = "embedding"


EMBEDDING_FEATURES: frozenset[Feature] = frozenset({Feature.RETRIEVAL})
"""Features served by the embeddings route; every other feature is a completion."""


class CostSource(StrEnum):
    """Where a call's cost figure came from."""

    GATEWAY = "gateway"
    ESTIMATE = "estimate"
    CACHE = "cache"


class CallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


def parse_feature(text: str) -> Feature:
    """The feature named by ``text``; an unknown name is an ``UnknownFeatureError``."""
    try:
        return Feature(text)
    except ValueError as exc:
        raise UnknownFeatureError(text) from exc


def kind_of(feature: Feature) -> CallKind:
    """The kind of call ``feature`` is served by."""
    return CallKind.EMBEDDING if feature in EMBEDDING_FEATURES else CallKind.COMPLETION


def require_kind(feature: Feature, kind: CallKind) -> Feature:
    """``feature`` when ``kind`` calls serve it; otherwise a ``FeatureMismatchError``."""
    if kind_of(feature) is not kind:
        raise FeatureMismatchError(feature.value, kind.value)
    return feature
