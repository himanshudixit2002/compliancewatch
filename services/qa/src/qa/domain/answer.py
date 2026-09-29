"""Answers, how the answer prompt may reply, and the check every cited quote must pass.

The answer schema is built per call: a citation names one of the bundle's clause labels, so
the model cannot cite a clause it was not given. ``check_citations`` then holds each quote to
the clause text the way the rulebook holds a rule's citation (ADR-006): a fuzzy match of at
least 0.85 and no number, form code or month that the clause does not carry. An answer that
fails twice is ``not_covered``; an answer that covers the question cites at least once.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from domain_kernel.citations import evidence_tokens_missing, quote_matches
from domain_kernel.ids import DocumentId
from qa.domain.evidence import EvidenceBundle

MAX_ANSWER_CHARS: Final = 1_200
MAX_CITATIONS: Final = 6
MIN_QUOTE_CHARS: Final = 8
MAX_QUOTE_CHARS: Final = 400
NOT_COVERED_TEXT: Final = (
    "I cannot answer this from the published rules and notifications in force on that date."
)
"""The whole answer whenever the outcome is ``not_covered``."""

_FIELDS = frozenset({"covered", "answer", "citations"})


class Outcome(StrEnum):
    ANSWERED = "answered"
    NOT_COVERED = "not_covered"


class Layer(StrEnum):
    """The layers a question passes through, cheapest first (ADR-012)."""

    STRUCTURED = "structured"
    KAG = "kag"
    HYBRID = "hybrid"


class LayerResult(StrEnum):
    """``passed`` means the layer did not apply; ``fallback`` that it tried and handed on."""

    ANSWERED = "answered"
    NOT_COVERED = "not_covered"
    PASSED = "passed"
    FALLBACK = "fallback"


class Reason(StrEnum):
    """Why a layer fell back or did not cover the question. Closed: the evals count them."""

    PLAN_INVALID = "plan_invalid"
    PLANNER_UNAVAILABLE = "planner_unavailable"
    PLANNER_DEFERRED = "planner_deferred"
    STEP_BUDGET_EXCEEDED = "step_budget_exceeded"
    STEP_FAILED = "step_failed"
    NO_EVIDENCE = "no_evidence"
    ANSWERER_DECLINED = "answerer_declined"
    CITATION_CHECK_FAILED = "citation_check_failed"


class AnswerInvalidError(ValueError):
    """The answer is not an object of the answer schema; ``problems`` says why."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True, slots=True)
class DraftCitation:
    clause: str
    """A bundle label such as ``C2``."""
    quote: str


@dataclass(frozen=True, slots=True)
class AnswerDraft:
    """The model's answer, structurally valid; ``check_citations`` judges the quotes."""

    covered: bool
    answer: str
    citations: tuple[DraftCitation, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerCitation:
    clause_ref: str
    document_id: DocumentId
    quote: str


@dataclass(frozen=True, slots=True)
class Answer:
    """What a layer decided: answered with citations, or not covered with the reason."""

    outcome: Outcome
    text: str
    citations: tuple[AnswerCitation, ...] = ()
    reason: Reason | None = None

    @classmethod
    def answered(cls, text: str, citations: Sequence[AnswerCitation]) -> "Answer":
        return cls(Outcome.ANSWERED, text, tuple(citations))

    @classmethod
    def not_covered(cls, reason: Reason) -> "Answer":
        return cls(Outcome.NOT_COVERED, NOT_COVERED_TEXT, (), reason)


def answer_schema(labels: Sequence[str]) -> dict[str, Any]:
    """The JSON schema of one answer call: citations name only these labels."""
    if not labels:
        raise ValueError("an answer schema needs at least one clause label")
    citation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["clause", "quote"],
        "properties": {
            "clause": {"type": "string", "enum": list(labels)},
            "quote": {
                "type": "string",
                "minLength": MIN_QUOTE_CHARS,
                "maxLength": MAX_QUOTE_CHARS,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "QaAnswer",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_FIELDS),
        "properties": {
            "covered": {"type": "boolean"},
            "answer": {"type": "string", "maxLength": MAX_ANSWER_CHARS},
            "citations": {"type": "array", "maxItems": MAX_CITATIONS, "items": citation},
        },
    }


def parse_answer(text: str) -> AnswerDraft:
    """The draft in the answer; raises ``AnswerInvalidError`` when its shape is wrong."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise AnswerInvalidError([f"not JSON: {exc}"]) from exc
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise AnswerInvalidError(["the answer must be an object with covered, answer, citations"])
    problems: list[str] = []
    covered, answer, items = data["covered"], data["answer"], data["citations"]
    if not isinstance(covered, bool):
        problems.append("covered must be true or false")
    if not isinstance(answer, str) or len(answer) > MAX_ANSWER_CHARS:
        problems.append(f"answer must be text of at most {MAX_ANSWER_CHARS} characters")
    if not isinstance(items, list) or len(items) > MAX_CITATIONS:
        problems.append(f"citations must be a list of at most {MAX_CITATIONS}")
        items = []
    citations: list[DraftCitation] = []
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or set(item) != {"clause", "quote"}
            or not isinstance(item["clause"], str)
            or not isinstance(item["quote"], str)
        ):
            problems.append(f"citation {index + 1} must be an object with clause and quote")
            continue
        citations.append(DraftCitation(item["clause"], item["quote"]))
    if problems:
        raise AnswerInvalidError(problems)
    return AnswerDraft(bool(covered), str(answer), tuple(citations))


def check_citations(draft: AnswerDraft, bundle: EvidenceBundle) -> tuple[str, ...]:
    """Everything wrong with the draft's citations; empty when a covered draft may stand."""
    if not draft.covered:
        return ()
    problems: list[str] = []
    if not draft.answer.strip():
        problems.append("a covered answer needs answer text")
    if not draft.citations:
        problems.append("a covered answer cites at least one clause")
    for index, citation in enumerate(draft.citations, start=1):
        clause = bundle.clause(citation.clause)
        if clause is None:
            problems.append(f"citation {index} names {citation.clause!r}, not a listed clause")
            continue
        if not MIN_QUOTE_CHARS <= len(citation.quote) <= MAX_QUOTE_CHARS:
            problems.append(
                f"citation {index} quote must be {MIN_QUOTE_CHARS} to {MAX_QUOTE_CHARS} characters"
            )
            continue
        if not quote_matches(citation.quote, clause.text):
            problems.append(f"citation {index} quote is not in {citation.clause}")
            continue
        missing = evidence_tokens_missing(citation.quote, clause.text)
        if missing:
            problems.append(
                f"citation {index} quote has {', '.join(missing)}, which {citation.clause} lacks"
            )
    return tuple(problems)


def cite(draft: AnswerDraft, bundle: EvidenceBundle) -> tuple[AnswerCitation, ...]:
    """The draft's citations as clause refs and documents, once each; call after the check."""
    found: list[AnswerCitation] = []
    for citation in draft.citations:
        clause = bundle.clause(citation.clause)
        if clause is None:
            continue
        cited = AnswerCitation(clause.clause_ref, clause.document_id, citation.quote)
        if cited not in found:
            found.append(cited)
    return tuple(found)
