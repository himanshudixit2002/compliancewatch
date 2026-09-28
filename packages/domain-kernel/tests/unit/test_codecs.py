"""Mapping codecs: specifications, obligation templates and recurrences round-trip through
their JSON form."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from domain_kernel.operators import Operator
from domain_kernel.predicates import (
    AllOf,
    AnyOf,
    Not,
    Predicate,
    Specification,
    specification_from_mapping,
    specification_to_mapping,
)
from domain_kernel.recurrence import Frequency, Recurrence
from domain_kernel.rules import ObligationTemplate

TREE = AllOf(
    (
        Predicate("registration_type", Operator.EQ, "regular"),
        AnyOf(
            (
                Predicate("turnover_band", Operator.GTE, "5_crore_to_10_crore"),
                Not(Predicate("state_codes", Operator.CONTAINS, "29")),
            )
        ),
        Predicate("employee_count", Operator.IN, (1, 2, 3)),
        Predicate("registered_since", Operator.LT, date(2020, 4, 1)),
        Predicate("annual_turnover_inr", Operator.GT, Decimal("1500000.50")),
        Predicate("nature_of_supply", free_text="supplies mainly to government departments"),
    )
)


def test_specification_mapping_is_json_shaped() -> None:
    mapping = specification_to_mapping(TREE)
    assert mapping == {
        "all_of": [
            {"attribute": "registration_type", "operator": "eq", "value": "regular"},
            {
                "any_of": [
                    {
                        "attribute": "turnover_band",
                        "operator": "gte",
                        "value": "5_crore_to_10_crore",
                    },
                    {"not": {"attribute": "state_codes", "operator": "contains", "value": "29"}},
                ]
            },
            {"attribute": "employee_count", "operator": "in", "value": [1, 2, 3]},
            {"attribute": "registered_since", "operator": "lt", "value": "2020-04-01"},
            {"attribute": "annual_turnover_inr", "operator": "gt", "value": "1500000.50"},
            {
                "attribute": "nature_of_supply",
                "free_text": "supplies mainly to government departments",
            },
        ]
    }


def test_specification_round_trip_keeps_structure_and_string_forms() -> None:
    rebuilt = specification_from_mapping(specification_to_mapping(TREE))
    assert isinstance(rebuilt, AllOf)
    assert [type(item).__name__ for item in rebuilt.items] == [
        "Predicate",
        "AnyOf",
        "Predicate",
        "Predicate",
        "Predicate",
        "Predicate",
    ]
    # Dates and decimals come back as strings; the ontology coerces them at evaluation time.
    assert rebuilt.items[3] == Predicate("registered_since", Operator.LT, "2020-04-01")
    assert rebuilt.items[4] == Predicate("annual_turnover_inr", Operator.GT, "1500000.50")
    assert specification_to_mapping(rebuilt) == specification_to_mapping(TREE)
    assert rebuilt.referenced_attributes() == TREE.referenced_attributes()


def test_free_text_with_a_hint_keeps_both() -> None:
    hinted = Predicate("turnover_band", Operator.GTE, "upto_10_lakh", free_text="judge this")
    mapping = specification_to_mapping(hinted)
    assert mapping["free_text"] == "judge this"
    assert specification_from_mapping(mapping) == hinted


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ("all_of", "specification must be"),
        ({}, "specification must be"),
        ({"all_of": [], "any_of": []}, "specification must be"),
        ({"all_of": "x"}, "list of specifications"),
        ({"attribute": "a", "operator": "between", "value": 1}, "operator must be one of"),
        ({"attribute": "a", "operator": "eq", "value": {"x": 1}}, "strings, numbers or booleans"),
        ({"attribute": "a", "operator": "eq"}, "operator and value"),
        ({"attribute": "a"}, "needs an operator and value or free text"),
        ({"attribute": "a", "extra": 1}, "specification must be"),
    ],
)
def test_specification_from_mapping_rejects_malformed_input(data: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        specification_from_mapping(data)


def test_floats_become_decimals() -> None:
    predicate = specification_from_mapping({"attribute": "a", "operator": "gt", "value": 1.5})
    assert isinstance(predicate, Predicate)
    assert predicate.value == Decimal("1.5")


def test_obligation_template_round_trip() -> None:
    template = ObligationTemplate("File GSTR-3B", ("Reconcile", "File"), 20, "filing_ack")
    mapping = template.to_mapping()
    assert mapping == {
        "title": "File GSTR-3B",
        "steps": ["Reconcile", "File"],
        "due_in_days": 20,
        "evidence_type": "filing_ack",
    }
    assert ObligationTemplate.from_mapping(mapping) == template
    assert ObligationTemplate.from_mapping({"title": "Display the certificate"}) == (
        ObligationTemplate("Display the certificate")
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"title": ""}, "title"),
        ({"title": "x", "steps": "one"}, "steps must be a list"),
        ({"title": "x", "steps": [""]}, "steps"),
        ({"title": "x", "due_in_days": -1}, "due_in_days"),
        ({"title": "x", "other": 1}, "unknown keys"),
        ("x", "obligation_template must be"),
    ],
)
def test_obligation_template_from_mapping_rejects(data: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        ObligationTemplate.from_mapping(data)


def test_recurrence_round_trip_and_half_years() -> None:
    recurrence = Recurrence.half_yearly(25)
    assert recurrence.to_mapping() == {
        "frequency": "half_yearly",
        "due_day": 25,
        "due_month_offset": 0,
    }
    assert Recurrence.from_mapping(recurrence.to_mapping()) == recurrence
    assert Recurrence.from_mapping({"frequency": "monthly", "due_day": 20}) == (
        Recurrence.monthly(20)
    )
    first = recurrence.period_containing(date(2026, 7, 1))
    assert (first.start, first.end, first.label) == (
        date(2026, 4, 1),
        date(2026, 10, 1),
        "2026-27 H1",
    )
    assert recurrence.due_date(first) == date(2026, 10, 25)
    second = recurrence.next_period(first)
    assert (second.start, second.end, second.label) == (
        date(2026, 10, 1),
        date(2027, 4, 1),
        "2026-27 H2",
    )
    assert recurrence.due_date(second) == date(2027, 4, 25)
    assert [f.value for f in Frequency] == ["monthly", "quarterly", "half_yearly", "annual"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"frequency": "weekly", "due_day": 1}, "frequency must be one of"),
        ({"frequency": "monthly"}, "due_day"),
        ({"frequency": "monthly", "due_day": 1, "x": 1}, "unknown keys"),
        ([], "recurrence must be"),
    ],
)
def test_recurrence_from_mapping_rejects(data: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        Recurrence.from_mapping(data)


_scalars = st.one_of(
    st.text(min_size=1, max_size=12),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)
_predicates = st.builds(
    Predicate,
    st.sampled_from(["turnover_band", "state_codes", "employee_count"]),
    st.sampled_from([Operator.EQ, Operator.NEQ, Operator.GT, Operator.LTE, Operator.CONTAINS]),
    _scalars,
)
_specifications: st.SearchStrategy[Specification] = st.recursive(
    _predicates,
    lambda children: st.one_of(
        st.builds(AllOf, st.tuples(children, children)),
        st.builds(AnyOf, st.tuples(children)),
        st.builds(Not, children),
    ),
    max_leaves=8,
)


@given(_specifications)
def test_every_specification_round_trips(specification: Specification) -> None:
    mapping = specification_to_mapping(specification)
    assert specification_from_mapping(mapping) == specification
