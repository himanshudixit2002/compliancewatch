"""KAG golden cases as the harness reads them: one question, what a grounded answer states and
cites (or that it must be refused), and the scripted model answers.

A case file is ``evals/golden/qa/kag/cases/<case_id>.yaml``. ``expected.facts`` are what the
answer must state: a ``date`` (ISO), a ``text`` (compared casefolded) or an ``entity`` (a type
and a name, compared by canonical name). Each carries its support: a quote of a world clause
(``document``, ``clause_ref``, ``quote``) or a seed calendar field (``seed_rule``, ``field``,
``value``). ``scripted.plan`` lists, per step, the fields its operator uses; ``planner_json``
writes the others as null, the shape ``qa.plan@1`` answers in. ``scripted.answer`` is the
``qa.answer@1`` answer with each citation naming its clause by document and clause ref (or by a
label, when the answer is wrong on purpose); ``scripted_answer`` writes the label the evidence
in the prompt gives that clause. Loading checks shapes only; ``cw_evals.qa.check`` checks the
content against the world, the seed calendar and qa's schemas.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import yaml

from domain_kernel.knowledge import EntityType
from qa.domain.plan_schema import FIELDS

CASES_DIR: Final = Path("qa") / "kag" / "cases"
CATEGORIES: Final = ("single_hop", "multi_hop", "date_threshold", "must_refuse")
FACT_SOURCES: Final = ("recorded_clause", "seed_calendar", "mixed", "none")
OUTCOMES: Final = ("answered", "not_covered")
FACT_KINDS: Final = ("date", "text", "entity")
LABEL_STATUSES: Final = ("draft", "reviewed", "approved")
CASE_ID: Final = re.compile(r"[A-Za-z0-9._-]{1,64}")
"""A case id is also the ``x-request-id`` of its question, so it has that header's shape."""
_HEADING: Final = re.compile(r"^\[(C[0-9]+)\] (\S+)(?: \((.+)\))?$", re.MULTILINE)
"""A clause heading of the rendered evidence: label, clause ref, the document's number."""
KEYS: Final = frozenset(
    {
        "case_id",
        "category",
        "label_status",
        "labelled_by",
        "reviewed_by",
        "fact_source",
        "question",
        "as_of",
        "business",
        "fy",
        "expected",
        "scripted",
        "refusal_reason",
        "notes",
    }
)


class CaseError(ValueError):
    """A case file is not a well-formed case."""


@dataclass(frozen=True, slots=True)
class ClauseSupport:
    document: str
    clause_ref: str
    quote: str


@dataclass(frozen=True, slots=True)
class SeedSupport:
    seed_rule: str
    field: str
    """A dotted path into the seed rule, such as ``recurrence.due_day``."""
    value: object


@dataclass(frozen=True, slots=True)
class Fact:
    kind: str
    value: str
    """ISO for a date, the text for a text, the name for an entity."""
    support: ClauseSupport | SeedSupport
    entity_type: EntityType | None = None


@dataclass(frozen=True, slots=True)
class CitationRef:
    document: str
    clause_ref: str


