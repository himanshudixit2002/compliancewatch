import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import (
    InvalidAttributeValueError,
    InvalidOperatorError,
    OntologyDefinitionError,
    UnknownAttributeError,
)
from domain_kernel.ontology import (
    ALLOWED_OPERATORS,
    ATTRIBUTE_KEY_PATTERN,
    ENUM_TYPES,
    NUMERIC_TYPES,
    SEMVER_PATTERN,
    AttributeDefinition,
    AttributeSource,
    AttributeType,
    AttributeValue,
    Ontology,
    PredicateValue,
)
from domain_kernel.operators import ORDERED_OPERATORS, SET_OPERATORS, Operator
from domain_kernel.predicates import Predicate

_ALL_KEYS = (
    "registration_type",
    "turnover_band",
    "state_codes",
    "e_commerce_supplier",
    "employee_count",
    "annual_turnover_inr",
    "registered_on",
    "trade_name",
)


def _attribute(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "key": "supply_type",
        "type": "enum",
        "source": "user_input",
        "definition": "What the business supplies.",
        "allowed_values": ["goods", "services", "both"],
    }
    data.update(overrides)
    for key in [key for key, value in data.items() if value is ...]:
        del data[key]
    return data


def _mapping(*attributes: object, version: object = "0.0.1") -> dict[str, object]:
    return {"version": version, "attributes": list(attributes)}


def _definition(**overrides: object) -> AttributeDefinition:
    return AttributeDefinition.from_mapping(_attribute(**overrides))


# ---- loading ---------------------------------------------------------------------------------


def test_fixture_loads_every_type(ontology: Ontology) -> None:
    assert ontology.version == "0.0.1"
    assert len(ontology) == 8
    assert tuple(attribute.key for attribute in ontology) == _ALL_KEYS
    assert {attribute.type for attribute in ontology} == set(AttributeType)
    assert ontology.require("registration_type").since == "0.0.1"
    assert ontology.require("employee_count").minimum == 0
    assert ontology.require("employee_count").maximum is None
    assert ontology.require("trade_name").allowed_values == ()


def test_examples_are_stored_in_canonical_form(ontology: Ontology) -> None:
    assert ontology.require("state_codes").example == frozenset({"KA"})
    assert ontology.require("annual_turnover_inr").example == Decimal("1500000.50")
    assert ontology.require("registered_on").example == date(2019, 7, 1)
    assert ontology.require("e_commerce_supplier").example is False
    assert ontology.require("employee_count").example == 12
    assert hash(ontology.require("state_codes")) == hash(ontology.require("state_codes"))


