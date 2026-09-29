"""Which model serves which feature, with one fallback and the upstream gateway's filters.

Model ids are ``creator/model`` as the Vercel AI Gateway lists them; ``fake/...`` ids go to the
deterministic fake provider. The defaults prefer cheap models and exclude the hosts whose
DeepSeek prices double during Indian business hours. Overrides come from settings; the routes
are judgement, not documentation, and a bake-off on gold documents should confirm them.
An embedding route has no fallback: vectors from two models do not compare.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal, Self

from domain_kernel._validation import require_finite, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.features import EMBEDDING_FEATURES, Feature, parse_feature
from llm_gateway.domain.ledger import MAX_MODEL_ID, require_bounded

MODEL_ID = re.compile(r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*")
"""``creator/model``, lowercase: ``deepseek/deepseek-v4.1-flash``, ``fake/echo``."""

ProviderName = Literal["fake", "vercel"]
RouteSource = Literal["default", "override"]
_SORTS = (None, "cost", "ttft")
_EFFORTS = (None, "none", "low", "medium", "high")


def require_model_id(value: object, name: str) -> str:
    """Return ``value`` when it is a well-formed model id short enough for the ledger."""
    text = require_bounded(require_text(value, name), name, MAX_MODEL_ID, required=True)
    if not MODEL_ID.fullmatch(text):
        raise InvariantViolationError(f"{name} must look like creator/model, got {text!r}")
    return text


def provider_for(model: str) -> ProviderName:
    """The provider that serves a model id: ``fake`` for ``fake/...``, else the gateway."""
    return "fake" if require_model_id(model, "model").startswith("fake/") else "vercel"


@dataclass(frozen=True, slots=True)
class Route:
    """The models and gateway options for one feature.

    ``only`` restricts the upstream hosts, ``has`` demands capabilities such as
    ``structured-output``, ``sort`` picks the cheapest or fastest host, ``reasoning_effort``
    turns thinking off for models that support it. ``fallback`` is tried when the primary fails.
    """

    feature: Feature
    primary: str
    fallback: str | None = None
    only: tuple[str, ...] = ()
    has: tuple[str, ...] = ()
    sort: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float = 30.0
    source: RouteSource = "default"

    def __post_init__(self) -> None:
        require_instance(self.feature, Feature, "feature")
        require_model_id(self.primary, "primary")
        if self.fallback is not None:
            require_model_id(self.fallback, "fallback")
            if self.fallback == self.primary:
                raise InvariantViolationError("fallback must differ from primary")
            if self.feature in EMBEDDING_FEATURES:
                raise InvariantViolationError(
                    f"the {self.feature.value} route takes no fallback: "
                    "vectors from two models do not compare"
                )
        object.__setattr__(self, "only", _names(self.only, "only"))
        object.__setattr__(self, "has", _names(self.has, "has"))
        if self.sort not in _SORTS:
            raise InvariantViolationError(f"sort must be one of cost, ttft, got {self.sort!r}")
        if self.reasoning_effort not in _EFFORTS:
            raise InvariantViolationError(
                f"reasoning_effort must be one of none, low, medium, high, "
                f"got {self.reasoning_effort!r}"
            )
        if require_finite(self.timeout_seconds, "timeout_seconds") <= 0:
            raise InvariantViolationError(
                f"timeout_seconds must be positive, got {self.timeout_seconds}"
            )
        if self.source not in ("default", "override"):
            raise InvariantViolationError(
                f"source must be default or override, got {self.source!r}"
            )

    @property
    def models(self) -> tuple[str, ...]:
        """The primary, then the fallback when there is one."""
        return (self.primary,) if self.fallback is None else (self.primary, self.fallback)


def _names(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvariantViolationError(f"{name} must be a sequence of names")
    return tuple(require_text(item, f"{name} entry") for item in value)


DEFAULT_ROUTES: Mapping[Feature, Route] = MappingProxyType(
    {
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
            only=(
                "togetherai",
                "runware",
                "deepinfra",
                "parasail",
                "fireworks",
                "google",
                "vertex",
            ),
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
        Feature.RETRIEVAL: Route(Feature.RETRIEVAL, "voyage/voyage-3.5-lite", timeout_seconds=15.0),
    }
)


def parse_route_override(text: str) -> tuple[str, str | None]:
    """``primary`` or ``primary,fallback`` from a settings value."""
    require_instance(text, str, "route override")
    ids = [part.strip() for part in text.split(",")]
    if not 1 <= len(ids) <= 2 or not all(ids):
        raise InvariantViolationError(
            f"route override must be 'primary' or 'primary,fallback', got {text!r}"
        )
    primary = require_model_id(ids[0], "primary")
    fallback = require_model_id(ids[1], "fallback") if len(ids) == 2 else None
    return primary, fallback


@dataclass(frozen=True, slots=True)
class RoutingTable:
    """One route per feature. Built from the defaults, then overridden from settings."""

    mapping: Mapping[Feature, Route]

    def __post_init__(self) -> None:
        if not isinstance(self.mapping, Mapping):
            raise InvariantViolationError("routes must be a mapping keyed by Feature")
        routes: dict[Feature, Route] = {}
        for feature in Feature:
            route = self.mapping.get(feature)
            if route is None:
                raise InvariantViolationError(f"no route for feature {feature.value!r}")
            require_instance(route, Route, f"route for {feature.value}")
            if route.feature is not feature:
                raise InvariantViolationError(
                    f"route under {feature.value!r} is for {route.feature.value!r}"
                )
            routes[feature] = route
        if len(self.mapping) != len(routes):
            raise InvariantViolationError("routes must be keyed by Feature only")
        object.__setattr__(self, "mapping", MappingProxyType(routes))

    @classmethod
    def default(cls) -> Self:
        return cls(DEFAULT_ROUTES)

    def with_overrides(self, overrides: Mapping[str, str]) -> Self:
        """Replace the models of the named features; the gateway filters stay.

        A fallback not named in the override is dropped, so ``qa=creator/model`` means
        "that model only". An unknown feature name is an ``UnknownFeatureError``.
        """
        routes = dict(self.mapping)
        for name, text in overrides.items():
            feature = parse_feature(name)
            primary, fallback = parse_route_override(text)
            routes[feature] = replace(
                routes[feature], primary=primary, fallback=fallback, source="override"
            )
        return type(self)(routes)

    def routes(self) -> Sequence[Route]:
        """Every route in ``Feature`` order."""
        return tuple(self.mapping[feature] for feature in Feature)

    def __getitem__(self, feature: Feature) -> Route:
        return self.mapping[feature]
