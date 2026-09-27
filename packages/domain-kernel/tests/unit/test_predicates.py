from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from domain_kernel.confidence import CERTAIN, ZERO, Confidence
from domain_kernel.errors import (
    InvalidAttributeValueError,
    InvalidOperatorError,
    InvariantViolationError,
    UnknownAttributeError,
)
from domain_kernel.ontology import Ontology
from domain_kernel.operators import Operator
from domain_kernel.predicates import (
    AllOf,
    AnyOf,
    Applicability,
    Not,
    Predicate,
    PredicateKind,
    PredicateResult,
    Specification,
    conjoin,
    disjoin,
    evaluate_predicate,
    negate,
)

APPLIES, NOT_APPLICABLE, UNSURE = (
    Applicability.APPLIES,
    Applicability.NOT_APPLICABLE,
    Applicability.UNSURE,
)
_PROFILE: dict[str, object] = {
    "registration_type": "regular",
    "turnover_band": "1_5cr_to_5cr",
    "state_codes": ["KA", "MH"],
    "e_commerce_supplier": True,
    "employee_count": 12,
    "annual_turnover_inr": "2500000",
    "registered_on": date(2019, 7, 1),
    "trade_name": "Acme",
}
_REGULAR = Predicate("registration_type", Operator.EQ, "regular")
_COMPOSITION = Predicate("registration_type", Operator.EQ, "composition")
_JUDGEMENT = Predicate("registration_type", free_text="only if the analyst says so")
_MISSING = Predicate("pan_number_missing_from_profile", Operator.EQ, "x")