def test_lists_are_copied_so_shared_yaml_anchors_cannot_leak() -> None:
    shared = ["a", "b"]
    first = _attribute(key="first", allowed_values=shared)
    second = _attribute(key="second", type="ordered_enum", allowed_values=shared)
    ontology = Ontology.from_mapping(_mapping(first, second))
    shared.append("c")
    assert ontology.require("first").allowed_values == ("a", "b")
    assert ontology.require("second").allowed_values == ("a", "b")
    assert isinstance(ontology.require("first").allowed_values, tuple)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ("not a mapping", "ontology must be a mapping"),
        (["version"], "ontology must be a mapping"),
        ({"version": "0.0.1", "attributes": [], "extra": 1}, "unknown keys"),
        ({"attributes": []}, "missing keys"),
        ({"version": 1, "attributes": []}, "version must be a non-empty string"),
        ({"version": "", "attributes": []}, "version must be a non-empty string"),
        ({"version": "1.0", "attributes": []}, "version must be semver"),
        ({"version": "0.0.1", "attributes": "x"}, "attributes must be a list"),
        ({"version": "0.0.1", "attributes": {"key": "a"}}, "attributes must be a list"),
        ({"version": "0.0.1", "attributes": None}, "attributes must be a list"),
        ({"version": "0.0.1", 1: []}, "keys must be strings"),
        (_mapping("x"), r"attributes\[0\] must be a mapping"),
        (_mapping({"key": "a"}), r"attributes\[0\]: missing keys"),
        (_mapping(_attribute(colour="red")), r"attributes\[0\]: unknown keys"),
        (_mapping(_attribute(key="SupplyType")), "must be lowercase snake_case"),
        (_mapping(_attribute(key="1st")), "must be lowercase snake_case"),
        (_mapping(_attribute(key=3)), "key must be a non-empty string"),
        (_mapping(_attribute(type="float")), "type 'float' is not one of"),
        (_mapping(_attribute(type=5)), "type must be a string"),
        (_mapping(_attribute(source="magic")), "source 'magic' is not one of"),
        (_mapping(_attribute(definition=" ")), "definition must be a non-empty string"),
        (_mapping(_attribute(allowed_values="goods")), "allowed_values must be a list"),
        (_mapping(_attribute(allowed_values=None)), "allowed_values must be a list"),
        (_mapping(_attribute(allowed_values=["goods", "goods"])), "duplicate allowed value"),
        (_mapping(_attribute(allowed_values=["goods", " "])), "allowed values must be non-blank"),
        (_mapping(_attribute(allowed_values=["goods", " both"])), "allowed values must be"),
        (_mapping(_attribute(allowed_values=["goods", 1])), "allowed value must be str"),
        (_mapping(_attribute(allowed_values=...)), "enum attributes need allowed_values"),
        (
            _mapping(_attribute(type="ordered_enum", allowed_values=[])),
            "ordered_enum attributes need allowed_values",
        ),
        (
            _mapping(_attribute(type="enum_set", allowed_values=...)),
            "enum_set attributes need allowed_values",
        ),
        (_mapping(_attribute(type="boolean")), "allowed_values are only for enum"),
        (_mapping(_attribute(type="string", allowed_values=..., min=0)), "only allowed on integer"),
        (_mapping(_attribute(type="date", allowed_values=..., max=0)), "only allowed on integer"),
        (
            _mapping(_attribute(type="integer", allowed_values=..., min=True)),
            "min must be an int or Decimal",
        ),
        (
            _mapping(_attribute(type="integer", allowed_values=..., min=0.5)),
            "min must be an int or Decimal",
        ),
        (
            _mapping(_attribute(type="decimal", allowed_values=..., max="10")),
            "max must be an int or Decimal",
        ),
        (
            _mapping(_attribute(type="integer", allowed_values=..., min=Decimal("1"))),
            "min on an integer attribute must be an int",
        ),
        (
            _mapping(_attribute(type="decimal", allowed_values=..., min=Decimal("NaN"))),
            "min must be finite",
        ),
        (
            _mapping(_attribute(type="integer", allowed_values=..., min=10, max=1)),
            "min 10 exceeds max 1",
        ),
        (_mapping(_attribute(since="v1")), "since must be semver"),
        (_mapping(_attribute(since=1.0)), "since must be a string"),
        (_mapping(_attribute(example="nope")), "example is invalid"),
        (_mapping(_attribute(type="boolean", allowed_values=..., example="yes")), "example"),
        (_mapping(_attribute(), _attribute()), r"attributes\[1\]: duplicate key 'supply_type'"),
    ],
)
def test_from_mapping_rejects_malformed_input(data: object, message: str) -> None:
    with pytest.raises(OntologyDefinitionError, match=message):
        Ontology.from_mapping(data)  # type: ignore[arg-type]


