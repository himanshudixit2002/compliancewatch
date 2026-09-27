"""The generated pydantic models accept every golden example and behave as tolerant readers."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cw_contracts.events import TOPICS, EventEnvelopeV1

EXAMPLES = Path(__file__).resolve().parents[4] / "events" / "examples"
TOPIC_EXAMPLES = sorted(path for path in EXAMPLES.rglob("*.json") if path.parent.name != "envelope")


def load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


@pytest.mark.parametrize("path", TOPIC_EXAMPLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_example_round_trips_through_the_envelope_and_payload_models(path: Path) -> None:
    message = load(path)
    envelope = EventEnvelopeV1.model_validate(message)
    assert envelope.topic == message["topic"]
    assert envelope.model_dump(mode="json") == message
    model = TOPICS[message["topic"]].model
    payload = model.model_validate(message["payload"])
    assert payload.model_dump(mode="json", exclude_unset=True) == message["payload"]


def test_unknown_payload_fields_are_ignored() -> None:
    message = load(EXAMPLES / "obligation.created" / "filing-with-due-date.json")
    model = TOPICS["obligation.created"].model
    payload = model.model_validate({**message["payload"], "added_in_a_later_minor": "x"})
    assert "added_in_a_later_minor" not in payload.model_dump()


def test_missing_required_field_is_rejected() -> None:
    message = load(EXAMPLES / "profile.updated" / "turnover-band-by-user.json")
    payload = dict(message["payload"])
    del payload["changed_attributes"]
    with pytest.raises(ValidationError, match="changed_attributes"):
        TOPICS["profile.updated"].model.model_validate(payload)


def test_enum_values_are_checked() -> None:
    message = load(EXAMPLES / "applicability.decided" / "applies-after-rule-published.json")
    payload = {**message["payload"], "result": "maybe"}
    with pytest.raises(ValidationError, match="result"):
        TOPICS["applicability.decided"].model.model_validate(payload)


def test_naive_datetimes_are_rejected() -> None:
    message = load(EXAMPLES / "obligation.due_soon" / "seven-days-first-reminder.json")
    payload = {**message["payload"], "due_at": "2026-10-25T23:59:59"}
    with pytest.raises(ValidationError, match="due_at"):
        TOPICS["obligation.due_soon"].model.model_validate(payload)
