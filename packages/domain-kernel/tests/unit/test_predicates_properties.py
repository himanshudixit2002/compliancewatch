from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.ontology import Ontology, PredicateValue, Scalar
from domain_kernel.operators import (
    MULTI_VALUE_OPERATORS,
    ORDERED_OPERATORS,
    SET_OPERATORS,
    Operator,
)
from domain_kernel.predicates import (
    AllOf,
    AnyOf,
    Applicability,
    Not,
    Predicate,
    Specification,
    negate,
)

_EQUALITY = frozenset({Operator.EQ, Operator.NEQ, Operator.IN, Operator.NOT_IN})
_COMPARABLE = _EQUALITY | ORDERED_OPERATORS
_ENUM = ("regular", "composition", "unregistered")
_BANDS = ("under_20l", "20l_to_1_5cr", "1_5cr_to_5cr", "over_5cr")
_STATES = ("KA", "MH", "DL", "TN")
_NAMES = ("Acme", "Beta", "Gamma")
_DATES = st.dates(min_value=date(2017, 7, 1), max_value=date(2026, 12, 31))
_MONEY = st.decimals(min_value=0, max_value=1000, places=2)

_LEAF_TABLE: dict[str, tuple[st.SearchStrategy[Scalar], frozenset[Operator]]] = {
    "registration_type": (st.sampled_from(_ENUM), _EQUALITY),
    "turnover_band": (st.sampled_from(_BANDS), _COMPARABLE),
    "state_codes": (st.sampled_from(_STATES), SET_OPERATORS),
    "e_commerce_supplier": (st.booleans(), frozenset({Operator.EQ, Operator.NEQ})),
    "employee_count": (st.integers(0, 50), _COMPARABLE),
    "annual_turnover_inr": (_MONEY, _COMPARABLE),
    "registered_on": (_DATES, _COMPARABLE),
    "trade_name": (st.sampled_from(_NAMES), _EQUALITY),
}
_ORDERED_KEYS = sorted(key for key, (_, ops) in _LEAF_TABLE.items() if ops >= ORDERED_OPERATORS)
_PROFILE_VALUES: dict[str, st.SearchStrategy[object]] = {
    "registration_type": st.sampled_from(_ENUM),
    "turnover_band": st.sampled_from(_BANDS),
    "state_codes": st.frozensets(st.sampled_from(_STATES)),
    "e_commerce_supplier": st.booleans(),
    "employee_count": st.integers(0, 50),
    "annual_turnover_inr": _MONEY,
    "registered_on": _DATES,
    "trade_name": st.sampled_from(_NAMES),
}
_REQUIRED: dict[str, st.SearchStrategy[object]] = {}


@st.composite
def _scalar_predicates(draw: st.DrawFn) -> Predicate:
    key = draw(st.sampled_from(sorted(_LEAF_TABLE)))
    values, operators = _LEAF_TABLE[key]
    operator = draw(st.sampled_from(sorted(operators)))
    value: PredicateValue
    if operator in MULTI_VALUE_OPERATORS:
        value = tuple(draw(st.lists(values, min_size=1, max_size=3)))
    else:
        value = draw(values)
    return Predicate(key, operator, value)


_free_text = st.just(Predicate("registration_type", free_text="only if the analyst agrees"))
leaves: st.SearchStrategy[Predicate] = st.one_of(_scalar_predicates(), _free_text)


def _extend(children: st.SearchStrategy[Specification]) -> st.SearchStrategy[Specification]:
    branches = st.lists(children, max_size=3).map(tuple)
    return st.one_of(
        st.builds(AllOf, branches), st.builds(AnyOf, branches), st.builds(Not, children)
    )


specs: st.SearchStrategy[Specification] = st.recursive(leaves, _extend, max_leaves=8)
spec_lists = st.lists(specs, max_size=3).map(tuple)
profiles: st.SearchStrategy[dict[str, object]] = st.fixed_dictionaries(
    _REQUIRED, optional=_PROFILE_VALUES
)


@given(spec=specs, profile=profiles)
def test_double_negation(
    ontology: Ontology, spec: Specification, profile: dict[str, object]
) -> None:
    assert Not(Not(spec)).evaluate(profile, ontology) is spec.evaluate(profile, ontology)


@given(items=spec_lists, profile=profiles)
def test_de_morgan_both_ways(
    ontology: Ontology, items: tuple[Specification, ...], profile: dict[str, object]
) -> None:
    negated = tuple(Not(item) for item in items)
    assert Not(AllOf(items)).evaluate(profile, ontology) is AnyOf(negated).evaluate(
        profile, ontology
    )
    assert Not(AnyOf(items)).evaluate(profile, ontology) is AllOf(negated).evaluate(
        profile, ontology
    )