# ---- construction ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "predicate",
    [
        Predicate("turnover_band", Operator.GTE, "1_5cr_to_5cr"),
        Predicate("state_codes", Operator.CONTAINS_ANY, ("KA", "MH")),
        Predicate("registration_type", Operator.IN, ("regular",)),
        Predicate("e_commerce_supplier", Operator.EQ, True),
        Predicate("employee_count", Operator.LT, 5),
        Predicate("annual_turnover_inr", Operator.GT, Decimal("1.5")),
        Predicate("registered_on", Operator.LTE, date(2020, 1, 1)),
        Predicate("registration_type", free_text="needs judgement"),
        Predicate("registration_type", Operator.EQ, "regular", "with a hint"),
    ],
)
def test_valid_predicates(predicate: Predicate) -> None:
    assert predicate.attribute
    assert isinstance(predicate, Specification)
    assert hash(predicate) == hash(predicate)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"attribute": ""}, "attribute must not be blank"),
        ({"attribute": "Turnover", "operator": Operator.EQ, "value": "x"}, "snake_case"),
        ({"attribute": 3, "operator": Operator.EQ, "value": "x"}, "attribute must be str"),
        ({"attribute": "a"}, "needs an operator and value or free text"),
        ({"attribute": "a", "operator": Operator.EQ}, "given together"),
        ({"attribute": "a", "value": "x"}, "given together"),
        ({"attribute": "a", "operator": "eq", "value": "x"}, "operator must be Operator"),
        ({"attribute": "a", "operator": Operator.IN, "value": "x"}, "non-empty tuple"),
        ({"attribute": "a", "operator": Operator.IN, "value": ()}, "non-empty tuple"),
        ({"attribute": "a", "operator": Operator.CONTAINS_ANY, "value": ("x", [1])}, "got list"),
        ({"attribute": "a", "operator": Operator.EQ, "value": ("x",)}, "got tuple"),
        (
            {"attribute": "a", "operator": Operator.EQ, "value": datetime(2020, 1, 1, tzinfo=UTC)},
            "got datetime",
        ),
        ({"attribute": "a", "operator": Operator.EQ, "value": 1.5}, "got float"),
        ({"attribute": "a", "free_text": " padded "}, "free_text must not have leading"),
        ({"attribute": "a", "free_text": 5}, "free_text must be str"),
    ],
)
def test_invalid_predicates(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        Predicate(**kwargs)  # type: ignore[arg-type]


def test_kind() -> None:
    assert _REGULAR.kind is PredicateKind.STRUCTURED
    assert _JUDGEMENT.kind is PredicateKind.FREE_TEXT
    assert Predicate("a", Operator.EQ, "x", "hint").kind is PredicateKind.FREE_TEXT


# ---- leaf semantics --------------------------------------------------------------------------


def test_structured_leaf_decides(ontology: Ontology) -> None:
    assert _REGULAR.evaluate(_PROFILE, ontology) is APPLIES
    assert _COMPOSITION.evaluate(_PROFILE, ontology) is NOT_APPLICABLE
    assert _REGULAR.is_satisfied_by(_PROFILE, ontology)
    assert not _COMPOSITION.is_satisfied_by(_PROFILE, ontology)


def test_free_text_is_unsure_even_with_a_hint(ontology: Ontology) -> None:
    hinted = Predicate("registration_type", Operator.EQ, "regular", "if the analyst agrees")
    assert _JUDGEMENT.evaluate(_PROFILE, ontology) is UNSURE
    assert hinted.evaluate(_PROFILE, ontology) is UNSURE
    assert not hinted.is_satisfied_by(_PROFILE, ontology)


def test_missing_or_none_attribute_is_unsure(ontology: Ontology) -> None:
    assert _REGULAR.evaluate({}, ontology) is UNSURE
    assert _REGULAR.evaluate({"registration_type": None}, ontology) is UNSURE


def test_malformed_profile_value_raises(ontology: Ontology) -> None:
    with pytest.raises(InvalidAttributeValueError, match="is not one of"):
        _REGULAR.evaluate({"registration_type": "Regular"}, ontology)


def test_unknown_attribute_raises_when_present_in_the_profile(ontology: Ontology) -> None:
    with pytest.raises(UnknownAttributeError, match="pan_number"):
        _MISSING.evaluate({"pan_number_missing_from_profile": "x"}, ontology)


def test_disallowed_operator_raises(ontology: Ontology) -> None:
    with pytest.raises(InvalidOperatorError):
        Predicate("registration_type", Operator.GT, "regular").evaluate(_PROFILE, ontology)


# ---- evaluate_predicate ----------------------------------------------------------------------


def test_evaluate_predicate_outcomes(ontology: Ontology) -> None:
    holds = evaluate_predicate(_REGULAR, _PROFILE, ontology)
    assert holds == PredicateResult(_REGULAR, APPLIES, CERTAIN, "registration_type = regular holds")
    assert not holds.needs_review
    fails = evaluate_predicate(_COMPOSITION, _PROFILE, ontology)
    assert fails.outcome is NOT_APPLICABLE
    assert fails.confidence == CERTAIN
    assert fails.reason == "registration_type = composition does not hold"
    judged = evaluate_predicate(_JUDGEMENT, _PROFILE, ontology)
    assert (judged.outcome, judged.confidence) == (UNSURE, ZERO)
    assert judged.reason == "needs judgement: only if the analyst says so"
    assert judged.needs_review
    missing = evaluate_predicate(_REGULAR, {}, ontology)
    assert (missing.outcome, missing.confidence) == (UNSURE, ZERO)
    assert missing.reason == "registration_type is not set on the profile"


def test_predicate_result_review_and_invariants() -> None:
    assert PredicateResult(_REGULAR, APPLIES, Confidence(0.5)).needs_review
    assert not PredicateResult(_REGULAR, NOT_APPLICABLE, Confidence(0.9)).needs_review
    assert PredicateResult(_REGULAR, UNSURE, CERTAIN).needs_review
    assert PredicateResult(_REGULAR, APPLIES, CERTAIN).reason == ""
    with pytest.raises(InvariantViolationError, match="predicate must be Predicate"):
        PredicateResult(AllOf(()), APPLIES, CERTAIN)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="outcome must be Applicability"):
        PredicateResult(_REGULAR, "applies", CERTAIN)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="confidence must be Confidence"):
        PredicateResult(_REGULAR, APPLIES, 1.0)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="reason must be str"):
        PredicateResult(_REGULAR, APPLIES, CERTAIN, None)  # type: ignore[arg-type]


