"""The features that call a model, and the small enums the ledger records per call."""

from enum import StrEnum

from llm_gateway.domain.errors import UnknownFeatureError


class Feature(StrEnum):
    """What a call is for. Routing, budgets and the ledger are keyed by it."""

    EXTRACTION = "extraction"
    JUDGEMENT = "judgement"
    QA = "qa"
    CLASSIFICATION = "classification"
    SMOKE = "smoke"


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
