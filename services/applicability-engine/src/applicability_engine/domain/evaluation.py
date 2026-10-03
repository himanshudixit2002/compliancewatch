"""Deterministic evaluation of a specification against a profile's attributes.

Every predicate in the tree is judged, left to right, and the tree combines the outcomes with
the kernel's three-valued logic. A predicate is unsure, never guessed, when it is free text (a
model or a person has to judge it), when the profile has not set its attribute, when the
attribute is not in the ontology this engine runs with, or when the ontology refuses to compare
(an operator the attribute's type does not allow, a value it does not accept). The decision is
certain (confidence 1) when the tree resolves to applies or not_applicable, which three-valued
logic can do around an unsure leaf, and has confidence 0 when it is unsure, which sends it to
review.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from domain_kernel.confidence import CERTAIN, ZERO, Confidence
from domain_kernel.errors import InvalidAttributeValueError, InvalidOperatorError
from domain_kernel.ontology import Ontology
from domain_kernel.predicates import (
    Applicability,
    Predicate,
    PredicateKind,
    PredicateResult,
    Specification,
    evaluate_predicate,
)


@dataclass(frozen=True, slots=True)
class Evaluation:
    result: Applicability
    confidence: Confidence
    evaluated: tuple[PredicateResult, ...]


def evaluate(
    specification: Specification, attributes: Mapping[str, object], ontology: Ontology
) -> Evaluation:
    evaluated: list[PredicateResult] = []

    def leaf(predicate: Predicate) -> Applicability:
        judged = judge(predicate, attributes, ontology)
        evaluated.append(judged)
        return judged.outcome

    result = specification.evaluate_with(leaf)
    confidence = ZERO if result is Applicability.UNSURE else CERTAIN
    return Evaluation(result, confidence, tuple(evaluated))


def judge(
    predicate: Predicate, attributes: Mapping[str, object], ontology: Ontology
) -> PredicateResult:
    """One predicate's outcome with its reason; bad data becomes unsure, not an error."""
    if predicate.kind is PredicateKind.STRUCTURED and predicate.attribute not in ontology:
        return PredicateResult(
            predicate,
            Applicability.UNSURE,
            ZERO,
            f"{predicate.attribute} is not in ontology {ontology.version}",
        )
    try:
        return evaluate_predicate(predicate, attributes, ontology)
    except (InvalidAttributeValueError, InvalidOperatorError) as exc:
        return PredicateResult(
            predicate, Applicability.UNSURE, ZERO, f"cannot compare: {exc.detail}"
        )
