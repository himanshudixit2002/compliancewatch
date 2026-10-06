"""Rule candidates in the domain: a rule.candidate.created payload read (the contract's own
examples and what it refuses), the priority and the high-impact suggestion, the draft a candidate
maps to, the analyst's edits on top of it with what they changed, and a candidate's states."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

import ontology as ontology_package
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, RuleVersionId, UserId
from domain_kernel.ontology import Ontology
from rulebook.domain.drafting import DraftEdit, changed_paths, described_paths
from rulebook.domain.errors import (
    CandidateAlreadyDraftedError,
    CandidateNotDraftedError,
    CandidatePayloadInvalidError,
    DraftIncompleteError,
)
from rulebook.domain.intake import (
    HAND_DRAFT_PRIORITY,
    HIGH_IMPACT_PRIORITY,
    REVIEW_PRIORITY,
    ROUTINE_PRIORITY,
    CandidateIntake,
    CandidateOutcome,
    CandidateSummary,
    ExtractionIssue,
    ProposedCitation,
    RuleCandidate,
    RuleCandidateStatus,
    RuleRejectReason,
    draft_content,
    drafted_content,
    suggest_high_impact,
)

EXAMPLES = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "events"
    / "examples"
    / "rule.candidate.created"
)
NOW = datetime(2000, 1, 3, 4, 30, tzinfo=UTC)
ANALYST = UserId(UUID(int=51))
FIELDS: dict[str, Any] = {
    "title": "Example: the due date of the example return is extended",
    "summary": "An example notification extends the due date of the example return.",
    "doc_kind": "notification",
    "change_kind": "none",
    "effective_from": "2000-02-01",
    "effective_to": None,
    "references": [],
    "applies_to": [
        {
            "attribute": "registration_type",
            "operator": "eq",
            "value": "regular",
            "clause_ref": "en.p2",
        },
        {
            "attribute": "filing_scheme",
            "operator": "in",
            "value": ["regular_monthly"],
            "clause_ref": "en.p2",
        },
    ],
    "obligation": {
        "title": "File the example return",
        "steps": ["Furnish the example return"],
        "evidence_type": "filing_acknowledgement",
        "due_in_days": 25,
        "clause_ref": "en.p2",
    },
    "recurrence": None,
    "amounts": [],
    "citations": [
        {"clause_ref": "en.p2", "quote": "extends the due date for the example return"},
        {"clause_ref": "en.p3", "quote": "shall come into effect from the 1st day of February"},
    ],
    "confidence": 0.9,
}


def example(name: str) -> dict[str, Any]:
    message = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    payload: dict[str, Any] = message["payload"]
    return payload


def payload(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "candidate_id": str(UUID(int=7)),
        "document_id": str(UUID(int=8)),
        "regulator": "CBIC",
        "model": "fake/echo",
        "prompt_version": "extraction.rule_candidate@1",
        "confidence": 0.9,
        "citation_count": 2,
        "needs_review": False,
        "outcome": "extracted",
        "candidate": FIELDS,
        "issues": [],
        "suggested_rule_key": "example_monthly",
        "clause_ids": [str(UUID(int=21)), str(UUID(int=22))],
        "doc_type": "notification",
        "source_id": str(UUID(int=9)),
        "source_key": "cbic_notifications",
        "ontology_version": "0.2.0",
    }
    values.update(overrides)
    return {key: value for key, value in values.items() if value is not ...}


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


# ---------------------------------------------------------------- reading the payload


def test_the_contract_examples_read_with_the_regulator_in_lower_case() -> None:
    confident = CandidateIntake.from_payload(example("high-confidence"))
    assert (confident.regulator, confident.outcome, confident.suggested_rule_key) == (
        "cbic",
        CandidateOutcome.EXTRACTED,
        "gstr3b_monthly",
    )
    assert confident.fields is not None
    assert confident.fields["change_kind"] == "extension"
    assert len(confident.clause_ids) == 3
    assert confident.doc_type == "notification"
    unparseable = CandidateIntake.from_payload(example("unparseable"))
    assert unparseable.regulator == "cbic", "the source registry says CBIC"
    assert (unparseable.outcome, unparseable.fields) == (CandidateOutcome.UNPARSEABLE, None)
    assert unparseable.issues == (
        ExtractionIssue("output_unparseable", "not JSON: Expecting value at 0", None),
    )
    old = CandidateIntake.from_payload(example("sent-to-review"))
    assert (old.outcome, old.fields, old.issues, old.clause_ids) == (
        CandidateOutcome.EXTRACTED,
        None,
        (),
        (),
    ), "a 1.0.0 payload has no outcome: it is extracted"


@pytest.mark.parametrize(
    ("overrides", "names"),
    [
        ({"candidate_id": ...}, "candidate_id is missing"),
        ({"candidate_id": "not-a-uuid"}, "candidate_id is not a uuid"),
        ({"document_id": 8}, "document_id is not a uuid"),
        ({"regulator": " "}, "regulator must be a non-blank text"),
        ({"model": "m" * 121}, "model is longer than 120"),
        ({"confidence": 1.5}, "confidence must be a number from 0 to 1"),
        ({"confidence": True}, "confidence must be a number"),
        ({"citation_count": -1}, "citation_count must be a whole number"),
        ({"needs_review": "no"}, "needs_review must be true or false"),
        ({"outcome": "failed"}, "outcome must be one of"),
        ({"outcome": "unparseable"}, "an unparseable extraction has no candidate"),
        ({"candidate": ["a list"]}, "candidate must be an object or null"),
        ({"issues": [{"code": "x"}]}, "issues[0] needs a code and a detail"),
        ({"issues": [{"code": "x", "detail": "", "clause_ref": 3}]}, "clause_ref must be a text"),
        ({"suggested_rule_key": "Not-A-Key"}, "suggested_rule_key is not a rule key"),
        ({"clause_ids": [str(UUID(int=1)), str(UUID(int=1))]}, "lists a clause twice"),
        ({"clause_ids": ["x"]}, "clause_ids holds"),
        ({"doc_type": "press_release"}, "doc_type must be one of"),
    ],
)
def test_a_payload_the_contract_refuses_is_invalid(overrides: dict[str, Any], names: str) -> None:
    with pytest.raises(CandidatePayloadInvalidError, match=names.replace("[", r"\[")):
        CandidateIntake.from_payload(payload(**overrides))


def test_a_payload_that_is_not_an_object_is_invalid() -> None:
    with pytest.raises(CandidatePayloadInvalidError, match="not an object"):
        CandidateIntake.from_payload(["not", "a", "payload"])


def test_fields_the_contract_does_not_name_are_ignored() -> None:
    intake = CandidateIntake.from_payload(payload(later_field={"any": "thing"}))
    assert intake.candidate_id == UUID(int=7)
    assert "later_field" not in intake.stored_payload()


def test_the_stored_payload_keeps_the_rest_of_the_event() -> None:
    stored = CandidateIntake.from_payload(payload()).stored_payload()
    assert stored == {
        "candidate": FIELDS,
        "issues": [],
        "suggested_rule_key": "example_monthly",
        "clause_ids": [str(UUID(int=21)), str(UUID(int=22))],
        "doc_type": "notification",
        "source": {"source_id": str(UUID(int=9)), "source_key": "cbic_notifications"},
        "ontology_version": "0.2.0",
    }
    json.dumps(stored)


# ---------------------------------------------------------------- priority and impact


@pytest.mark.parametrize(
    ("overrides", "priority"),
    [
        ({}, ROUTINE_PRIORITY),
        ({"needs_review": True}, REVIEW_PRIORITY),
        ({"issues": [{"code": "date_not_in_cited_clauses", "detail": "x"}]}, REVIEW_PRIORITY),
        ({"outcome": "unparseable", "candidate": None, "needs_review": True}, HAND_DRAFT_PRIORITY),
        ({"outcome": ..., "candidate": ...}, HAND_DRAFT_PRIORITY),
        ({"candidate": {**FIELDS, "change_kind": "extension"}}, HIGH_IMPACT_PRIORITY),
        (
            {"candidate": {**FIELDS, "change_kind": "withdrawal"}, "needs_review": True},
            HIGH_IMPACT_PRIORITY,
        ),
    ],
)
def test_the_priority_puts_high_impact_first_then_hand_drafting_then_review(
    overrides: dict[str, Any], priority: int
) -> None:
    assert CandidateIntake.from_payload(payload(**overrides)).priority() == priority


def test_each_high_impact_rule_names_its_reason() -> None:
    assert suggest_high_impact(None) == (False, ())
    assert suggest_high_impact(FIELDS) == (False, ())
    assert suggest_high_impact({**FIELDS, "change_kind": "extension"}) == (
        True,
        ("change_kind is extension",),
    )
    assert suggest_high_impact({**FIELDS, "change_kind": "withdrawal"})[0]
    assert suggest_high_impact({**FIELDS, "change_kind": "amendment"}) == (False, ())
    assert suggest_high_impact({**FIELDS, "applies_to": []}) == (
        True,
        ("applies_to is empty, so it applies to every taxpayer",),
    )
    amounts = [{"label": "Example late fee", "value_inr": 50, "clause_ref": "en.p2"}]
    assert suggest_high_impact({**FIELDS, "amounts": amounts}) == (True, ("it names amounts",))
    assert suggest_high_impact({**FIELDS, "applies_to": None}) == (False, ())


# ---------------------------------------------------------------- the draft it proposes


def test_a_candidate_maps_into_the_kernels_forms() -> None:
    proposed = draft_content(FIELDS)
    assert proposed.problems == {}
    assert proposed.values == {
        "title": FIELDS["title"],
        "summary": FIELDS["summary"],
        "specification": {
            "all_of": [
                {"attribute": "registration_type", "operator": "eq", "value": "regular"},
                {"attribute": "filing_scheme", "operator": "in", "value": ["regular_monthly"]},
            ]
        },
        "obligation_template": {
            "title": "File the example return",
            "steps": ["Furnish the example return"],
            "due_in_days": 25,
            "evidence_type": "filing_acknowledgement",
        },
        "recurrence": None,
        "effective_from": date(2000, 2, 1),
        "effective_to": None,
    }
    assert proposed.citations == (
        ProposedCitation("en.p2", "extends the due date for the example return"),
        ProposedCitation("en.p3", "shall come into effect from the 1st day of February"),
    )
    assert proposed.citation_problems == ()
    recurring = draft_content(
        {
            **FIELDS,
            "recurrence": {
                "frequency": "monthly",
                "due_day": 20,
                "due_month_offset": 0,
                "clause_ref": "en.p2",
            },
        }
    )
    assert recurring.values["recurrence"] == {
        "frequency": "monthly",
        "due_day": 20,
        "due_month_offset": 0,
    }


def test_what_does_not_map_is_named_and_left_out() -> None:
    refused = draft_content(
        {
            **FIELDS,
            "title": " ",
            "effective_from": None,
            "effective_to": "not a date",
            "applies_to": [
                {"attribute": "registration_type", "operator": "in", "value": "regular"},
                {"attribute": "Turnover Band", "operator": "eq", "value": "x"},
                "not a condition",
            ],
            "obligation": None,
            "recurrence": {"frequency": "weekly", "due_day": 1, "due_month_offset": 0},
            "citations": [{"clause_ref": "en.p2"}, {"clause_ref": "en.p3", "quote": " "}],
        }
    )
    assert set(refused.problems) == {
        "title",
        "effective_from",
        "effective_to",
        "specification",
        "obligation_template",
        "recurrence",
    }
    assert "specification" not in refused.values, "a refused condition never widens the rule"
    assert len(refused.problems["specification"]) == 3
    assert refused.problems["specification"][0].startswith("applies_to[0] (registration_type in)")
    assert refused.problems["obligation_template"] == ("the candidate names no obligation",)
    assert refused.problems["effective_from"] == ("the candidate gives none",)
    assert refused.problem_list[0].startswith("title: ")
    assert refused.citations == ()
    assert refused.citation_problems == (
        "citations[0] names no clause ref and quote",
        "citations[1] quotes nothing",
    )
    assert draft_content(None).values == {}
    assert draft_content({"title": "x"}).problems["specification"] == (
        "applies_to must be a list of conditions",
    )


def test_an_empty_applies_to_applies_to_everyone() -> None:
    assert draft_content({**FIELDS, "applies_to": []}).values["specification"] == {"all_of": []}


# ---------------------------------------------------------------- the analyst's draft


def test_the_proposal_taken_as_it_is_changes_nothing(ontology: Ontology) -> None:
    drafted = drafted_content(draft_content(FIELDS), None, ontology)
    assert (drafted.title, drafted.effective_from, drafted.todo) == (
        FIELDS["title"],
        date(2000, 2, 1),
        (),
    )
    assert drafted.changed == ()


def test_edits_apply_on_top_and_the_changes_are_named_as_paths(ontology: Ontology) -> None:
    edit = DraftEdit(
        {
            "title": "Example: the example return for January",
            "obligation_template": {
                "title": "File the example return",
                "steps": ["Furnish the example return"],
                "due_in_days": 30,
                "evidence_type": "filing_acknowledgement",
            },
            "specification": {
                "all_of": [
                    {"attribute": "registration_type", "operator": "eq", "value": "regular"},
                    {
                        "attribute": "filing_scheme",
                        "operator": "in",
                        "value": ["regular_monthly", "regular_qrmp"],
                    },
                ]
            },
        }
    )
    drafted = drafted_content(draft_content(FIELDS), edit, ontology)
    assert drafted.obligation_template["due_in_days"] == 30
    assert drafted.changed == (
        "title",
        "specification.all_of[1].value",
        "obligation_template.due_in_days",
    )


def test_every_problem_is_reported_at_once_and_an_edit_fixes_its_field(
    ontology: Ontology,
) -> None:
    proposed = draft_content({**FIELDS, "effective_from": None, "obligation": None})
    with pytest.raises(DraftIncompleteError) as incomplete:
        drafted_content(proposed, None, ontology)
    assert incomplete.value.problems == (
        "obligation_template: the candidate names no obligation",
        "effective_from: the candidate gives none",
    )
    fixed = drafted_content(
        proposed,
        DraftEdit(
            {
                "effective_from": date(2000, 2, 1),
                "obligation_template": {"title": "File the example return", "due_in_days": 1},
            }
        ),
        ontology,
    )
    assert fixed.changed == ("obligation_template", "effective_from")


def test_nothing_to_draft_from_needs_the_analyst_to_give_it_all(ontology: Ontology) -> None:
    with pytest.raises(DraftIncompleteError) as incomplete:
        drafted_content(draft_content(None), DraftEdit({"title": "Example rule"}), ontology)
    assert incomplete.value.problems == (
        "specification: the candidate gives none; send it",
        "obligation_template: the candidate gives none; send it",
        "effective_from: the candidate gives none; send it",
    )


def test_the_content_passes_the_seed_calendars_checks(ontology: Ontology) -> None:
    with pytest.raises(DraftIncompleteError, match=r"needs obligation_template\.due_in_days"):
        drafted_content(
            draft_content({**FIELDS, "obligation": {**FIELDS["obligation"], "due_in_days": None}}),
            None,
            ontology,
        )
    unknown = {
        "all_of": [{"attribute": "example_unknown", "operator": "eq", "value": "x"}],
    }
    with pytest.raises(DraftIncompleteError, match="example_unknown"):
        drafted_content(draft_content(FIELDS), DraftEdit({"specification": unknown}), ontology)
    with pytest.raises(DraftIncompleteError, match="title: at most 300"):
        drafted_content(draft_content(FIELDS), DraftEdit({"title": "x" * 301}), ontology)


def test_changed_paths_compare_item_by_item() -> None:
    before = {"a": {"b": [1, 2], "c": "x"}, "title": "t", "gone": 1}
    after = {"a": {"b": (1, 3), "d": "y"}, "title": "t", "new": 2}
    assert changed_paths(before, after) == ("a.b[1]", "a.c", "a.d", "gone", "new")
    assert changed_paths({"a": [1]}, {"a": [1, 2]}) == ("a",)
    assert changed_paths({"a": {"all_of": [1]}}, {"a": {"any_of": []}}) == ("a",)
    assert described_paths([f"p{index}" for index in range(22)]).endswith("p19 and 2 more")


# ---------------------------------------------------------------- the candidate's states


def candidate(**overrides: Any) -> RuleCandidate:
    intake = CandidateIntake.from_payload(payload())
    received = RuleCandidate.received(
        intake, event_id=uuid4(), at=NOW, suggested_rule_key=intake.suggested_rule_key
    )
    values = {name: getattr(received, name) for name in received.__slots__}
    values.update(overrides)
    return RuleCandidate(**values)


def test_a_candidate_is_drafted_once_then_approved_or_rejected() -> None:
    opened = candidate()
    assert (opened.status, opened.title, opened.high_impact_suggested) == (
        RuleCandidateStatus.OPEN,
        FIELDS["title"],
        False,
    )
    version = RuleVersionId.new()
    drafted = opened.drafted(version)
    assert (drafted.status, drafted.rule_version_id) == (RuleCandidateStatus.DRAFTED, version)
    with pytest.raises(CandidateAlreadyDraftedError):
        drafted.drafted(RuleVersionId.new())
    with pytest.raises(CandidateNotDraftedError):
        opened.approved(by=ANALYST, at=NOW)
    approved = drafted.approved(by=ANALYST, at=NOW)
    assert (approved.status, approved.decided_by) == (RuleCandidateStatus.APPROVED, ANALYST)
    with pytest.raises(InvariantViolationError, match="approved already"):
        approved.rejected(RuleRejectReason.DUPLICATE, by=ANALYST, at=NOW)
    rejected = opened.rejected(RuleRejectReason.NOT_A_RULE, by=ANALYST, at=NOW)
    assert (rejected.status, rejected.reject_reason, rejected.rule_version_id) == (
        RuleCandidateStatus.REJECTED,
        RuleRejectReason.NOT_A_RULE,
        None,
    )
    after_draft = drafted.rejected(RuleRejectReason.WRONG_EXTRACTION, by=ANALYST, at=NOW)
    assert after_draft.rule_version_id == version, "its draft stays"


@pytest.mark.parametrize(
    "overrides",
    [
        {"regulator": "CBIC"},
        {"confidence": 1.2},
        {"status": RuleCandidateStatus.DRAFTED},
        {"rule_version_id": RuleVersionId.new()},
        {"status": RuleCandidateStatus.APPROVED, "rule_version_id": RuleVersionId.new()},
        {"status": RuleCandidateStatus.REJECTED, "decided_by": ANALYST, "decided_at": NOW},
        {"reject_reason": RuleRejectReason.DUPLICATE},
        {"created_at": datetime(2000, 1, 3)},
    ],
)
def test_a_candidate_keeps_its_state_consistent(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvariantViolationError):
        candidate(**overrides)


def test_the_queue_summarises_a_candidate() -> None:
    summary = CandidateSummary.of(candidate(needs_review=True))
    assert (summary.candidate_id, summary.document_id, summary.issue_count) == (
        UUID(int=7),
        DocumentId(UUID(int=8)),
        0,
    )
    assert summary.needs_review
    assert summary.suggested_rule_key == "example_monthly"
    issues = candidate(payload={"issues": [{"code": "c", "detail": "d"}, "junk"]}).issues
    assert issues == (ExtractionIssue("c", "d", None),)
    assert candidate(payload={"candidate": None}).title == ""