def test_from_mapping_names_the_attribute_position() -> None:
    with pytest.raises(
        OntologyDefinitionError, match=r"^attributes\[1\]: other: since must be semver"
    ):
        Ontology.from_mapping(_mapping(_attribute(), _attribute(key="other", since="x")))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type": "enum"}, "type must be AttributeType"),
        ({"source": "user_input"}, "source must be AttributeSource"),
        ({"key": None}, "attribute key must be str"),
        ({"definition": None}, "definition must be str"),
        ({"definition": " "}, "definition must not be blank"),
        ({"allowed_values": ["goods"]}, "allowed_values must be tuple"),
        ({"since": 1}, "since must be str"),
    ],
)
def test_direct_construction_checks_field_types(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "key": "supply_type",
        "type": AttributeType.ENUM,
        "definition": "What the business supplies.",
        "source": AttributeSource.USER_INPUT,
        "allowed_values": ("goods", "services"),
    }
    fields.update(kwargs)
    with pytest.raises(OntologyDefinitionError, match=message):
        AttributeDefinition(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("version", "attributes", "message"),
    [
        (1, (), "version must be str"),
        ("0.0.1", [], "attributes must be tuple"),
        ("0.0.1", ("x",), r"attributes\[0\] must be AttributeDefinition"),
    ],
)
def test_ontology_direct_construction_checks_field_types(
    version: object, attributes: object, message: str
) -> None:
    with pytest.raises(OntologyDefinitionError, match=message):
        Ontology(version, attributes)  # type: ignore[arg-type]


def test_patterns() -> None:
    assert ATTRIBUTE_KEY_PATTERN.fullmatch("turnover_band_2")
    assert not ATTRIBUTE_KEY_PATTERN.fullmatch("Turnover")
    assert SEMVER_PATTERN.fullmatch("10.2.33")
    assert not SEMVER_PATTERN.fullmatch("1.2")


# ---- operators -------------------------------------------------------------------------------


def test_allowed_operators_cover_every_type() -> None:
    assert set(ALLOWED_OPERATORS) == set(AttributeType)
    assert all(ALLOWED_OPERATORS[kind] for kind in AttributeType)
    assert ALLOWED_OPERATORS[AttributeType.ENUM_SET] == SET_OPERATORS
    assert ALLOWED_OPERATORS[AttributeType.BOOLEAN] == {Operator.EQ, Operator.NEQ}
    for kind in (AttributeType.ORDERED_ENUM, *NUMERIC_TYPES, AttributeType.DATE):
        assert ALLOWED_OPERATORS[kind] >= ORDERED_OPERATORS
    for kind in (AttributeType.ENUM, AttributeType.STRING, AttributeType.BOOLEAN):
        assert ORDERED_OPERATORS.isdisjoint(ALLOWED_OPERATORS[kind])
        assert SET_OPERATORS.isdisjoint(ALLOWED_OPERATORS[kind])
    assert {AttributeType.ENUM, AttributeType.ORDERED_ENUM, AttributeType.ENUM_SET} == ENUM_TYPES


# ---- coercion --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("registration_type", "regular", "regular"),
        ("turnover_band", "over_5cr", "over_5cr"),
        ("state_codes", ["KA", "MH"], frozenset({"KA", "MH"})),
        ("state_codes", ("KA",), frozenset({"KA"})),
        ("state_codes", {"DL"}, frozenset({"DL"})),
        ("state_codes", frozenset(), frozenset()),
        ("e_commerce_supplier", True, True),
        ("employee_count", 0, 0),
        ("employee_count", 250, 250),
        ("annual_turnover_inr", 5, Decimal("5")),
        ("annual_turnover_inr", 5.5, Decimal("5.5")),
        ("annual_turnover_inr", "1500000.50", Decimal("1500000.50")),
        ("annual_turnover_inr", Decimal("0"), Decimal("0")),
        ("registered_on", date(2020, 1, 31), date(2020, 1, 31)),
        ("registered_on", "2020-01-31", date(2020, 1, 31)),
        ("trade_name", "Acme", "Acme"),
        ("trade_name", "", ""),
    ],
)
def test_validate_value_returns_the_canonical_form(
    ontology: Ontology, key: str, raw: object, expected: AttributeValue
) -> None:
    canonical = ontology.validate_value(key, raw)
    assert canonical == expected
    assert type(canonical) is type(expected)


