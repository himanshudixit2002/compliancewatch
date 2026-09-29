"""The answer schema, reading an answer, and the citation post-check."""

import json
from uuid import UUID

import pytest

from domain_kernel.ids import ClauseId, DocumentId
from qa.domain.answer import (
    MAX_CITATIONS,
    NOT_COVERED_TEXT,
    Answer,
    AnswerCitation,
    AnswerDraft,
    AnswerInvalidError,
    DraftCitation,
    Outcome,
    Reason,
    answer_schema,
    check_citations,
    cite,
    parse_answer,
)
from qa.domain.evidence import BundleBuilder, EvidenceBundle

DOCUMENT = DocumentId(UUID(int=5))
CLAUSE = (
    "The time limit for furnishing the return in FORM GSTR-3B for the month of March, 2026 "
    "is extended till the 24th day of April, 2026."
)


def bundle() -> EvidenceBundle:
    builder = BundleBuilder()
    builder.add_clause(
        clause_id=ClauseId(UUID(int=1)),
        document_id=DOCUMENT,
        clause_ref="en.p3",
        text=CLAUSE,
        step_id="s2",
    )
    return builder.build()


def draft(*citations: tuple[str, str], covered: bool = True, text: str = "24 April") -> AnswerDraft:
    return AnswerDraft(covered, text, tuple(DraftCitation(c, q) for c, q in citations))


def test_the_schema_closes_the_labels() -> None:
    schema = answer_schema(["C1", "C2"])
    citation = schema["properties"]["citations"]["items"]
    assert citation["properties"]["clause"]["enum"] == ["C1", "C2"]
    assert schema["properties"]["citations"]["maxItems"] == MAX_CITATIONS
    assert schema["required"] == ["answer", "citations", "covered"]
    assert schema["additionalProperties"] is False
    with pytest.raises(ValueError, match="at least one clause"):
        answer_schema([])


def test_a_valid_answer_is_read() -> None:
    citations = [{"clause": "C1", "quote": "q" * 9}]
    text = json.dumps({"covered": True, "answer": "It is 24 April 2026.", "citations": citations})
    assert parse_answer(text) == draft(("C1", "q" * 9), text="It is 24 April 2026.")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("not json", "not JSON"),
        ("[]", "an object with covered"),
        (json.dumps({"covered": True, "answer": "a"}), "an object with covered"),
        (json.dumps({"covered": "yes", "answer": "a", "citations": []}), "covered must be"),
        (json.dumps({"covered": True, "answer": 3, "citations": []}), "answer must be text"),
        (json.dumps({"covered": True, "answer": "a", "citations": {}}), "citations must be"),
        (
            json.dumps({"covered": True, "answer": "a", "citations": [{"clause": "C1"}]}),
            "citation 1 must be",
        ),
    ],
)
def test_a_malformed_answer_is_refused(text: str, problem: str) -> None:
    with pytest.raises(AnswerInvalidError, match=problem):
        parse_answer(text)


def test_an_exact_quote_passes_the_check() -> None:
    quote = "is extended till the 24th day of April, 2026"
    assert check_citations(draft(("C1", quote)), bundle()) == ()
    assert cite(draft(("C1", quote), ("C1", quote)), bundle()) == (
        AnswerCitation("en.p3", DOCUMENT, quote),
    )


def test_extraction_noise_still_passes() -> None:
    quote = "FORM GSTR - 3B for the month of March, 2026"
    assert check_citations(draft(("C1", quote)), bundle()) == ()


@pytest.mark.parametrize(
    ("citation", "problem"),
    [
        (("C2", "is extended till the 24th day"), "not a listed clause"),
        (("C1", "short"), "8 to 400 characters"),
        (("C1", "the late fee is waived for every taxpayer"), "quote is not in C1"),
        (("C1", "is extended till the 25th day of April, 2026"), "25th"),
    ],
)
def test_a_wrong_citation_is_a_problem(citation: tuple[str, str], problem: str) -> None:
    (found,) = check_citations(draft(citation), bundle())
    assert problem in found


def test_a_covered_answer_needs_text_and_a_citation() -> None:
    assert check_citations(draft(text=" "), bundle()) == (
        "a covered answer needs answer text",
        "a covered answer cites at least one clause",
    )


def test_a_declined_answer_is_not_checked() -> None:
    assert check_citations(draft(("C9", "x"), covered=False), bundle()) == ()


def test_cite_skips_unknown_labels() -> None:
    assert cite(draft(("C7", "anything at all")), bundle()) == ()


def test_not_covered_has_the_fixed_text_and_a_reason() -> None:
    answer = Answer.not_covered(Reason.NO_EVIDENCE)
    assert (answer.outcome, answer.text, answer.citations, answer.reason) == (
        Outcome.NOT_COVERED,
        NOT_COVERED_TEXT,
        (),
        Reason.NO_EVIDENCE,
    )
    answered = Answer.answered("yes", [AnswerCitation("en.p1", DOCUMENT, "q" * 8)])
    assert (answered.outcome, answered.reason) == (Outcome.ANSWERED, None)


def test_reason_codes_are_closed() -> None:
    assert [reason.value for reason in Reason] == [
        "plan_invalid",
        "planner_unavailable",
        "planner_deferred",
        "step_budget_exceeded",
        "step_failed",
        "no_evidence",
        "answerer_declined",
        "citation_check_failed",
    ]
