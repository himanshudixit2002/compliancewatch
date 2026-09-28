from uuid import UUID

import pytest

from domain_kernel.documents import Clause, DocumentType, ParsedDocument
from domain_kernel.ids import DocumentId
from domain_kernel.ontology import Ontology
from ontology import load
from pipeline.application.validators import validate
from pipeline.domain.candidate import candidate_from_mapping

CLAUSES = (
    Clause("en.p1", "Notification No. 01/2026 - Central Tax"),
    Clause(
        "en.p2",
        "the Commissioner extends the due date for furnishing FORM GSTR-3B for March, 2026 till "
        "the twenty -first day of April, 2026 for registered persons whose aggregate turnover "
        "exceeds Rs. 2 crore, as required under notification No. 83/2020 - Central Tax.",
    ),
    Clause("en.p3", "This notification shall come into effect from 20th day of April, 2026."),
)
DOC = ParsedDocument(DocumentId(UUID(int=3)), DocumentType.NOTIFICATION, "n", CLAUSES)
GOOD: dict[str, object] = {
    "title": "t",
    "summary": "s",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": "2026-04-20",
    "effective_to": None,
    "references": ["83/2020-Central Tax"],
    "applies_to": [
        {
            "attribute": "turnover_band",
            "operator": "gt",
            "value": "1_5_crore_to_2_crore",
            "clause_ref": "en.p2",
        }
    ],
    "obligation": {
        "title": "File",
        "steps": [],
        "evidence_type": "",
        "due_in_days": None,
        "clause_ref": "en.p2",
    },
    "recurrence": None,
    "amounts": [{"label": "turnover", "value_inr": 20000000, "clause_ref": "en.p2"}],
    "citations": [
        {"clause_ref": "en.p2", "quote": "extends the due date for furnishing FORM GSTR-3B"},
        {"clause_ref": "en.p3", "quote": "come into effect from 20th day of April, 2026"},
    ],
    "confidence": 0.95,
}


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return load()


def test_a_grounded_candidate_passes(ontology: Ontology) -> None:
    report = validate(candidate_from_mapping(GOOD), DOC, ontology)
    assert report.ok
    assert report.citation_count == 2
    assert not report.needs_review


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"citations": [{"clause_ref": "en.p9", "quote": "x"}]}, "citation_missing_clause"),
        (
            {"citations": [{"clause_ref": "en.p2", "quote": "words not in the clause"}]},
            "citation_quote_not_found",
        ),
        (
            {"amounts": [{"label": "t", "value_inr": 50000000, "clause_ref": "en.p2"}]},
            "amount_not_in_clause",
        ),
        ({"effective_from": "2026-04-25"}, "date_not_in_cited_clauses"),
        ({"effective_from": "2026-04-20", "effective_to": "2026-04-19"}, "dates_out_of_order"),
        (
            {
                "recurrence": {
                    "frequency": "monthly",
                    "due_day": 25,
                    "due_month_offset": 0,
                    "clause_ref": "en.p2",
                }
            },
            "due_day_not_in_clause",
        ),
        (
            {
                "obligation": {
                    "title": "x",
                    "steps": [],
                    "evidence_type": "",
                    "due_in_days": 45,
                    "clause_ref": "en.p2",
                }
            },
            "due_in_days_not_in_clause",
        ),
        (
            {
                "applies_to": [
                    {"attribute": "nope", "operator": "eq", "value": 1, "clause_ref": "en.p2"}
                ]
            },
            "predicate_invalid",
        ),
        (
            {
                "applies_to": [
                    {
                        "attribute": "registration_type",
                        "operator": "eq",
                        "value": "alien",
                        "clause_ref": "en.p2",
                    }
                ]
            },
            "predicate_invalid",
        ),
        (
            {
                "applies_to": [
                    {
                        "attribute": "employee_count",
                        "operator": "contains",
                        "value": 3,
                        "clause_ref": "en.p2",
                    }
                ]
            },
            "predicate_invalid",
        ),
        ({"references": ["Notification No."]}, "reference_empty"),
    ],
)
def test_each_check_reports_its_code(
    ontology: Ontology, changes: dict[str, object], code: str
) -> None:
    report = validate(candidate_from_mapping(dict(GOOD, **changes)), DOC, ontology)
    assert code in report.codes(), report.issues
    assert report.needs_review


def test_low_confidence_needs_review_without_issues(ontology: Ontology) -> None:
    report = validate(candidate_from_mapping(dict(GOOD, confidence=0.5)), DOC, ontology)
    assert report.ok
    assert report.needs_review


def test_an_uncited_predicate_clause_is_reported(ontology: Ontology) -> None:
    changes = {
        "applies_to": [
            {"attribute": "supply_type", "operator": "eq", "value": "goods", "clause_ref": "en.p7"}
        ]
    }
    report = validate(candidate_from_mapping(dict(GOOD, **changes)), DOC, ontology)
    assert ("citation_missing_clause", "en.p7") in {(i.code, i.clause_ref) for i in report.issues}
