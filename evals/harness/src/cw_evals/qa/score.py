"""Scores for one qa case and their aggregates.

A citation is valid when it names a clause of the world, the clause's document was published
on or before the question's date, and the quote holds in the clause (``quote_matches`` and no
number, form code or month the clause lacks). A case is grounded when it is answered, every
citation is valid, at least one expected citation is among them, every expected fact is in the
answer and nothing in ``must_not_mention`` is. Facts are read from the answer text: dates in
ISO, "21 April 2026", "21st April, 2026", "April 21, 2026" or ordinal-word form ("the
twenty-first day of April, 2026"), every expected date among them; text casefolded, dashes
folded and whitespace collapsed; entities by the canonical names the mention grammar finds in
the answer.

With the KAG layer on, a case the labels send through it (answerable, with a scripted plan that
has steps) is grounded only when the KAG layer decided it: a hybrid answer after the KAG layer
fell back does not count for the KAG run. The solver fails when the KAG layer falls back with
``step_failed`` or ``step_budget_exceeded``, and also when a valid plan with steps finds no
clause (``no_evidence``) for an answerable case; for a must-refuse case an empty bundle is the
right result.

The aggregate follows the plan: ``plan_validity``, ``solver_success`` and the first-try share
are over the cases where the KAG layer ran; ``grounded_answer_rate`` and
``false_refusal_rate`` over the answerable cases; ``refusal_accuracy`` over the must-refuse
cases; ``answer_safety`` and ``response_rate`` over every case. A share with nothing to count is
``None`` (reported as n/a), except ``citation_correctness``, which is 1.0 when no citation came
back. Tokens, p95 latency, layer shares and the grounded rate per category and fact source are
reported, not gated.
"""

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

from pydantic import ValidationError

from cw_evals.qa.cases import QaCase
from domain_kernel.citations import DASHES, evidence_tokens_missing, quote_matches
from domain_kernel.documents import Clause, DocumentType, ParsedDocument, document_id_for
from domain_kernel.knowledge import EntityType, normalise_name
from pipeline.domain.grammar import mentions_for
from qa.api.schemas import AskOut

