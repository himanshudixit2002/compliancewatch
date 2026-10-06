"""A stored rule extraction: its candidate id, its suggested rule key, the clauses it cites,
and the schema limits a candidate must keep that the parser does not check."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from domain_kernel.documents import DocumentType, clause_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId
from pipeline.domain.candidate import (
    CANDIDATE_SCHEMA,
    candidate_from_mapping,
    conformance_problems,
)
from pipeline.domain.extraction import (
    MAX_ANSWER_CHARS,
    ExtractionOutcome,
    RuleExtraction,
    candidate_id_for,
    suggest_rule_key,
)
from pipeline.domain.issues import Issue

DOCUMENT = DocumentId(UUID(int=7))
PROMPT = "extraction.rule_candidate@1"
NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)


def fields(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "title": "Example: the due date of an example return is extended",
        "summary": "An example notification extends the due date of FORM GSTR-3B.",
        "doc_kind": "notification",
        "change_kind": "extension",
        "effective_from": None,
        "effective_to": None,
        "references": [],
        "applies_to": [],
        "obligation": None,
        "recurrence": None,
        "amounts": [],
        "citations": [{"clause_ref": "en.p3", "quote": "extends the due date"}],
        "confidence": 0.9,
    }
    values.update(overrides)
    return values


def extraction(**overrides: object) -> RuleExtraction:
    values: dict[str, object] = {
        "document_id": DOCUMENT,
        "prompt_version": PROMPT,
        "candidate_id": candidate_id_for(DOCUMENT, PROMPT),
        "outcome": ExtractionOutcome.EXTRACTED,
        "model": "scripted/golden",
        "attempts": 1,
        "source_key": "cbic_notifications",
        "doc_type": DocumentType.NOTIFICATION,
        "regulator": "CBIC",
        "issues": (),
        "citation_count": 1,
        "confidence": 0.9,
        "needs_review": False,
        "answer": "{}",
        "ontology_version": "0.2.0",
        "extracted_at": NOW,
        "fields": candidate_from_mapping(fields()).to_mapping(),
    }
    values.update(overrides)
    return RuleExtraction(**values)  # type: ignore[arg-type]


MONTHLY = {
    "attribute": "filing_scheme",
    "operator": "eq",
    "value": "regular_monthly",
    "clause_ref": "en.p3",
}


@pytest.mark.parametrize(
    ("overrides", "key"),
    [
        (
            {
                "applies_to": [MONTHLY],
                "obligation": {
                    "title": "File FORM GSTR-3B for the example month",
                    "steps": [],
                    "evidence_type": "filing_acknowledgement",
                    "due_in_days": None,
                    "clause_ref": "en.p3",
                },
            },
            "gstr3b_monthly",
        ),
        (
            {
                "title": "Example: the annual return in FORM GSTR-9",
                "recurrence": {
                    "frequency": "annual",
                    "due_day": 31,
                    "due_month_offset": 9,
                    "clause_ref": "en.p3",
                },
            },
            "gstr9_annual",
        ),
        (
            {
                "summary": "An example: the statement in FORM ITC-04 is furnished each half year",
                "recurrence": {
                    "frequency": "half_yearly",
                    "due_day": 25,
                    "due_month_offset": 1,
                    "clause_ref": "en.p3",
                },
            },
            "itc04_half_yearly",
        ),
        (
            {
                "applies_to": [
                    {
                        "attribute": "filing_scheme",
                        "operator": "eq",
                        "value": "regular_qrmp",
                        "clause_ref": "en.p3",
                    }
                ]
            },
            "gstr3b_quarterly",
        ),
        ({"applies_to": []}, None),
        (
            {
                "summary": "An example notification about the e-way bill",
                "applies_to": [MONTHLY],
                "citations": [{"clause_ref": "en.p3", "quote": "the e-way bill"}],
                "title": "Example notification",
            },
            None,
        ),
        (
            {
                "applies_to": [
                    {
                        "attribute": "filing_scheme",
                        "operator": "eq",
                        "value": "composition",
                        "clause_ref": "en.p3",
                    }
                ]
            },
            None,
        ),
    ],
    ids=["form-and-scheme", "recurrence", "itc04", "qrmp", "no-cadence", "no-form", "composition"],
)
def test_the_suggested_rule_key_is_a_form_and_its_cadence(
    overrides: dict[str, object], key: str | None
) -> None:
    assert suggest_rule_key(candidate_from_mapping(fields(**overrides))) == key


def test_the_candidate_id_is_the_documents_and_the_prompts() -> None:
    assert candidate_id_for(DOCUMENT, PROMPT) == candidate_id_for(DOCUMENT, PROMPT)
    assert candidate_id_for(DOCUMENT, PROMPT) != candidate_id_for(DOCUMENT, "extraction.x@2")
    with pytest.raises(InvariantViolationError, match="derived"):
        extraction(candidate_id=candidate_id_for(DOCUMENT, "extraction.x@2"))


def test_an_extraction_keeps_its_rules() -> None:
    with pytest.raises(InvariantViolationError, match="no rule is extracted from a statute"):
        extraction(doc_type=DocumentType.STATUTE)
    with pytest.raises(InvariantViolationError, match="has fields"):
        extraction(outcome=ExtractionOutcome.UNPARSEABLE)
    with pytest.raises(InvariantViolationError, match="needs review"):
        extraction(outcome=ExtractionOutcome.UNPARSEABLE, fields=None)
    with pytest.raises(InvariantViolationError, match="kept to"):
        extraction(answer="x" * (MAX_ANSWER_CHARS + 1))
    with pytest.raises(InvariantViolationError, match="prompt_version"):
        extraction(prompt_version="rule_candidate")


def test_the_clauses_it_leans_on_and_its_event() -> None:
    stored = extraction(
        fields=candidate_from_mapping(
            fields(
                applies_to=[MONTHLY],
                citations=[
                    {"clause_ref": "en.p4", "quote": "comes into effect"},
                    {"clause_ref": "en.p3", "quote": "extends the due date"},
                ],
            )
        ).to_mapping()
    )
    assert stored.clause_ids() == (
        clause_id_for(DOCUMENT, "en.p3"),
        clause_id_for(DOCUMENT, "en.p4"),
    )
    event = stored.event(SourceId(UUID(int=1)))
    assert (event.candidate_id, event.outcome, event.suggested_rule_key) == (
        stored.candidate_id,
        "extracted",
        "gstr3b_monthly",
    )
    assert event.clause_ids == stored.clause_ids()
    assert event.candidate is not None
    unparseable = extraction(
        outcome=ExtractionOutcome.UNPARSEABLE,
        fields=None,
        needs_review=True,
        issues=(Issue("output_unparseable", "not JSON"),),
    )
    assert (unparseable.candidate(), unparseable.clause_ids()) == (None, ())
    assert unparseable.event(SourceId(UUID(int=1))).candidate is None


def plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [plain(item) for item in value]
    return value


VALIDATOR = Draft202012Validator(
    plain(CANDIDATE_SCHEMA),  # type: ignore[arg-type]
    format_checker=Draft202012Validator.FORMAT_CHECKER,
)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"citations": []},
        {"title": "t" * 201},
        {"summary": "s" * 1001},
        {
            "recurrence": {
                "frequency": "monthly",
                "due_day": 20,
                "due_month_offset": 25,
                "clause_ref": "en.p3",
            }
        },
        {
            "recurrence": {
                "frequency": "monthly",
                "due_day": 20,
                "due_month_offset": 24,
                "clause_ref": "en.p3",
            }
        },
        {"title": "t" * 200, "summary": "s" * 1000},
    ],
    ids=[
        "fits",
        "no-citation",
        "long-title",
        "long-summary",
        "far-offset",
        "offset-at-limit",
        "at-the-limits",
    ],
)
def test_what_the_parser_reads_fits_the_schema_exactly_when_nothing_is_wrong(
    overrides: dict[str, object],
) -> None:
    answer = json.dumps(fields(**overrides))
    read = candidate_from_mapping(json.loads(answer))
    fits = VALIDATOR.is_valid(plain(read.to_mapping()))
    assert fits is not bool(conformance_problems(read))
