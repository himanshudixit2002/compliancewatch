import importlib.metadata
import re
from pathlib import Path

import pytest

import ontology
from domain_kernel.ontology import AttributeType, Ontology
from ontology import VERSION, OntologyCheckError, data_path, load, parse

EXPECTED_COUNT = 16
_KEY = re.compile(r"[a-z][a-z0-9_]*")


@pytest.fixture(scope="module")
def loaded() -> Ontology:
    return load()


def test_version_agrees_everywhere(loaded: Ontology) -> None:
    assert loaded.version == VERSION == importlib.metadata.version("ontology")


def test_attribute_count_and_key_shape(loaded: Ontology) -> None:
    keys = [attribute.key for attribute in loaded.attributes]
    assert len(keys) == EXPECTED_COUNT
    assert len(set(keys)) == EXPECTED_COUNT
    assert all(_KEY.fullmatch(key) for key in keys)


def test_spot_checks(loaded: Ontology) -> None:
    registration = loaded.require("registration_type")
    assert registration.type is AttributeType.ENUM
    assert "composition" in registration.allowed_values
    states = loaded.require("state_codes")
    assert states.type is AttributeType.ENUM_SET
    assert len(states.allowed_values) == 38
    employees = loaded.require("employee_count")
    assert employees.type is AttributeType.INTEGER
    assert (employees.minimum, employees.maximum) == (0, 100000)


def test_turnover_bands_ascend(loaded: Ontology) -> None:
    band = loaded.require("turnover_band")
    assert band.type is AttributeType.ORDERED_ENUM
    assert band.allowed_values[0] == "upto_10_lakh"
    assert band.allowed_values[-1] == "above_500_crore"
    ranks = [band.rank(value) for value in band.allowed_values]
    assert ranks == list(range(len(band.allowed_values)))
    assert loaded.require("peak_turnover_band").allowed_values == band.allowed_values


def test_data_path_is_the_packaged_file() -> None:
    path = data_path()
    assert path.is_file()
    assert Path(str(path)).parts[-3:] == ("ontology", "data", "attributes.yaml")
    assert parse(path.read_text(encoding="utf-8"))["version"] == VERSION


def test_parse_rejects_a_non_mapping() -> None:
    with pytest.raises(OntologyCheckError, match="mapping"):
        parse("- version\n- attributes\n")


def test_load_rejects_a_version_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ontology, "VERSION", "9.9.9")
    with pytest.raises(OntologyCheckError, match="does not match"):
        load()


def test_load_reports_house_rule_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    draft = tmp_path / "attributes.yaml"
    draft.write_text(
        'version: "0.1.0"\n'
        "attributes:\n"
        "  - key: supply_type\n"
        "    type: enum\n"
        "    source: user_input\n"
        "    definition: No full stop\n"
        "    allowed_values: [goods, services]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ontology, "data_path", lambda: draft)
    with pytest.raises(OntologyCheckError, match="period"):
        load()