@dataclass(frozen=True, slots=True)
class Expected:
    outcome: str
    facts: tuple[Fact, ...] = ()
    must_not_mention: tuple[str, ...] = ()
    citations: tuple[CitationRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Scripted:
    """The model's answers for the case; ``None`` where the case expects no such call."""

    plan: Mapping[str, Any] | None = None
    plan_retry: Mapping[str, Any] | None = None
    answer: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class QaCase:
    case_id: str
    category: str
    label_status: str
    labelled_by: str
    reviewed_by: str
    fact_source: str
    question: str
    as_of: date
    business: str | None
    fy: str | None
    expected: Expected
    scripted: Scripted
    path: Path
    refusal_reason: str | None = None
    notes: str = ""

    @property
    def answerable(self) -> bool:
        return self.expected.outcome == "answered"


def planner_json(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The plan as ``qa.plan@1`` writes it: every step with every field, null when unused."""
    steps = []
    for raw in plan.get("steps") or []:
        step: dict[str, Any] = dict.fromkeys(FIELDS)
        step.update({str(key): _iso(value) for key, value in raw.items()})
        steps.append(step)
    return {"as_of": _iso(plan.get("as_of")), "steps": steps}


def plan_text(plan: Mapping[str, Any]) -> str:
    return json.dumps(planner_json(plan))


def scripted_answer(
    answer: Mapping[str, Any], prompt: str, sources: Mapping[str, str]
) -> dict[str, Any]:
    """The case's answer as ``qa.answer@1`` writes it, each clause named by the label the
    evidence in ``prompt`` gives it. ``sources`` maps a world document key to its number."""
    labels = {(source, clause_ref): label for label, clause_ref, source in _HEADING.findall(prompt)}
    citations = []
    for item in answer.get("citations") or []:
        label = item.get("clause")
        if label is None:
            document, clause_ref = str(item["document"]), str(item["clause_ref"])
            label = labels.get(
                (sources.get(document, document), clause_ref), f"{document}/{clause_ref}"
            )
        citations.append({"clause": str(label), "quote": str(item["quote"])})
    return {"covered": answer["covered"], "answer": answer["answer"], "citations": citations}


def load_qa_cases(golden: Path) -> list[QaCase]:
    """Every case under ``golden`` (``evals/golden``), in file name order."""
    return [load_qa_case(path) for path in sorted((golden / CASES_DIR).glob("*.yaml"))]


def load_qa_case(path: Path) -> QaCase:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CaseError(f"{path.name}: not YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CaseError(f"{path.name}: a case is a mapping")
    missing = sorted(KEYS - set(data) - {"refusal_reason", "notes", "fy"})
    unknown = sorted(set(data) - KEYS)
    if missing or unknown:
        raise CaseError(f"{path.name}: missing {missing or '-'}, unknown {unknown or '-'}")
    try:
        return _case(data, path)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CaseError):
            raise
        raise CaseError(f"{path.name}: {exc}") from exc


def _case(data: Mapping[str, Any], path: Path) -> QaCase:
    expected = data["expected"]
    if not isinstance(expected, dict):
        raise CaseError(f"{path.name}: expected is a mapping")
    scripted = data["scripted"] or {}
    if not isinstance(scripted, dict):
        raise CaseError(f"{path.name}: scripted is a mapping")
    unknown = sorted(set(scripted) - {"plan", "plan_retry", "answer"})
    if unknown:
        raise CaseError(f"{path.name}: scripted has unknown keys {unknown}")
    return QaCase(
        case_id=str(data["case_id"]),
        category=str(data["category"]),
        label_status=str(data["label_status"]),
        labelled_by=str(data["labelled_by"] or ""),
        reviewed_by=str(data["reviewed_by"] or ""),
        fact_source=str(data["fact_source"]),
        question=str(data["question"]),
        as_of=_day(data["as_of"]),
        business=None if data["business"] is None else str(data["business"]),
        fy=None if data.get("fy") is None else str(data["fy"]),
        expected=Expected(
            outcome=str(expected["outcome"]),
            facts=tuple(_fact(item) for item in expected.get("facts") or ()),
            must_not_mention=tuple(str(item) for item in expected.get("must_not_mention") or ()),
            citations=tuple(
                CitationRef(str(item["document"]), str(item["clause_ref"]))
                for item in expected.get("citations") or ()
            ),
        ),
        scripted=Scripted(
            plan=_mapping(scripted.get("plan"), "scripted.plan"),
            plan_retry=_mapping(scripted.get("plan_retry"), "scripted.plan_retry"),
            answer=_mapping(scripted.get("answer"), "scripted.answer"),
        ),
        path=path,
        refusal_reason=None if data.get("refusal_reason") is None else str(data["refusal_reason"]),
        notes=str(data.get("notes") or ""),
    )


def _fact(item: Mapping[str, Any]) -> Fact:
    support = item["support"]
    if "seed_rule" in support:
        backing: ClauseSupport | SeedSupport = SeedSupport(
            str(support["seed_rule"]), str(support["field"]), support["value"]
        )
    else:
        backing = ClauseSupport(
            str(support["document"]), str(support["clause_ref"]), str(support["quote"])
        )
    kind = str(item["kind"])
    entity_type = EntityType(str(item["type"])) if kind == "entity" else None
    value = item["value"]
    return Fact(kind, _iso(value) if kind == "date" else str(value), backing, entity_type)


def _mapping(value: object, name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CaseError(f"{name} is a mapping")
    return value


def _day(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _iso(value: object) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def by_category(cases: Sequence[QaCase]) -> dict[str, int]:
    counts = dict.fromkeys(CATEGORIES, 0)
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1
    return counts
