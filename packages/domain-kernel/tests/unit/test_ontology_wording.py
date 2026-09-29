import dataclasses
from collections.abc import Mapping

import pytest

from domain_kernel.errors import OntologyDefinitionError
from domain_kernel.ontology import (
    LANGUAGE_PATTERN,
    AttributeWording,
    Ontology,
    OntologyWording,
    WordingReviewStatus,
)

ONTOLOGY = Ontology.from_mapping(
    {
        "version": "1.2.3",
        "attributes": [
            {
                "key": "supply_type",
                "type": "enum",
                "source": "user_input",
                "definition": "What the business supplies.",
                "allowed_values": ["goods", "services", "both"],
            },
            {
                "key": "state_codes",
                "type": "enum_set",
                "source": "gstin_lookup",
                "definition": "States in which the business is registered.",
                "allowed_values": ["07", "29"],
            },
            {
                "key": "employee_count",
                "type": "integer",
                "source": "user_input",
                "definition": "People on the payroll.",
                "min": 0,
            },
            {
                "key": "size_class",
                "type": "enum",
                "source": "derived",
                "definition": "Size class computed from the turnover band.",
                "allowed_values": ["micro", "small"],
            },
        ],
    }
)


def _item(key: str, **fields: object) -> dict[str, object]:
    return {"key": key, **fields}


def _wording(*items: object, **top: object) -> dict[str, object]:
    data: dict[str, object] = {
        "version": "0.1.0",
        "language": "en",
        "review_status": "needs_review",
        "attributes": list(items),
    }
    data.update(top)
    return data


SUPPLY_LABELS = {"goods": "Goods", "services": "Services", "both": "Both"}
FITTING_ITEMS: tuple[dict[str, object], ...] = (
    _item(
        "supply_type",
        question="Does the business supply goods, services, or both?",
        help="Pick both when it supplies either.",
        labels=SUPPLY_LABELS,
    ),
    _item(
        "state_codes",
        question="In which states is the business registered?",
        labels={"07": "Delhi", "29": "Karnataka"},
    ),
    _item("employee_count", question="How many people are on the payroll?"),
)
FITTING = _wording(*FITTING_ITEMS)


def _fitting_items() -> list[dict[str, object]]:
    return [dict(item) for item in FITTING_ITEMS]


@pytest.fixture
def wording() -> OntologyWording:
    return OntologyWording.from_mapping(FITTING)


# ---- loading ---------------------------------------------------------------------------------


def test_a_fitting_wording_loads_and_passes(wording: OntologyWording) -> None:
    assert wording.version == "0.1.0"
    assert wording.language == "en"
    assert wording.review_status is WordingReviewStatus.NEEDS_REVIEW
    assert [item.key for item in wording.attributes] == [
        "supply_type",
        "state_codes",
        "employee_count",
    ]
    assert wording.check_against(ONTOLOGY) == []


def test_for_key_returns_the_entry_or_none(wording: OntologyWording) -> None:
    supply = wording.for_key("supply_type")
    assert supply is not None
    assert supply.question.endswith("?")
    assert supply.help == "Pick both when it supplies either."
    assert dict(supply.value_labels) == {"goods": "Goods", "services": "Services", "both": "Both"}
    employees = wording.for_key("employee_count")
    assert employees is not None
    assert (employees.help, dict(employees.value_labels)) == ("", {})
    assert wording.for_key("size_class") is None


def test_label_falls_back_to_the_raw_value(wording: OntologyWording) -> None:
    assert wording.label("state_codes", "29") == "Karnataka"
    assert wording.label("state_codes", "33") == "33"
    assert wording.label("size_class", "micro") == "micro"
    supply = wording.for_key("supply_type")
    assert supply is not None
    assert supply.label("both") == "Both"
    assert supply.label("neither") == "neither"


def test_value_labels_are_read_only(wording: OntologyWording) -> None:
    supply = wording.for_key("supply_type")
    assert supply is not None
    with pytest.raises(TypeError):
        supply.value_labels["goods"] = "Things"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        supply.question = "Changed?"  # type: ignore[misc]


def test_equal_wording_compares_equal_and_hashes() -> None:
    first = AttributeWording("supply_type", "What?", value_labels={"goods": "Goods"})
    second = AttributeWording("supply_type", "What?", value_labels={"goods": "Goods"})
    assert first == second
    assert hash(first) == hash(second)
    assert OntologyWording.from_mapping(FITTING) == OntologyWording.from_mapping(FITTING)


def test_the_reviewed_status_is_accepted() -> None:
    reviewed = OntologyWording.from_mapping(_wording(review_status="reviewed"))
    assert reviewed.review_status is WordingReviewStatus.REVIEWED


@pytest.mark.parametrize("language", ["en", "hi", "ta"])
def test_two_letter_languages_are_accepted(language: str) -> None:
    assert LANGUAGE_PATTERN.fullmatch(language)
    assert OntologyWording.from_mapping(_wording(language=language)).language == language


# ---- check_against ---------------------------------------------------------------------------


def _problems(*items: object) -> list[str]:
    return OntologyWording.from_mapping(_wording(*items)).check_against(ONTOLOGY)


def test_an_unknown_key_is_reported() -> None:
    extra = _item("trade_name", question="What is it called?")
    assert _problems(*FITTING_ITEMS, extra) == ["trade_name: not an attribute of ontology 1.2.3"]


