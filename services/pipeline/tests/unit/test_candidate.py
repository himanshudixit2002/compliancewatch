import json
from datetime import date

import pytest

from pipeline.domain.candidate import (
    CANDIDATE_SCHEMA,
    CandidateParseError,
    candidate_from_mapping,
    parse_candidate,
)

FULL = {
    "title": "Due date extended",
    "summary": "The due date moves.",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": "2026-04-20",
    "effective_to": None,
    "references": ["83/2020-Central Tax"],
    "applies_to": [
        {
            "attribute": "filing_scheme",
            "operator": "eq",
            "value": "regular_monthly",
            "clause_ref": "en.p3",
        },
        {
            "attribute": "state_codes",
            "operator": "contains_any",
            "value": ["27", "29"],
            "clause_ref": "en.p3",
        },
    ],
    "obligation": {
        "title": "File GSTR-3B",
        "steps": ["File it"],
        "evidence_type": "filing_acknowledgement",
        "due_in_days": None,
        "clause_ref": "en.p3",
    },
    "recurrence": {
        "frequency": "monthly",
        "due_day": 20,
        "due_month_offset": 0,
        "clause_ref": "en.p3",
    },
    "amounts": [{"label": "threshold", "value_inr": 20000000, "clause_ref": "en.p3"}],
    "citations": [{"clause_ref": "en.p3", "quote": "extends the due date"}],
    "confidence": 0.9,
}


def test_round_trip_through_json() -> None:
    fields = parse_candidate(json.dumps(FULL))
    assert fields.effective_from == date(2026, 4, 20)
    assert fields.applies_to[1].value == ("27", "29")
    assert fields.recurrence is not None
    assert fields.recurrence.due_day == 20
    assert fields.cited_refs() == {"en.p3"}
    again = candidate_from_mapping(fields.to_mapping())
    assert again == fields
    assert set(FULL) == set(CANDIDATE_SCHEMA["required"])


def test_nulls_and_empty_lists_are_allowed() -> None:
    data = dict(FULL, obligation=None, recurrence=None, amounts=[], references=[], applies_to=[])
    fields = candidate_from_mapping(data)
    assert fields.obligation is None
    assert fields.amounts == ()
    assert fields.extra == {}


def test_unknown_keys_are_kept_aside() -> None:
    assert candidate_from_mapping(dict(FULL, note="x")).extra == {"note": "x"}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"doc_kind": "placeholder"}, "doc_kind must be one of"),
        ({"effective_from": "20 April 2026"}, "ISO date"),
        ({"confidence": 1.5}, "between 0 and 1"),
        ({"citations": [{"clause_ref": "en.p1"}]}, "quote must be non-empty"),
        (
            {"applies_to": [{"attribute": "x", "operator": "like", "value": 1, "clause_ref": "a"}]},
            "operator",
        ),
        ({"recurrence": {"frequency": "monthly", "due_day": 40, "clause_ref": "a"}}, "due_day"),
        ({"amounts": [{"label": "t", "value_inr": -1, "clause_ref": "a"}]}, "whole number"),
        ({"references": "83/2020"}, "must be a list"),
    ],
)
def test_bad_shapes_are_parse_errors(changes: dict[str, object], message: str) -> None:
    with pytest.raises(CandidateParseError, match=message):
        candidate_from_mapping(dict(FULL, **changes))


def test_not_json_and_missing_fields() -> None:
    with pytest.raises(CandidateParseError, match="not JSON"):
        parse_candidate("nope")
    with pytest.raises(CandidateParseError, match="must be a JSON object"):
        parse_candidate("[]")
    with pytest.raises(CandidateParseError, match="missing fields: summary"):
        candidate_from_mapping({k: v for k, v in FULL.items() if k != "summary"})