PLAN: Final = "qa.plan"
ANSWER: Final = "qa.answer"
SOLVER_FAILURES: Final = frozenset({"step_failed", "step_budget_exceeded"})
NO_EVIDENCE: Final = "no_evidence"
MONTHS: Final = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH = "(" + "|".join(MONTHS) + ")"
_ISO = re.compile(r"\b([0-9]{4})-([0-9]{2})-([0-9]{2})\b")
_DAY_MONTH_YEAR = re.compile(
    r"\b([0-9]{1,2})\s*(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?" + _MONTH + r",?\s+([0-9]{4})\b",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR = re.compile(
    r"\b" + _MONTH + r"\s+([0-9]{1,2})(?:st|nd|rd|th)?,?\s+([0-9]{4})\b", re.IGNORECASE
)
_ORDINALS: Final = (
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
    "twentieth",
)
ORDINAL_DAYS: Final = {
    **{word: day for day, word in enumerate(_ORDINALS, start=1)},
    **{f"twenty-{word}": 20 + day for day, word in enumerate(_ORDINALS[:9], start=1)},
    "thirtieth": 30,
    "thirty-first": 31,
}
"""A day of the month written as an ordinal word, hyphenated."""
_ORDINAL = (
    "("
    + "|".join(
        word.replace("-", r"\s*-?\s*") for word in sorted(ORDINAL_DAYS, key=len, reverse=True)
    )
    + ")"
)
_WORD_DAY_MONTH_YEAR = re.compile(
    r"\b" + _ORDINAL + r"\s+(?:day\s+of\s+)?" + _MONTH + r",?\s+([0-9]{4})\b", re.IGNORECASE
)
_MONTH_WORD_DAY_YEAR = re.compile(
    r"\b" + _MONTH + r"\s+" + _ORDINAL + r",?\s+([0-9]{4})\b", re.IGNORECASE
)
_AMOUNT = re.compile(r"(?:\u20b9|\brs\.?|\binr)\s*[0-9]|\b(?:crore|lakh|rupees?)\b", re.IGNORECASE)
_FOLD = str.maketrans(dict.fromkeys(DASHES, "-"))


def dates_in(text: str) -> set[date]:
    """Every date written in ``text`` in one of the forms the module docstring lists."""
    found: set[date] = set()
    for year, month, day in _ISO.findall(text):
        _add(found, int(year), int(month), int(day))
    for day, month, year in _DAY_MONTH_YEAR.findall(text):
        _add(found, int(year), MONTHS.index(month.casefold()) + 1, int(day))
    for month, day, year in _MONTH_DAY_YEAR.findall(text):
        _add(found, int(year), MONTHS.index(month.casefold()) + 1, int(day))
    for word, month, year in _WORD_DAY_MONTH_YEAR.findall(text):
        _add(found, int(year), MONTHS.index(month.casefold()) + 1, _ordinal_day(word))
    for month, word, year in _MONTH_WORD_DAY_YEAR.findall(text):
        _add(found, int(year), MONTHS.index(month.casefold()) + 1, _ordinal_day(word))
    return found


def _ordinal_day(word: str) -> int:
    parts = re.split(r"[\s-]+", word.casefold())
    return ORDINAL_DAYS["-".join(part for part in parts if part)]


def _add(found: set[date], year: int, month: int, day: int) -> None:
    try:
        found.add(date(year, month, day))
    except ValueError:
        return


def has_amount(text: str) -> bool:
    """Whether ``text`` names a sum of money: a currency sign with a number, or crore, lakh or
    rupees."""
    return _AMOUNT.search(text) is not None


def folded(text: str) -> str:
    return " ".join(text.translate(_FOLD).casefold().split())


def entities_in(text: str) -> set[tuple[EntityType, str]]:
    """The entities the mention grammar finds in ``text``, by type and canonical name."""
    document = ParsedDocument(
        document_id=document_id_for("0" * 64),
        doc_type=DocumentType.NOTIFICATION,
        title="",
        clauses=(Clause(clause_ref="answer", text=text),),
    )
    return {(m.entity_type, m.proposed_name) for m in mentions_for(document) if m.proposed_name}


@dataclass(frozen=True, slots=True)
class ModelCall:
    question_id: str
    prompt: str
    stage: str
    attempt: int
    status: int
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class WorldClause:
    document: str
    clause_ref: str
    text: str
    published_on: date


@dataclass(frozen=True, slots=True)
class Asked:
    """One question as the harness saw it: the answer (or the error), the model calls and what
    the scripted provider noted while answering it."""

    case: QaCase
    status: int | None
    body: Mapping[str, Any] | None = None
    error: str = ""
    calls: tuple[ModelCall, ...] = ()
    latency_ms: float = 0.0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QaScore:
    case_id: str
    category: str
    fact_source: str
    label_status: str
    answerable: bool
    responded: bool
    outcome: str | None = None
    layer: str | None = None
    reason: str | None = None
    planned: bool = False
    plan_valid: bool = False
    plan_first_try: bool | None = None
    solver_failed: bool = False
    kag_expected: bool = False
    """The KAG layer was on and the labels send the case through it (see the module docstring)."""
    citations: int = 0
    valid_citations: int = 0
    correct_citations: int = 0
    expected_cited: bool = False
    facts_ok: bool = False
    problems: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0

    @property
    def answered(self) -> bool:
        return self.responded and self.outcome == "answered"

    @property
    def refused(self) -> bool:
        return self.responded and self.outcome == "not_covered"

    @property
    def grounded(self) -> bool:
        return (
            self.answered
            and self.valid_citations == self.citations
            and self.expected_cited
            and self.facts_ok
            and (not self.kag_expected or self.layer == "kag")
        )

    @property
    def safe(self) -> bool:
        return self.refused or (self.answered and self.valid_citations == self.citations)

    @property
    def passed(self) -> bool:
        """What the case asks for: grounded when answerable, refused otherwise."""
        return self.grounded if self.answerable else self.refused


@dataclass(frozen=True, slots=True)
class QaAggregate:
    cases: int
    plan_validity: float | None
    plan_first_try_validity: float | None
    solver_success: float | None
    citation_correctness: float
    grounded_answer_rate: float | None
    refusal_accuracy: float | None
    false_refusal_rate: float | None
    answer_safety: float | None
    response_rate: float | None
    input_tokens: int = 0
    output_tokens: int = 0
    p95_latency_ms: float = 0.0
    layer_shares: dict[str, float] = field(default_factory=dict)
    grounded_by_category: dict[str, float | None] = field(default_factory=dict)
    grounded_by_fact_source: dict[str, float | None] = field(default_factory=dict)


def score_case(
    asked: Asked, clauses: Mapping[tuple[str, str], WorldClause], *, kag_on: bool = False
) -> QaScore:
    """``clauses`` maps (document id as text, clause ref) to the world's clause; ``kag_on`` says
    the KAG layer was on for the question."""
    case = asked.case
    tokens = {
        "input_tokens": sum(call.input_tokens for call in asked.calls),
        "output_tokens": sum(call.output_tokens for call in asked.calls),
    }
    base: dict[str, Any] = {
        "case_id": case.case_id,
        "category": case.category,
        "fact_source": case.fact_source,
        "label_status": case.label_status,
        "answerable": case.answerable,
        "latency_ms": asked.latency_ms,
        **tokens,
    }
    body = _valid_body(asked)
    if body is None:
        return QaScore(responded=False, problems=(asked.error or f"HTTP {asked.status}",), **base)
    layers = {item.layer.value: item for item in body.layers}
    kag = layers.get("kag")
    plan_calls = [call for call in asked.calls if call.prompt.startswith(PLAN + "@")]
    planned = kag is not None
    plan_valid = planned and body.plan is not None
    kag_expected = kag_on and case.answerable and _has_steps(case.scripted.plan)
    solver_failed = (
        kag is not None
        and kag.result.value == "fallback"
        and kag.reason is not None
        and (
            kag.reason.value in SOLVER_FAILURES
            or (kag.reason.value == NO_EVIDENCE and case.answerable and _has_steps(body.plan))
        )
    )
    problems: list[str] = list(asked.notes)
    expected = {(ref.document, ref.clause_ref) for ref in case.expected.citations}
    valid = correct = 0
    cited_expected = False
    for citation in body.citations:
        clause = clauses.get((str(citation.document_id), citation.clause_ref))
        ok = (
            clause is not None
            and clause.published_on <= case.as_of
            and quote_matches(citation.quote, clause.text)
            and not evidence_tokens_missing(citation.quote, clause.text)
        )
        if not ok:
            problems.append(f"citation {citation.clause_ref} of {citation.document_id} is invalid")
            continue
        assert clause is not None
        valid += 1
        if (clause.document, clause.clause_ref) in expected:
            correct += 1
            cited_expected = True
        else:
            problems.append(f"citation {clause.document} {clause.clause_ref} is not expected")
    facts_ok = True
    if body.outcome.value == "answered":
        missing = _missing_facts(case, body.answer)
        problems.extend(missing)
        facts_ok = not missing
    if case.answerable and body.outcome.value != "answered":
        problems.append(f"not covered ({body.reason.value if body.reason else 'no reason'})")
    elif kag_expected and body.layer.value != "kag":
        why = f" after {kag.reason.value}" if kag is not None and kag.reason is not None else ""
        problems.append(f"decided by the {body.layer.value} layer{why}, not kag")
    if not case.answerable and body.outcome.value == "answered":
        problems.append("answered a question it must refuse")
    return QaScore(
        responded=True,
        outcome=body.outcome.value,
        layer=body.layer.value,
        reason=None if body.reason is None else body.reason.value,
        planned=planned,
        plan_valid=plan_valid,
        plan_first_try=(plan_valid and len(plan_calls) == 1) if plan_calls else None,
        solver_failed=solver_failed,
        kag_expected=kag_expected,
        citations=len(body.citations),
        valid_citations=valid,
        correct_citations=correct,
        expected_cited=cited_expected,
        facts_ok=facts_ok,
        problems=tuple(problems),
        **base,
    )


def _has_steps(plan: Mapping[str, Any] | None) -> bool:
    return bool(plan and plan.get("steps"))


def _valid_body(asked: Asked) -> AskOut | None:
    if asked.status != 200 or asked.body is None:
        return None
    try:
        return AskOut.model_validate(asked.body)
    except ValidationError:
        return None


def _missing_facts(case: QaCase, answer: str) -> list[str]:
    problems: list[str] = []
    text = folded(answer)
    written = dates_in(answer)
    entities: set[tuple[EntityType, str]] | None = None
    for fact in case.expected.facts:
        if fact.kind == "date":
            if date.fromisoformat(fact.value) not in written:
                problems.append(f"date {fact.value} is not in the answer")
        elif fact.kind == "text":
            if folded(fact.value) not in text:
                problems.append(f"{fact.value!r} is not in the answer")
        elif fact.kind == "entity" and fact.entity_type is not None:
            entities = entities_in(answer) if entities is None else entities
            wanted = (fact.entity_type, normalise_name(fact.entity_type, fact.value))
            if wanted not in entities:
                problems.append(f"{fact.entity_type.value} {fact.value} is not in the answer")
    for phrase in case.expected.must_not_mention:
        if folded(phrase) in text:
            problems.append(f"the answer mentions {phrase!r}")
    return problems


def aggregate(scores: Sequence[QaScore]) -> QaAggregate:
    answerable = [s for s in scores if s.answerable]
    refusable = [s for s in scores if not s.answerable]
    planned = [s for s in scores if s.planned]
    with_plan = [s for s in planned if s.plan_valid]
    first_tries = [s.plan_first_try for s in planned if s.plan_first_try is not None]
    citations = sum(s.citations for s in scores)
    responded = [s for s in scores if s.responded]
    layers: dict[str, int] = {}
    for s in responded:
        if s.layer is not None:
            layers[s.layer] = layers.get(s.layer, 0) + 1
    return QaAggregate(
        cases=len(scores),
        plan_validity=_share((s.plan_valid for s in planned), len(planned)),
        plan_first_try_validity=_share(first_tries, len(first_tries)),
        solver_success=_share((not s.solver_failed for s in with_plan), len(with_plan)),
        citation_correctness=sum(s.correct_citations for s in scores) / citations
        if citations
        else 1.0,
        grounded_answer_rate=_share((s.grounded for s in answerable), len(answerable)),
        refusal_accuracy=_share((s.refused for s in refusable), len(refusable)),
        false_refusal_rate=_share((s.refused for s in answerable), len(answerable)),
        answer_safety=_share((s.safe for s in scores), len(scores)),
        response_rate=_share((s.responded for s in scores), len(scores)),
        input_tokens=sum(s.input_tokens for s in scores),
        output_tokens=sum(s.output_tokens for s in scores),
        p95_latency_ms=p95([s.latency_ms for s in scores]),
        layer_shares={k: v / len(responded) for k, v in sorted(layers.items())},
        grounded_by_category=_grouped(answerable, lambda s: s.category),
        grounded_by_fact_source=_grouped(answerable, lambda s: s.fact_source),
    )


def p95(values: Sequence[float]) -> float:
    """The 95th percentile by nearest rank; 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _share(values: Iterable[bool], whole: int) -> float | None:
    return sum(1 for value in values if value) / whole if whole else None


def _grouped(scores: Sequence[QaScore], key: Any) -> dict[str, float | None]:
    groups: dict[str, list[QaScore]] = {}
    for score in scores:
        groups.setdefault(key(score), []).append(score)
    return {
        name: _share((s.grounded for s in items), len(items))
        for name, items in sorted(groups.items())
    }
