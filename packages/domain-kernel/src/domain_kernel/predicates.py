"""Predicates and the specification algebra rules are written in.

Evaluation is three-valued. A predicate applies, does not apply, or is unsure: unsure comes
from a free-text predicate (a model or a person has to judge it) or from a profile that has
not set the attribute yet. AllOf and AnyOf combine children with Kleene's strong logic, Not
swaps applies and not_applicable, and unsure stays unsure. Bad data (an unknown attribute, a
disallowed operator, a malformed value) raises instead of becoming a verdict.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from domain_kernel._validation import require_instance, require_text
from domain_kernel.confidence import CERTAIN, ZERO, Confidence
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ontology import ATTRIBUTE_KEY_PATTERN, Ontology, PredicateValue
from domain_kernel.operators import MULTI_VALUE_OPERATORS, Operator


class Applicability(StrEnum):
    """Outcome of evaluating a specification against a profile."""

    APPLIES = "applies"
    NOT_APPLICABLE = "not_applicable"
    UNSURE = "unsure"


class PredicateKind(StrEnum):
    STRUCTURED = "structured"
    FREE_TEXT = "free_text"


def negate(result: Applicability) -> Applicability:
    """Kleene NOT: swaps applies and not_applicable, keeps unsure."""
    match result:
        case Applicability.APPLIES:
            return Applicability.NOT_APPLICABLE
        case Applicability.NOT_APPLICABLE:
            return Applicability.APPLIES
        case Applicability.UNSURE:  # pragma: no branch
            return Applicability.UNSURE


def conjoin(results: Iterable[Applicability]) -> Applicability:
    """Kleene AND: any not_applicable wins, then any unsure, else applies (empty is applies)."""
    outcomes = tuple(results)
    if Applicability.NOT_APPLICABLE in outcomes:
        return Applicability.NOT_APPLICABLE
    if Applicability.UNSURE in outcomes:
        return Applicability.UNSURE
    return Applicability.APPLIES


def disjoin(results: Iterable[Applicability]) -> Applicability:
    """Kleene OR: any applies wins, then any unsure, else not_applicable (empty is that)."""
    outcomes = tuple(results)
    if Applicability.APPLIES in outcomes:
        return Applicability.APPLIES
    if Applicability.UNSURE in outcomes:
        return Applicability.UNSURE
    return Applicability.NOT_APPLICABLE


type LeafEvaluator = Callable[[Predicate], Applicability]
"""Decides one predicate. The engine supplies deterministic or model-backed leaves."""


class Specification(ABC):
    """A rule's applicability condition: one predicate or a tree of them."""

    __slots__ = ()

    @abstractmethod
    def evaluate_with(self, leaf: LeafEvaluator) -> Applicability:
        """Evaluate the tree with ``leaf`` deciding each predicate."""

    @abstractmethod
    def predicates(self) -> Iterator[Predicate]:
        """Every predicate in the tree, left to right."""

    def evaluate(self, attributes: Mapping[str, object], ontology: Ontology) -> Applicability:
        """Evaluate against a profile with the ontology deciding each structured predicate."""
        return self.evaluate_with(lambda predicate: predicate.evaluate(attributes, ontology))

    def is_satisfied_by(self, attributes: Mapping[str, object], ontology: Ontology) -> bool:
        """True only when the outcome is applies; unsure is not satisfaction."""
        return self.evaluate(attributes, ontology) is Applicability.APPLIES

    def referenced_attributes(self) -> frozenset[str]:
        return frozenset(predicate.attribute for predicate in self.predicates())


@dataclass(frozen=True, slots=True)
class Predicate(Specification):
    """One condition on one attribute.

    Structured: ``attribute operator value``. Free text: ``free_text`` says what has to be
    judged; an operator and value may accompany it as a hint but never decide the outcome.
    """

    attribute: str
    operator: Operator | None = None
    value: PredicateValue | None = None
    free_text: str = ""

    def __post_init__(self) -> None:
        attribute = require_text(self.attribute, "attribute")
        if not ATTRIBUTE_KEY_PATTERN.fullmatch(attribute):
            raise InvariantViolationError(f"attribute {attribute!r} must be lowercase snake_case")
        free_text = require_instance(self.free_text, str, "free_text")
        if free_text != free_text.strip():
            raise InvariantViolationError("free_text must not have leading or trailing whitespace")
        if (self.operator is None) != (self.value is None):
            raise InvariantViolationError("operator and value must be given together")
        if self.operator is None:
            if not free_text:
                raise InvariantViolationError(
                    "a predicate needs an operator and value or free text"
                )
            return
        operator = require_instance(self.operator, Operator, "operator")
        if operator in MULTI_VALUE_OPERATORS:
            if not isinstance(self.value, tuple) or not self.value:
                raise InvariantViolationError(f"{operator.value} needs a non-empty tuple of values")
            for item in self.value:
                _require_scalar(item)
        else:
            _require_scalar(self.value)

    @property
    def kind(self) -> PredicateKind:
        return PredicateKind.FREE_TEXT if self.free_text else PredicateKind.STRUCTURED

    def evaluate(self, attributes: Mapping[str, object], ontology: Ontology) -> Applicability:
        """Unsure for free text or a missing attribute; otherwise the ontology's comparison."""
        operator, expected = self.operator, self.value
        if self.free_text or operator is None or expected is None:
            return Applicability.UNSURE
        actual = attributes.get(self.attribute)
        if actual is None:
            return Applicability.UNSURE
        if ontology.compare(self.attribute, operator, actual, expected):
            return Applicability.APPLIES
        return Applicability.NOT_APPLICABLE

    def evaluate_with(self, leaf: LeafEvaluator) -> Applicability:
        return leaf(self)

    def predicates(self) -> Iterator[Predicate]:
        yield self

    def describe(self) -> str:
        """Short human-readable form, such as ``turnover_band >= 5_crore_to_10_crore``."""
        operator, expected = self.operator, self.value
        if self.free_text or operator is None or expected is None:
            return f'free text: "{self.free_text}"'
        return f"{self.attribute} {operator.symbol} {_format(expected)}"


