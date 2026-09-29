import re
from pathlib import Path

import pytest
import yaml

import ontology
from domain_kernel.errors import OntologyDefinitionError
from domain_kernel.ontology import AttributeSource, Ontology, OntologyWording, WordingReviewStatus
from ontology import (
    WORDING_LANGUAGES,
    WORDING_VERSION,
    OntologyCheckError,
    data_path,
    load,
    load_wording,
    wording_path,
)

_STATE_COMMENT = re.compile(r'^\s*- "(\d{2})" # (.+)$')


@pytest.fixture(scope="module")
def loaded() -> Ontology:
    return load()


@pytest.fixture(scope="module")
def wording() -> OntologyWording:
    return load_wording()


def _base(name: str) -> str:
    """A place name without its parenthesised note."""
    return name.split(" (", 1)[0]


def _band_label(band: str) -> str:
    """The label a turnover band key reads as: ``75_lakh_to_1_5_crore`` is
    ``75 lakh to 1.5 crore``."""
    text = band.replace("upto_", "Up to ").replace("above_", "Above ").replace("_to_", " to ")
    return re.sub(r"(\d)_(\d)", r"\1.\2", text).replace("_", " ")


def test_the_packaged_wording_fits_the_ontology(loaded: Ontology, wording: OntologyWording) -> None:
    assert wording.check_against(loaded) == []
    assert wording.version == WORDING_VERSION
    assert wording.language == "en"
    assert WORDING_LANGUAGES == ("en",)


def test_the_wording_is_a_draft_until_an_analyst_reviews_it(wording: OntologyWording) -> None:
    assert wording.review_status is WordingReviewStatus.NEEDS_REVIEW
    header = wording_path().read_text(encoding="utf-8").split("version:", 1)[0]
    assert "Draft wording; an analyst reviews it before launch (guide section 14)." in header


def test_one_entry_per_attribute_in_ontology_order(
    loaded: Ontology, wording: OntologyWording
) -> None:
    assert [item.key for item in wording.attributes] == [item.key for item in loaded]
    assert len(wording.attributes) == 17


def test_every_attribute_a_person_answers_has_a_question(
    loaded: Ontology, wording: OntologyWording
) -> None:
    for definition in loaded:
        entry = wording.for_key(definition.key)
        assert entry is not None, definition.key
        if definition.source is not AttributeSource.DERIVED:
            assert entry.question.endswith("?"), definition.key
            assert entry.question[0].isupper(), definition.key
        if entry.help:
            assert entry.help.endswith("."), definition.key


def test_every_allowed_value_has_a_label(loaded: Ontology, wording: OntologyWording) -> None:
    for definition in loaded:
        entry = wording.for_key(definition.key)
        assert entry is not None
        assert set(entry.value_labels) == set(definition.allowed_values), definition.key


def test_state_labels_come_from_the_comments_in_the_attribute_file(
    wording: OntologyWording,
) -> None:
    comments = {
        match[1]: match[2]
        for line in data_path().read_text(encoding="utf-8").splitlines()
        if (match := _STATE_COMMENT.match(line))
    }
    assert len(comments) == 38
    for code, comment in comments.items():
        label = wording.label("state_codes", code)
        assert _base(label) == _base(comment), code
        assert ("legacy" in label) == ("legacy" in comment), code


def test_turnover_band_labels_restate_the_band_keys(
    loaded: Ontology, wording: OntologyWording
) -> None:
    bands = loaded.require("turnover_band").allowed_values
    for band in bands:
        assert wording.label("turnover_band", band) == _band_label(band)
        assert wording.label("peak_turnover_band", band) == _band_label(band)
    assert _band_label("75_lakh_to_1_5_crore") == "75 lakh to 1.5 crore"
    assert _band_label("upto_10_lakh") == "Up to 10 lakh"


def test_label_falls_back_to_the_value(wording: OntologyWording) -> None:
    assert wording.label("supply_type", "both") == "Both goods and services"
    assert wording.label("supply_type", "neither") == "neither"
    assert wording.label("employee_count", "12") == "12"


def test_a_language_that_is_not_shipped_is_refused() -> None:
    with pytest.raises(OntologyCheckError, match="no wording for language 'hi'"):
        load_wording("hi")
    with pytest.raises(OntologyCheckError, match="no wording for language"):
        wording_path("../attributes")


def test_a_version_mismatch_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ontology, "WORDING_VERSION", "9.9.9")
    with pytest.raises(OntologyCheckError, match=r"does not match WORDING_VERSION 9\.9\.9"):
        load_wording()


def _draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: object) -> None:
    draft = tmp_path / "wording.en.yaml"
    draft.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(ontology, "wording_path", lambda language="en": draft)


def _packaged() -> dict[str, object]:
    data = yaml.safe_load(wording_path().read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_a_draft_that_misses_a_question_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _packaged()
    items = data["attributes"]
    assert isinstance(items, list)
    del items[-1]["question"]
    _draft(tmp_path, monkeypatch, data)
    with pytest.raises(OntologyCheckError, match="employee_count: no question"):
        load_wording()


def test_a_draft_in_another_language_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _draft(tmp_path, monkeypatch, {**_packaged(), "language": "hi"})
    with pytest.raises(OntologyCheckError, match="file language hi does not match en"):
        load_wording()


def test_a_draft_that_is_not_a_mapping_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _draft(tmp_path, monkeypatch, ["version", "attributes"])
    with pytest.raises(OntologyCheckError, match="must be a mapping"):
        load_wording()


def test_a_malformed_draft_is_a_definition_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _draft(tmp_path, monkeypatch, {**_packaged(), "review_status": "approved"})
    with pytest.raises(OntologyDefinitionError, match="review_status"):
        load_wording()
