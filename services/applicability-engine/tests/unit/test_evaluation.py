"""Deterministic evaluation: every predicate judged, three-valued combination, and anything the
engine cannot decide is unsure rather than a guess or an error."""

import pytest

import ontology as ontology_package
from applicability_engine.domain.evaluation import evaluate, judge
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.ontology import Ontology
from domain_kernel.operators import Operator
from domain_kernel.predicates import AllOf, AnyOf, Applicability, Not, Predicate

REGULAR = Predicate("registration_type", Operator.EQ, "regular")
ABOVE_5_CRORE = Predicate("turnover_band", Operator.GT, "2_crore_to_5_crore")
FREE_TEXT = Predicate(
    "business_category", free_text="Supplies goods through an e-commerce operator"
)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def test_a_structured_predicate_is_decided_with_certainty(ontology: Ontology) -> None:
    applies = judge(REGULAR, {"registration_type": "regular"}, ontology)
    assert (applies.outcome, applies.confidence) == (Applicability.APPLIES, CERTAIN)
    assert applies.reason == "registration_type = regular holds"
    does_not = judge(REGULAR, {"registration_type": "composition"}, ontology)
    assert (does_not.outcome, does_not.confidence) == (Applicability.NOT_APPLICABLE, CERTAIN)


def test_an_ordered_attribute_compares_by_rank(ontology: Ontology) -> None:
    big = {"turnover_band": "5_crore_to_10_crore"}
    small = {"turnover_band": "40_lakh_to_75_lakh"}
    assert judge(ABOVE_5_CRORE, big, ontology).outcome is Applicability.APPLIES
    assert judge(ABOVE_5_CRORE, small, ontology).outcome is Applicability.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("predicate", "attributes", "reason"),
    [
        (FREE_TEXT, {"business_category": "trader"}, "needs judgement: Supplies goods"),
        (REGULAR, {}, "registration_type is not set on the profile"),
        (
            Predicate("headcount_band", Operator.EQ, "small"),
            {"headcount_band": "small"},
            "headcount_band is not in",
        ),
        (
            Predicate("registration_type", Operator.GT, "regular"),
            {"registration_type": "regular"},
            "cannot compare",
        ),
        (REGULAR, {"registration_type": "bogus"}, "cannot compare"),
    ],
    ids=["free-text", "unset", "unknown-attribute", "operator-not-allowed", "invalid-value"],
)
def test_what_cannot_be_decided_is_unsure_and_needs_review(
    ontology: Ontology, predicate: Predicate, attributes: dict[str, object], reason: str
) -> None:
    judged = judge(predicate, attributes, ontology)
    assert (judged.outcome, judged.confidence) == (Applicability.UNSURE, ZERO)
    assert judged.needs_review
    assert judged.reason.startswith(reason)


def test_every_predicate_is_recorded_left_to_right(ontology: Ontology) -> None:
    specification = AllOf((REGULAR, Not(FREE_TEXT), ABOVE_5_CRORE))
    evaluation = evaluate(specification, {"registration_type": "regular"}, ontology)
    assert [item.predicate for item in evaluation.evaluated] == [REGULAR, FREE_TEXT, ABOVE_5_CRORE]
    assert evaluation.result is Applicability.UNSURE
    assert evaluation.confidence == ZERO


def test_three_valued_logic_can_decide_around_an_unsure_predicate(ontology: Ontology) -> None:
    attributes = {"registration_type": "composition"}
    all_of = evaluate(AllOf((FREE_TEXT, REGULAR)), attributes, ontology)
    assert (all_of.result, all_of.confidence) == (Applicability.NOT_APPLICABLE, CERTAIN)
    any_of = evaluate(AnyOf((FREE_TEXT, Not(REGULAR))), attributes, ontology)
    assert (any_of.result, any_of.confidence) == (Applicability.APPLIES, CERTAIN)
    assert [item.outcome for item in any_of.evaluated] == [
        Applicability.UNSURE,
        Applicability.NOT_APPLICABLE,
    ]