# ---- composites ------------------------------------------------------------------------------


def test_empty_composites(ontology: Ontology) -> None:
    assert AllOf(()).evaluate(_PROFILE, ontology) is APPLIES
    assert AnyOf(()).evaluate(_PROFILE, ontology) is NOT_APPLICABLE
    assert AllOf(()).referenced_attributes() == frozenset()
    assert list(AnyOf(()).predicates()) == []


_TRUTH = [
    (APPLIES, APPLIES, APPLIES, APPLIES),
    (APPLIES, NOT_APPLICABLE, NOT_APPLICABLE, APPLIES),
    (APPLIES, UNSURE, UNSURE, APPLIES),
    (NOT_APPLICABLE, APPLIES, NOT_APPLICABLE, APPLIES),
    (NOT_APPLICABLE, NOT_APPLICABLE, NOT_APPLICABLE, NOT_APPLICABLE),
    (NOT_APPLICABLE, UNSURE, NOT_APPLICABLE, UNSURE),
    (UNSURE, APPLIES, UNSURE, APPLIES),
    (UNSURE, NOT_APPLICABLE, NOT_APPLICABLE, UNSURE),
    (UNSURE, UNSURE, UNSURE, UNSURE),
]


@pytest.mark.parametrize(("left", "right", "conjunction", "disjunction"), _TRUTH)
def test_truth_tables(
    left: Applicability,
    right: Applicability,
    conjunction: Applicability,
    disjunction: Applicability,
) -> None:
    assert conjoin([left, right]) is conjunction
    assert disjoin([left, right]) is disjunction
    assert conjoin(iter([right, left])) is conjunction
    assert disjoin(iter([right, left])) is disjunction


def test_conjoin_and_disjoin_on_empty_and_negate() -> None:
    assert conjoin([]) is APPLIES
    assert disjoin([]) is NOT_APPLICABLE
    assert negate(APPLIES) is NOT_APPLICABLE
    assert negate(NOT_APPLICABLE) is APPLIES
    assert negate(UNSURE) is UNSURE


def test_composites_against_a_profile(ontology: Ontology) -> None:
    band = Predicate("turnover_band", Operator.GTE, "1_5cr_to_5cr")
    states = Predicate("state_codes", Operator.CONTAINS_ANY, ("DL", "MH"))
    assert AllOf((_REGULAR, band, states)).evaluate(_PROFILE, ontology) is APPLIES
    assert AllOf((_REGULAR, _COMPOSITION)).evaluate(_PROFILE, ontology) is NOT_APPLICABLE
    assert AllOf((_REGULAR, _JUDGEMENT)).evaluate(_PROFILE, ontology) is UNSURE
    assert AnyOf((_COMPOSITION, _JUDGEMENT)).evaluate(_PROFILE, ontology) is UNSURE
    assert AnyOf((_COMPOSITION, band)).evaluate(_PROFILE, ontology) is APPLIES
    assert Not(_COMPOSITION).evaluate(_PROFILE, ontology) is APPLIES
    assert Not(_JUDGEMENT).evaluate(_PROFILE, ontology) is UNSURE
    assert Not(AllOf((_REGULAR, Not(band)))).is_satisfied_by(_PROFILE, ontology)


def test_composites_do_not_short_circuit_past_bad_data(ontology: Ontology) -> None:
    bad = Predicate("registration_type", Operator.GT, "regular")
    with pytest.raises(InvalidOperatorError):
        AllOf((_COMPOSITION, bad)).evaluate(_PROFILE, ontology)
    with pytest.raises(InvalidOperatorError):
        AnyOf((_REGULAR, bad)).evaluate(_PROFILE, ontology)


