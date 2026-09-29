"""The schema files, their golden examples and the CHANGELOG agree with each other."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from cw_contracts.events import ENVELOPE_VERSION, TOPICS

EVENTS = Path(__file__).resolve().parents[4] / "events"
SCHEMAS = EVENTS / "schemas"
EXAMPLES = EVENTS / "examples"
CHANGELOG = (EVENTS / "CHANGELOG.md").read_text(encoding="utf-8")
TOPIC_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
FORMAT_CHECKER = Draft202012Validator.FORMAT_CHECKER


def load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def validator_for(path: Path) -> Draft202012Validator:
    return Draft202012Validator(load(path), format_checker=FORMAT_CHECKER)


SCHEMA_FILES = sorted(SCHEMAS.glob("*.json"))
TOPIC_FILES = [path for path in SCHEMA_FILES if path.name != "envelope.v1.json"]
EXAMPLE_FILES = sorted(EXAMPLES.rglob("*.json"))
ENVELOPE = validator_for(SCHEMAS / "envelope.v1.json")


def test_nineteen_schemas_exist() -> None:
    assert len(TOPIC_FILES) == 18
    assert (SCHEMAS / "envelope.v1.json").exists()


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid_2020_12_and_has_the_house_keys(path: Path) -> None:
    document = load(path)
    Draft202012Validator.check_schema(document)
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["type"] == "object"
    assert document["title"]
    assert document["description"].endswith(".")
    assert SEMVER.fullmatch(document["x-version"])
    name = path.name.removesuffix(".json")
    topic, _, major = name.rpartition(".v")
    assert document["$id"] == f"urn:compliancewatch:event:{topic}:v{major}"
    assert document["x-version"].split(".")[0] == major
    if topic != "envelope":
        assert TOPIC_PATTERN.fullmatch(topic)
        assert isinstance(document["x-tenant-scoped"], bool)
        assert document["x-producer"]
        assert "additionalProperties" not in document, "payloads are tolerant readers"
        assert set(document["required"]) <= set(document["properties"])
        for key, prop in document["properties"].items():
            assert prop.get("description"), f"{path.name}: {key} needs a description"


@pytest.mark.parametrize("path", TOPIC_FILES, ids=lambda p: p.name)
def test_every_topic_has_a_changelog_line_and_a_registry_entry(path: Path) -> None:
    document = load(path)
    topic = document["title"]
    assert f"- {topic} {document['x-version']}:" in CHANGELOG
    spec = TOPICS[topic]
    assert spec.version == document["x-version"]
    assert spec.tenant_scoped is document["x-tenant-scoped"]
    assert spec.schema_file == path.name


def test_registry_lists_exactly_the_schema_files() -> None:
    assert sorted(TOPICS) == [load(path)["title"] for path in TOPIC_FILES]
    assert f"- envelope {ENVELOPE_VERSION}:" in CHANGELOG


@pytest.mark.parametrize("path", TOPIC_FILES, ids=lambda p: p.name)
def test_every_topic_has_at_least_one_example(path: Path) -> None:
    topic = load(path)["title"]
    assert list((EXAMPLES / topic).glob("*.json")), f"no example under examples/{topic}"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_example_validates_against_the_envelope_and_its_topic(path: Path) -> None:
    message = load(path)
    ENVELOPE.validate(message)
    assert path.parent.name in {message["topic"], "envelope"}
    if path.parent.name == "envelope":
        return
    spec = TOPICS[message["topic"]]
    assert message["schema_version"] == spec.version
    validator_for(SCHEMAS / spec.schema_file).validate(message["payload"])
    if spec.tenant_scoped:
        assert message["tenant_id"] is not None, "tenant-scoped topics carry a tenant id"
    else:
        assert message["tenant_id"] is None, "regulatory topics carry no tenant id"


def test_envelope_rejects_unknown_fields_and_bad_topics() -> None:
    good = load(EXAMPLES / "envelope" / "regulatory-event.json")
    with pytest.raises(ValidationError):
        ENVELOPE.validate({**good, "extra": 1})
    with pytest.raises(ValidationError):
        ENVELOPE.validate({**good, "topic": "Rule.Published"})
    with pytest.raises(ValidationError):
        ENVELOPE.validate({**good, "schema_version": "1"})
    with pytest.raises(ValidationError):
        ENVELOPE.validate({**good, "occurred_at": "2026-10-01"})


def test_a_missing_required_payload_field_fails() -> None:
    message = load(EXAMPLES / "rule.published" / "first-version.json")
    payload = dict(message["payload"])
    del payload["approved_by"]
    with pytest.raises(ValidationError, match="approved_by"):
        validator_for(SCHEMAS / "rule.published.v1.json").validate(payload)


def test_formats_are_enforced() -> None:
    message = load(EXAMPLES / "obligation.closed" / "completed-by-user.json")
    payload = dict(message["payload"])
    payload["closed_at"] = "not a date"
    with pytest.raises(ValidationError, match="date-time"):
        validator_for(SCHEMAS / "obligation.closed.v1.json").validate(payload)
    payload = dict(message["payload"])
    payload["obligation_id"] = "not-a-uuid"
    with pytest.raises(ValidationError, match="uuid"):
        validator_for(SCHEMAS / "obligation.closed.v1.json").validate(payload)