def test_a_label_for_a_value_outside_allowed_values_is_reported() -> None:
    items = _fitting_items()
    items[0]["labels"] = {**SUPPLY_LABELS, "neither": "Neither"}
    items[2]["labels"] = {"many": "Many"}
    assert _problems(*items) == [
        "supply_type: label for 'neither', which is not an allowed value",
        "employee_count: label for 'many', which is not an allowed value",
    ]


def test_an_unlabelled_enum_value_is_reported() -> None:
    items = _fitting_items()
    items[1]["labels"] = {"07": "Delhi"}
    assert _problems(*items) == ["state_codes: value '29' has no label"]


def test_a_missing_question_is_reported() -> None:
    items = _fitting_items()
    del items[2]["question"]
    items[0]["question"] = "Goods, services or both"
    assert _problems(*items) == [
        "supply_type: question does not end with '?'",
        "employee_count: no question",
    ]


def test_an_attribute_without_wording_reports_its_question_and_labels() -> None:
    assert _problems(FITTING_ITEMS[0], FITTING_ITEMS[2]) == [
        "state_codes: no question",
        "state_codes: value '07' has no label",
        "state_codes: value '29' has no label",
    ]


def test_a_derived_attribute_needs_no_question_or_labels() -> None:
    assert _problems(*FITTING_ITEMS, _item("size_class", labels={"micro": "Micro"})) == []


def test_a_derived_attribute_still_may_not_label_unknown_values() -> None:
    derived = _item("size_class", labels={"large": "Large"})
    assert _problems(*FITTING_ITEMS, derived) == [
        "size_class: label for 'large', which is not an allowed value"
    ]


# ---- structural problems raise ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("top", "message"),
    [
        ({"version": "1.0"}, "semver"),
        ({"version": 1}, "version must be a non-empty string"),
        ({"language": "english"}, "two-letter code"),
        ({"language": "EN"}, "two-letter code"),
        ({"review_status": "approved"}, "review_status 'approved' is not one of"),
        ({"review_status": True}, "review_status must be a string"),
        ({"attributes": "supply_type"}, "attributes must be a list"),
        ({"extra": 1}, r"unknown keys \['extra'\]"),
    ],
)
def test_a_malformed_top_level_raises(top: Mapping[str, object], message: str) -> None:
    with pytest.raises(OntologyDefinitionError, match=message):
        OntologyWording.from_mapping(_wording(**top))


def test_missing_top_level_keys_raise() -> None:
    with pytest.raises(OntologyDefinitionError, match=r"missing keys \['language'"):
        OntologyWording.from_mapping({"version": "0.1.0", "attributes": []})


def test_a_non_mapping_raises() -> None:
    with pytest.raises(OntologyDefinitionError, match="wording must be a mapping"):
        OntologyWording.from_mapping(["version"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("item", "message"),
    [
        ("supply_type", r"attributes\[0\] must be a mapping"),
        ({"question": "What?"}, r"attributes\[0\]: missing keys \['key'\]"),
        ({"key": "Supply"}, "must be lowercase snake_case"),
        ({"key": "supply_type", "wording": "x"}, r"unknown keys \['wording'\]"),
        ({"key": "supply_type", "question": 3}, "question must be a string when given"),
        ({"key": "supply_type", "help": ["x"]}, "help must be a string when given"),
        ({"key": "supply_type", "question": " What? "}, "must not start or end with whitespace"),
        ({"key": "supply_type", "labels": ["goods"]}, "labels must be a mapping"),
        ({"key": "supply_type", "labels": {1: "One"}}, "keys must be strings"),
        ({"key": "supply_type", "labels": {" goods": "Goods"}}, "surrounding whitespace"),
        ({"key": "supply_type", "labels": {"goods": ""}}, "must not be blank"),
        ({"key": "supply_type", "labels": {"goods": 5}}, "must be str"),
        (
            {"key": "supply_type", "labels": {"goods": "Goods", "both": "Goods"}},
            "label 'Goods' names two values",
        ),
    ],
)
def test_a_malformed_attribute_item_raises(item: object, message: str) -> None:
    with pytest.raises(OntologyDefinitionError, match=message) as caught:
        OntologyWording.from_mapping(_wording(item))
    assert "attributes[0]" in caught.value.detail


def test_a_duplicate_key_raises() -> None:
    item = _item("supply_type", question="What?")
    with pytest.raises(OntologyDefinitionError, match=r"attributes\[1\]: duplicate key"):
        OntologyWording.from_mapping(_wording(item, item))


def test_direct_construction_checks_types() -> None:
    with pytest.raises(OntologyDefinitionError, match="review_status must be WordingReviewStatus"):
        OntologyWording("0.1.0", "en", "needs_review", ())  # type: ignore[arg-type]
    with pytest.raises(OntologyDefinitionError, match=r"attributes\[0\] must be AttributeWording"):
        OntologyWording("0.1.0", "en", WordingReviewStatus.REVIEWED, ({"key": "x"},))  # type: ignore[arg-type]
    with pytest.raises(OntologyDefinitionError, match="value_labels must be a mapping"):
        AttributeWording("supply_type", "What?", value_labels=[("goods", "Goods")])  # type: ignore[arg-type]
    with pytest.raises(OntologyDefinitionError, match="wording key must be str"):
        AttributeWording(3, "What?")  # type: ignore[arg-type]
    with pytest.raises(OntologyDefinitionError, match="wording language must be str"):
        OntologyWording("0.1.0", None, WordingReviewStatus.REVIEWED, ())  # type: ignore[arg-type]