@pytest.mark.parametrize(
    ("factory", "argument", "message"),
    [
        (AllOf, [_REGULAR], "AllOf.items must be tuple"),
        (AnyOf, (_REGULAR, "x"), r"AnyOf.items\[1\] must be a Specification"),
        (Not, "x", "Not.item must be a Specification"),
        (Not, None, "Not.item must be a Specification"),
    ],
)
def test_composites_reject_non_specifications(
    factory: type[AllOf] | type[AnyOf] | type[Not], argument: object, message: str
) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        factory(argument)  # type: ignore[arg-type]


def test_evaluate_with_a_custom_leaf_makes_free_text_decidable() -> None:
    spec = AllOf((_REGULAR, Not(_JUDGEMENT)))
    assert spec.evaluate_with(lambda _: APPLIES) is NOT_APPLICABLE
    assert spec.evaluate_with(lambda p: NOT_APPLICABLE if p.free_text else APPLIES) is APPLIES
    seen: list[Predicate] = []

    def record(predicate: Predicate) -> Applicability:
        seen.append(predicate)
        return UNSURE

    assert AnyOf((_REGULAR, spec)).evaluate_with(record) is UNSURE
    assert seen == [_REGULAR, _REGULAR, _JUDGEMENT]


def test_predicates_and_referenced_attributes() -> None:
    band = Predicate("turnover_band", Operator.GTE, "1_5cr_to_5cr")
    spec = AnyOf((AllOf((_REGULAR, band)), Not(_JUDGEMENT), _MISSING))
    assert list(spec.predicates()) == [_REGULAR, band, _JUDGEMENT, _MISSING]
    assert spec.referenced_attributes() == frozenset(
        {"registration_type", "turnover_band", "pan_number_missing_from_profile"}
    )


@pytest.mark.parametrize(
    ("predicate", "text"),
    [
        (_REGULAR, "registration_type = regular"),
        (Predicate("registration_type", Operator.NEQ, "regular"), "registration_type != regular"),
        (Predicate("registration_type", Operator.IN, ("a", "b")), "registration_type in (a, b)"),
        (Predicate("registration_type", Operator.NOT_IN, ("a",)), "registration_type not in (a)"),
        (Predicate("turnover_band", Operator.GT, "over_5cr"), "turnover_band > over_5cr"),
        (Predicate("turnover_band", Operator.GTE, "over_5cr"), "turnover_band >= over_5cr"),
        (Predicate("employee_count", Operator.LT, 5), "employee_count < 5"),
        (Predicate("employee_count", Operator.LTE, 5), "employee_count <= 5"),
        (Predicate("state_codes", Operator.CONTAINS, "29"), "state_codes contains 29"),
        (
            Predicate("state_codes", Operator.CONTAINS_ANY, ("29", "27")),
            "state_codes contains any (29, 27)",
        ),
        (Predicate("e_commerce_supplier", Operator.EQ, True), "e_commerce_supplier = True"),
        (Predicate("registered_on", Operator.LT, date(2020, 1, 1)), "registered_on < 2020-01-01"),
        (_JUDGEMENT, 'free text: "only if the analyst says so"'),
        (Predicate("a", Operator.EQ, "x", "hint"), 'free text: "hint"'),
    ],
)
def test_describe(predicate: Predicate, text: str) -> None:
    assert predicate.describe() == text


def test_value_equality_and_hashing() -> None:
    assert Predicate("registration_type", Operator.EQ, "regular") == _REGULAR
    assert _REGULAR != _COMPOSITION
    assert AllOf((_REGULAR,)) == AllOf((_REGULAR,))
    all_of: Specification = AllOf((_REGULAR,))
    assert all_of != AnyOf((_REGULAR,))
    assert Not(_REGULAR) == Not(_REGULAR)
    assert (
        len({_REGULAR, Predicate("registration_type", Operator.EQ, "regular"), Not(_REGULAR)}) == 2
    )
    assert not hasattr(_REGULAR, "__dict__")
    assert not hasattr(AllOf(()), "__dict__")