@pytest.mark.parametrize(
    ("key", "raw", "message"),
    [
        ("registration_type", "Regular", "is not one of"),
        ("registration_type", None, "is not one of"),
        ("registration_type", ["regular"], "is not one of"),
        ("turnover_band", 1, "is not one of"),
        ("state_codes", "KA", "must be a list, tuple or set"),
        ("state_codes", ["KA", "XX"], "'XX' is not one of"),
        ("state_codes", 1, "must be a list, tuple or set"),
        ("e_commerce_supplier", 1, "must be a bool"),
        ("e_commerce_supplier", "true", "must be a bool"),
        ("employee_count", True, "must be an int"),
        ("employee_count", 5.0, "must be an int"),
        ("employee_count", "5", "must be an int"),
        ("employee_count", -1, "is below the minimum 0"),
        ("annual_turnover_inr", True, "must be a number"),
        ("annual_turnover_inr", "abc", "is not a decimal number"),
        ("annual_turnover_inr", "", "is not a decimal number"),
        ("annual_turnover_inr", float("nan"), "must be finite"),
        ("annual_turnover_inr", Decimal("Infinity"), "must be finite"),
        ("annual_turnover_inr", "-0.01", "is below the minimum 0"),
        ("annual_turnover_inr", [1], "must be a number"),
        ("registered_on", datetime(2020, 1, 31, tzinfo=UTC), "must be a date without a time"),
        ("registered_on", "31/01/2020", "is not an ISO date"),
        ("registered_on", 20200131, "must be a date"),
        ("trade_name", 12, "must be a string"),
    ],
)
def test_validate_value_rejects_bad_input(
    ontology: Ontology, key: str, raw: object, message: str
) -> None:
    with pytest.raises(InvalidAttributeValueError, match=message) as info:
        ontology.validate_value(key, raw)
    assert info.value.attribute == key


def test_decimal_bounds_apply_to_int_float_and_str_input() -> None:
    definition = _definition(type="decimal", allowed_values=..., min=0, max=Decimal("100"))
    assert definition.coerce(5) == Decimal("5")
    assert definition.coerce(5.5) == Decimal("5.5")
    assert definition.coerce("99.99") == Decimal("99.99")
    assert definition.coerce(100) == Decimal("100")
    with pytest.raises(InvalidAttributeValueError, match="is above the maximum 100"):
        definition.coerce("100.01")
    with pytest.raises(InvalidAttributeValueError, match="is below the minimum 0"):
        definition.coerce(-1)


def test_integer_maximum() -> None:
    definition = _definition(type="integer", allowed_values=..., min=0, max=10)
    assert definition.coerce(10) == 10
    with pytest.raises(InvalidAttributeValueError, match="is above the maximum 10"):
        definition.coerce(11)


def test_member_and_members_on_the_definition(ontology: Ontology) -> None:
    states = ontology.require("state_codes")
    assert states.member("KA") == "KA"
    assert states.members(["KA", "KA"]) == frozenset({"KA"})
    with pytest.raises(InvalidAttributeValueError, match="is not one of"):
        states.member("XX")


def test_rank(ontology: Ontology) -> None:
    band = ontology.require("turnover_band")
    assert band.rank("under_20l") == 0
    assert band.rank("over_5cr") == 3
    assert ontology.require("employee_count").rank(7) == 7
    assert ontology.require("annual_turnover_inr").rank("2.5") == Decimal("2.5")
    assert ontology.require("registered_on").rank("2020-01-01") == date(2020, 1, 1)
    with pytest.raises(InvalidAttributeValueError, match="has no order on a enum attribute"):
        ontology.require("registration_type").rank("regular")
    with pytest.raises(InvalidAttributeValueError, match="has no order on a boolean attribute"):
        ontology.require("e_commerce_supplier").rank(True)
    with pytest.raises(InvalidAttributeValueError, match="has no order on a enum_set attribute"):
        ontology.require("state_codes").rank(["KA"])


