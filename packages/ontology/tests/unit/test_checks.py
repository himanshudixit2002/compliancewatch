import pytest

from domain_kernel.errors import OntologyDefinitionError
from domain_kernel.ontology import Ontology
from ontology._checks import check

_CLEAN: dict[str, object] = {
    "key": "supply_type",
    "type": "enum",
    "source": "user_input",
    "since": "0.1.0",
    "definition": "Whether the business supplies goods, services or both.",
    "allowed_values": ["goods", "services", "both"],
}


def _mapping(**overrides: object) -> dict[str, object]:
    return {"version": "0.1.0", "attributes": [{**_CLEAN, **overrides}]}


def test_clean_attribute_passes() -> None:
    assert check(Ontology.from_mapping(_mapping())) == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"definition": "No full stop"}, "period"),
        ({"since": "0.2.0"}, "newer than"),
        ({"allowed_values": ["goods"]}, "at least two"),
        ({"allowed_values": ["goods", "Bad Value"]}, "malformed"),
        ({"key": "state_codes", "type": "enum_set", "allowed_values": ["29", "1"]}, "malformed"),
        ({"since": None}, "since is required"),
        ({"per_financial_year": True}, "entity level"),
    ],
)
def test_each_rule_reports(overrides: dict[str, object], expected: str) -> None:
    problems = check(Ontology.from_mapping(_mapping(**overrides)))
    assert len(problems) == 1
    assert expected in problems[0]


def test_kernel_rejects_a_bad_key_before_the_house_rules() -> None:
    with pytest.raises(OntologyDefinitionError, match="snake_case"):
        Ontology.from_mapping(_mapping(key="SupplyType"))


def test_key_rule_reports_on_its_own() -> None:
    # AttributeDefinition rejects such a key itself, so the loader never reaches this rule.
    # Set the field behind the frozen dataclass to exercise the rule in isolation.
    attribute = Ontology.from_mapping(_mapping()).attributes[0]
    object.__setattr__(attribute, "key", "SupplyType")
    problems = check(Ontology(version="0.1.0", attributes=(attribute,)))
    assert problems == ["SupplyType: key is not snake_case"]
