import pytest

from domain_kernel.errors import OntologyDefinitionError
from domain_kernel.ontology import AttributeDefinition, AttributeLevel, AttributeSource, Ontology

BASE: dict[str, object] = {
    "key": "turnover_band",
    "type": "ordered_enum",
    "source": "user_input",
    "definition": "Aggregate turnover band.",
    "allowed_values": ["low", "high"],
}


def test_defaults_are_registration_level_and_not_per_financial_year() -> None:
    attribute = AttributeDefinition.from_mapping(BASE)
    assert attribute.level is AttributeLevel.REGISTRATION
    assert attribute.per_financial_year is False


def test_level_and_per_financial_year_are_read_from_the_mapping() -> None:
    attribute = AttributeDefinition.from_mapping(
        {**BASE, "level": "entity", "per_financial_year": True}
    )
    assert attribute.level is AttributeLevel.ENTITY
    assert attribute.per_financial_year is True
    assert [level.value for level in AttributeLevel] == ["entity", "registration", "location"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"level": "country"}, "level"),
        ({"per_financial_year": "yes"}, "per_financial_year"),
        ({"per_financial_year": 1}, "per_financial_year"),
    ],
)
def test_bad_values_are_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(OntologyDefinitionError, match=message):
        AttributeDefinition.from_mapping({**BASE, **overrides})


def test_direct_construction_checks_the_new_fields() -> None:
    with pytest.raises(OntologyDefinitionError, match="level"):
        AttributeDefinition(
            key="k",
            type=AttributeDefinition.from_mapping(BASE).type,
            definition="x.",
            source=AttributeSource.USER_INPUT,
            level="entity",  # type: ignore[arg-type]
            allowed_values=("a", "b"),
        )
    with pytest.raises(OntologyDefinitionError, match="per_financial_year"):
        AttributeDefinition(
            key="k",
            type=AttributeDefinition.from_mapping(BASE).type,
            definition="x.",
            source=AttributeSource.USER_INPUT,
            per_financial_year="no",  # type: ignore[arg-type]
            allowed_values=("a", "b"),
        )


def test_ontology_carries_levels() -> None:
    ontology = Ontology.from_mapping(
        {
            "version": "0.2.0",
            "attributes": [
                {**BASE, "level": "entity", "per_financial_year": True},
                {**BASE, "key": "filing_scheme", "allowed_values": ["a", "b"]},
            ],
        }
    )
    assert ontology.require("turnover_band").level is AttributeLevel.ENTITY
    assert ontology.require("filing_scheme").level is AttributeLevel.REGISTRATION