@dataclass(frozen=True, slots=True)
class AllOf(Specification):
    """Applies when every child applies. Empty is applies."""

    items: tuple[Specification, ...]

    def __post_init__(self) -> None:
        _require_specifications(self.items, "AllOf.items")

    def evaluate_with(self, leaf: LeafEvaluator) -> Applicability:
        return conjoin(item.evaluate_with(leaf) for item in self.items)

    def predicates(self) -> Iterator[Predicate]:
        for item in self.items:
            yield from item.predicates()


@dataclass(frozen=True, slots=True)
class AnyOf(Specification):
    """Applies when at least one child applies. Empty is not_applicable."""

    items: tuple[Specification, ...]

    def __post_init__(self) -> None:
        _require_specifications(self.items, "AnyOf.items")

    def evaluate_with(self, leaf: LeafEvaluator) -> Applicability:
        return disjoin(item.evaluate_with(leaf) for item in self.items)

    def predicates(self) -> Iterator[Predicate]:
        for item in self.items:
            yield from item.predicates()


@dataclass(frozen=True, slots=True)
class Not(Specification):
    """Swaps applies and not_applicable; unsure stays unsure."""

    item: Specification

    def __post_init__(self) -> None:
        _require_specification(self.item, "Not.item")

    def evaluate_with(self, leaf: LeafEvaluator) -> Applicability:
        return negate(self.item.evaluate_with(leaf))

    def predicates(self) -> Iterator[Predicate]:
        yield from self.item.predicates()


@dataclass(frozen=True, slots=True)
class PredicateResult:
    """Outcome of one predicate with the confidence behind it and a short reason."""

    predicate: Predicate
    outcome: Applicability
    confidence: Confidence
    reason: str = ""

    def __post_init__(self) -> None:
        require_instance(self.predicate, Predicate, "predicate")
        require_instance(self.outcome, Applicability, "outcome")
        require_instance(self.confidence, Confidence, "confidence")
        require_instance(self.reason, str, "reason")

    @property
    def needs_review(self) -> bool:
        return self.outcome is Applicability.UNSURE or self.confidence.needs_review()


def evaluate_predicate(
    predicate: Predicate, attributes: Mapping[str, object], ontology: Ontology
) -> PredicateResult:
    """Deterministic leaf evaluation with a reason attached."""
    if predicate.kind is PredicateKind.FREE_TEXT:
        return PredicateResult(
            predicate, Applicability.UNSURE, ZERO, f"needs judgement: {predicate.free_text}"
        )
    if attributes.get(predicate.attribute) is None:
        return PredicateResult(
            predicate,
            Applicability.UNSURE,
            ZERO,
            f"{predicate.attribute} is not set on the profile",
        )
    outcome = predicate.evaluate(attributes, ontology)
    verdict = "holds" if outcome is Applicability.APPLIES else "does not hold"
    return PredicateResult(predicate, outcome, CERTAIN, f"{predicate.describe()} {verdict}")


def _require_scalar(value: object) -> None:
    if isinstance(value, datetime) or not isinstance(value, str | int | bool | Decimal | date):
        raise InvariantViolationError(
            f"predicate values must be str, int, bool, Decimal or date, got "
            f"{value.__class__.__name__}"
        )


def _require_specification(value: object, name: str) -> Specification:
    if not isinstance(value, Specification):
        raise InvariantViolationError(
            f"{name} must be a Specification, got {value.__class__.__name__}"
        )
    return value


def _require_specifications(items: object, name: str) -> None:
    for index, item in enumerate(require_instance(items, tuple, name)):
        _require_specification(item, f"{name}[{index}]")


def _format(value: PredicateValue) -> str:
    if isinstance(value, tuple):
        return "(" + ", ".join(str(item) for item in value) + ")"
    return str(value)