_canonical_values = st.one_of(
    st.tuples(st.just("registration_type"), st.sampled_from(["regular", "composition"])),
    st.tuples(st.just("turnover_band"), st.sampled_from(["under_20l", "over_5cr"])),
    st.tuples(st.just("state_codes"), st.frozensets(st.sampled_from(["KA", "MH", "DL", "TN"]))),
    st.tuples(st.just("e_commerce_supplier"), st.booleans()),
    st.tuples(st.just("employee_count"), st.integers(min_value=0)),
    st.tuples(
        st.just("annual_turnover_inr"),
        st.decimals(min_value=0, allow_nan=False, allow_infinity=False),
    ),
    st.tuples(st.just("registered_on"), st.dates()),
    st.tuples(st.just("trade_name"), st.text()),
)


@given(item=_canonical_values)
def test_validate_value_is_idempotent_on_canonical_values(
    ontology: Ontology, item: tuple[str, object]
) -> None:
    key, raw = item
    canonical = ontology.validate_value(key, raw)
    assert ontology.validate_value(key, canonical) == canonical
    assert canonical == raw


# ---- lookups ---------------------------------------------------------------------------------


def test_validate_attributes(ontology: Ontology) -> None:
    profile = {"registration_type": "regular", "state_codes": ["KA"], "employee_count": 3}
    assert ontology.validate_attributes(profile) == {
        "registration_type": "regular",
        "state_codes": frozenset({"KA"}),
        "employee_count": 3,
    }
    assert ontology.validate_attributes({}) == {}
    with pytest.raises(UnknownAttributeError, match="pan_number"):
        ontology.validate_attributes({"pan_number": "x"})
    with pytest.raises(InvalidAttributeValueError, match="must not be None"):
        ontology.validate_attributes({"employee_count": None})
    with pytest.raises(InvalidAttributeValueError, match="must be an int"):
        ontology.validate_attributes({"employee_count": "3"})


def test_require_get_contains(ontology: Ontology) -> None:
    assert ontology.require("trade_name").type is AttributeType.STRING
    assert ontology.get("trade_name") is ontology.require("trade_name")
    assert ontology.get("pan_number") is None
    assert "trade_name" in ontology
    assert "pan_number" not in ontology
    assert 3 not in ontology
    with pytest.raises(UnknownAttributeError, match="pan_number") as info:
        ontology.require("pan_number")
    assert info.value.attribute == "pan_number"


def test_replace_rebuilds_the_index(ontology: Ontology) -> None:
    smaller = dataclasses.replace(ontology, attributes=ontology.attributes[:2])
    assert len(smaller) == 2
    assert "state_codes" not in smaller
    assert "state_codes" in ontology
    assert smaller.require("turnover_band") is ontology.require("turnover_band")
    assert smaller != ontology
    with pytest.raises(OntologyDefinitionError, match="duplicate key"):
        dataclasses.replace(ontology, attributes=ontology.attributes[:1] * 2)


def test_ontology_equality_ignores_the_index(ontology: Ontology) -> None:
    again = Ontology(ontology.version, ontology.attributes)
    assert again == ontology
    assert hash(again) == hash(ontology)
    assert "_by_key" not in repr(ontology)