@given(left=specs, right=specs, profile=profiles)
def test_commutative_and_idempotent(
    ontology: Ontology, left: Specification, right: Specification, profile: dict[str, object]
) -> None:
    assert AllOf((left, right)).evaluate(profile, ontology) is AllOf((right, left)).evaluate(
        profile, ontology
    )
    assert AnyOf((left, right)).evaluate(profile, ontology) is AnyOf((right, left)).evaluate(
        profile, ontology
    )
    assert AllOf((left, left)).evaluate(profile, ontology) is left.evaluate(profile, ontology)
    assert AnyOf((left, left)).evaluate(profile, ontology) is left.evaluate(profile, ontology)


@given(first=specs, second=specs, third=specs, profile=profiles)
def test_associative_with_identities(
    ontology: Ontology,
    first: Specification,
    second: Specification,
    third: Specification,
    profile: dict[str, object],
) -> None:
    nested_left = AllOf((AllOf((first, second)), third)).evaluate(profile, ontology)
    nested_right = AllOf((first, AllOf((second, third)))).evaluate(profile, ontology)
    assert nested_left is nested_right
    assert nested_left is AllOf((first, second, third)).evaluate(profile, ontology)
    any_left = AnyOf((AnyOf((first, second)), third)).evaluate(profile, ontology)
    any_right = AnyOf((first, AnyOf((second, third)))).evaluate(profile, ontology)
    assert any_left is any_right
    assert any_left is AnyOf((first, second, third)).evaluate(profile, ontology)
    outcome = first.evaluate(profile, ontology)
    assert AllOf((first, AllOf(()))).evaluate(profile, ontology) is outcome
    assert AnyOf((first, AnyOf(()))).evaluate(profile, ontology) is outcome
    assert AllOf(()).evaluate(profile, ontology) is Applicability.APPLIES
    assert AnyOf(()).evaluate(profile, ontology) is Applicability.NOT_APPLICABLE


@given(predicate=_scalar_predicates(), profile=profiles)
def test_free_text_is_always_unsure(
    ontology: Ontology, predicate: Predicate, profile: dict[str, object]
) -> None:
    hinted = Predicate(predicate.attribute, predicate.operator, predicate.value, "judge it")
    assert hinted.evaluate(profile, ontology) is Applicability.UNSURE
    assert Not(hinted).evaluate(profile, ontology) is Applicability.UNSURE
    assert not hinted.is_satisfied_by(profile, ontology)


@given(predicate=_scalar_predicates(), profile=profiles)
def test_structured_leaf_is_decided_iff_the_attribute_is_present(
    ontology: Ontology, predicate: Predicate, profile: dict[str, object]
) -> None:
    outcome = predicate.evaluate(profile, ontology)
    if predicate.attribute in profile:
        assert outcome in (Applicability.APPLIES, Applicability.NOT_APPLICABLE)
    else:
        assert outcome is Applicability.UNSURE


@given(predicate=_scalar_predicates(), profile=profiles)
def test_neq_and_not_in_are_negations(
    ontology: Ontology, predicate: Predicate, profile: dict[str, object]
) -> None:
    opposites = {
        Operator.EQ: Operator.NEQ,
        Operator.NEQ: Operator.EQ,
        Operator.IN: Operator.NOT_IN,
        Operator.NOT_IN: Operator.IN,
    }
    if predicate.operator not in opposites:
        return
    opposite = Predicate(predicate.attribute, opposites[predicate.operator], predicate.value)
    assert opposite.evaluate(profile, ontology) is negate(predicate.evaluate(profile, ontology))
    assert opposite.evaluate(profile, ontology) is Not(predicate).evaluate(profile, ontology)


@given(key=st.sampled_from(_ORDERED_KEYS), data=st.data())
def test_ordered_trichotomy(ontology: Ontology, key: str, data: st.DataObject) -> None:
    values, _ = _LEAF_TABLE[key]
    actual, expected = data.draw(values), data.draw(values)
    profile = {key: actual}

    def holds(operator: Operator) -> bool:
        return Predicate(key, operator, expected).is_satisfied_by(profile, ontology)

    assert [holds(Operator.LT), holds(Operator.EQ), holds(Operator.GT)].count(True) == 1
    assert holds(Operator.GTE) == (holds(Operator.GT) or holds(Operator.EQ))
    assert holds(Operator.LTE) == (holds(Operator.LT) or holds(Operator.EQ))
    assert holds(Operator.NEQ) == (not holds(Operator.EQ))


@given(spec=specs, profile=profiles)
def test_is_satisfied_by_agrees_with_evaluate(
    ontology: Ontology, spec: Specification, profile: dict[str, object]
) -> None:
    outcome = spec.evaluate(profile, ontology)
    assert spec.is_satisfied_by(profile, ontology) is (outcome is Applicability.APPLIES)


@given(spec=specs, profile=profiles)
def test_default_leaf_equals_evaluate(
    ontology: Ontology, spec: Specification, profile: dict[str, object]
) -> None:
    via_leaf = spec.evaluate_with(lambda predicate: predicate.evaluate(profile, ontology))
    assert via_leaf is spec.evaluate(profile, ontology)
    assert spec.referenced_attributes() == frozenset(p.attribute for p in spec.predicates())