# ---- compare ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "operator", "actual", "expected", "verdict"),
    [
        ("registration_type", Operator.EQ, "regular", "regular", True),
        ("registration_type", Operator.EQ, "regular", "composition", False),
        ("registration_type", Operator.NEQ, "regular", "composition", True),
        ("registration_type", Operator.IN, "regular", ("regular", "composition"), True),
        ("registration_type", Operator.NOT_IN, "regular", ("regular", "composition"), False),
        ("turnover_band", Operator.GT, "over_5cr", "1_5cr_to_5cr", True),
        ("turnover_band", Operator.GTE, "1_5cr_to_5cr", "1_5cr_to_5cr", True),
        ("turnover_band", Operator.LT, "1_5cr_to_5cr", "1_5cr_to_5cr", False),
        ("turnover_band", Operator.LTE, "under_20l", "20l_to_1_5cr", True),
        ("turnover_band", Operator.IN, "under_20l", ("under_20l",), True),
        ("state_codes", Operator.CONTAINS, ["KA", "MH"], "KA", True),
        ("state_codes", Operator.CONTAINS, ["KA", "MH"], "DL", False),
        ("state_codes", Operator.CONTAINS_ANY, ["KA", "MH"], ("DL", "MH"), True),
        ("state_codes", Operator.CONTAINS_ANY, ["KA"], ("DL", "TN"), False),
        ("state_codes", Operator.CONTAINS_ANY, [], ("DL", "TN"), False),
        ("e_commerce_supplier", Operator.EQ, True, True, True),
        ("e_commerce_supplier", Operator.NEQ, True, False, True),
        ("employee_count", Operator.GTE, 10, 10, True),
        ("employee_count", Operator.GT, 10, 10, False),
        ("employee_count", Operator.LT, 9, 10, True),
        ("employee_count", Operator.LTE, 11, 10, False),
        ("employee_count", Operator.IN, 9, (1, 9), True),
        ("employee_count", Operator.NOT_IN, 9, (1, 2), True),
        ("annual_turnover_inr", Operator.GT, "150.5", 150, True),
        ("annual_turnover_inr", Operator.EQ, 1.0, "1", True),
        ("annual_turnover_inr", Operator.IN, Decimal("2.0"), (1, "2"), True),
        ("annual_turnover_inr", Operator.LTE, 2, Decimal("1.99"), False),
        ("registered_on", Operator.LT, "2019-06-30", date(2019, 7, 1), True),
        ("registered_on", Operator.GTE, date(2019, 7, 1), "2019-07-01", True),
        ("registered_on", Operator.EQ, date(2019, 7, 1), "2019-07-02", False),
        ("registered_on", Operator.NOT_IN, date(2019, 7, 1), ("2019-07-02",), True),
        ("trade_name", Operator.EQ, "Acme", "Acme", True),
        ("trade_name", Operator.NEQ, "Acme", "acme", True),
        ("trade_name", Operator.IN, "Acme", ("Acme", "Beta"), True),
        ("trade_name", Operator.NOT_IN, "Acme", ("Acme", "Beta"), False),
    ],
)
def test_compare_table(
    ontology: Ontology,
    key: str,
    operator: Operator,
    actual: object,
    expected: PredicateValue,
    verdict: bool,
) -> None:
    assert ontology.compare(key, operator, actual, expected) is verdict


@pytest.mark.parametrize(
    ("key", "operator"),
    [
        ("registration_type", Operator.GT),
        ("registration_type", Operator.CONTAINS),
        ("state_codes", Operator.EQ),
        ("state_codes", Operator.IN),
        ("e_commerce_supplier", Operator.IN),
        ("e_commerce_supplier", Operator.LT),
        ("employee_count", Operator.CONTAINS_ANY),
        ("trade_name", Operator.GTE),
        ("registered_on", Operator.CONTAINS),
    ],
)
def test_compare_rejects_disallowed_operators(
    ontology: Ontology, key: str, operator: Operator
) -> None:
    with pytest.raises(InvalidOperatorError) as info:
        ontology.compare(key, operator, "x", "y")
    assert info.value.attribute == key
    assert info.value.operator == operator.value
    assert info.value.attribute_type == ontology.require(key).type.value


@pytest.mark.parametrize(
    ("key", "operator", "actual", "expected", "message"),
    [
        ("registration_type", Operator.EQ, "Regular", "regular", "is not one of"),
        ("registration_type", Operator.EQ, "regular", "Regular", "is not one of"),
        ("registration_type", Operator.EQ, "regular", ("regular",), "takes one value"),
        ("registration_type", Operator.IN, "regular", "regular", "takes a tuple"),
        ("registration_type", Operator.IN, "regular", (), "at least one value"),
        ("registration_type", Operator.NOT_IN, "regular", ("regular", 1), "is not one of"),
        ("turnover_band", Operator.GT, "over_5cr", ("under_20l",), "takes one value"),
        ("turnover_band", Operator.GT, "big", "under_20l", "is not one of"),
        ("state_codes", Operator.CONTAINS, "KA", "KA", "must be a list, tuple or set"),
        ("state_codes", Operator.CONTAINS, ["KA"], ("KA",), "takes one value"),
        ("state_codes", Operator.CONTAINS, ["KA"], "XX", "is not one of"),
        ("state_codes", Operator.CONTAINS_ANY, ["KA"], "KA", "takes a tuple"),
        ("state_codes", Operator.CONTAINS_ANY, ["KA"], ("XX",), "is not one of"),
        ("employee_count", Operator.GT, "9", 10, "must be an int"),
        ("employee_count", Operator.GT, 9, "10", "must be an int"),
        ("registered_on", Operator.LT, "yesterday", "2019-07-01", "is not an ISO date"),
    ],
)
def test_compare_rejects_malformed_values(
    ontology: Ontology, key: str, operator: Operator, actual: object, expected: object, message: str
) -> None:
    with pytest.raises(InvalidAttributeValueError, match=message):
        ontology.compare(key, operator, actual, expected)  # type: ignore[arg-type]


def test_compare_unknown_attribute(ontology: Ontology) -> None:
    with pytest.raises(UnknownAttributeError, match="pan_number"):
        ontology.compare("pan_number", Operator.EQ, "x", "x")


# ---- check_predicate -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "predicate",
    [
        Predicate("registration_type", Operator.EQ, "regular"),
        Predicate("registration_type", Operator.NOT_IN, ("regular", "composition")),
        Predicate("turnover_band", Operator.GTE, "over_5cr"),
        Predicate("state_codes", Operator.CONTAINS, "KA"),
        Predicate("state_codes", Operator.CONTAINS_ANY, ("KA", "MH")),
        Predicate("e_commerce_supplier", Operator.EQ, False),
        Predicate("employee_count", Operator.IN, (1, 2)),
        Predicate("annual_turnover_inr", Operator.LT, "10.5"),
        Predicate("registered_on", Operator.GT, "2020-01-01"),
        Predicate("trade_name", free_text="anything the analyst wants"),
        Predicate("trade_name", Operator.EQ, "Acme", "with a hint"),
    ],
)
def test_check_predicate_accepts_well_formed_predicates(
    ontology: Ontology, predicate: Predicate
) -> None:
    ontology.check_predicate(predicate)


@pytest.mark.parametrize(
    ("predicate", "error", "message"),
    [
        (Predicate("pan_number", Operator.EQ, "x"), UnknownAttributeError, "pan_number"),
        (Predicate("pan_number", free_text="x"), UnknownAttributeError, "pan_number"),
        (Predicate("registration_type", Operator.GT, "regular"), InvalidOperatorError, "gt"),
        (Predicate("state_codes", Operator.EQ, "KA"), InvalidOperatorError, "eq"),
        (
            Predicate("registration_type", Operator.EQ, "Regular"),
            InvalidAttributeValueError,
            "one of",
        ),
        (Predicate("registration_type", Operator.IN, ("x",)), InvalidAttributeValueError, "one of"),
        (Predicate("state_codes", Operator.CONTAINS, "XX"), InvalidAttributeValueError, "one of"),
        (
            Predicate("state_codes", Operator.CONTAINS_ANY, ("XX",)),
            InvalidAttributeValueError,
            "of",
        ),
        (Predicate("employee_count", Operator.EQ, -1), InvalidAttributeValueError, "minimum"),
        (Predicate("employee_count", Operator.IN, (1, "2")), InvalidAttributeValueError, "int"),
        (Predicate("registered_on", Operator.LT, "soon"), InvalidAttributeValueError, "ISO"),
        (Predicate("trade_name", Operator.EQ, 1, "hinted"), InvalidAttributeValueError, "string"),
    ],
)
def test_check_predicate_rejects_bad_predicates(
    ontology: Ontology, predicate: Predicate, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        ontology.check_predicate(predicate)
