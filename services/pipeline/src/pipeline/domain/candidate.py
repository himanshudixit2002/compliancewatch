"""What the extractor is asked to produce from one document, and how its answer is read.

``CANDIDATE_SCHEMA`` is the JSON Schema sent to the model gateway with every extraction call
and the shape of the ``expected`` block of a golden extraction case, so the model, the labels and
the validators speak one language. ``parse_candidate`` turns the model's text into
``CandidateFields`` without trusting it: a wrong shape is a ``CandidateParseError`` the caller
turns into a candidate that needs review, never a crash.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from domain_kernel.documents import DocumentType

DOC_KINDS = ("notification", "circular", "press_release", "act_amendment")
"""The kinds of document a rule is extracted from: every document type but ``statute``."""


def is_extracted(doc_type: DocumentType | str) -> bool:
    """Whether the extraction steps read a document of this type. A statute (the CGST Act,
    the CGST Rules) is registered and its clauses embedded, so rules can cite it, but no rule
    or relation is extracted from it: it is the law the other documents act on. The ingest
    asks this before its knowledge extraction, and the rule extraction step that comes next
    asks it too."""
    return DocumentType(doc_type).value in DOC_KINDS


CHANGE_KINDS = ("none", "corrigendum", "withdrawal", "amendment", "extension")
FREQUENCIES = ("monthly", "quarterly", "half_yearly", "annual")
OPERATORS = ("eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "contains_any")

CANDIDATE_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RuleCandidateFields",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "summary",
        "doc_kind",
        "change_kind",
        "effective_from",
        "effective_to",
        "references",
        "applies_to",
        "obligation",
        "recurrence",
        "amounts",
        "citations",
        "confidence",
    ],
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 200},
        "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
        "doc_kind": {"type": "string", "enum": list(DOC_KINDS)},
        "change_kind": {"type": "string", "enum": list(CHANGE_KINDS)},
        "effective_from": {"type": ["string", "null"], "format": "date"},
        "effective_to": {"type": ["string", "null"], "format": "date"},
        "references": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "description": "Notifications and circulars the document names, as written.",
        },
        "applies_to": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["attribute", "operator", "value", "clause_ref"],
                "properties": {
                    "attribute": {"type": "string"},
                    "operator": {"type": "string", "enum": list(OPERATORS)},
                    "value": {},
                    "clause_ref": {"type": "string"},
                },
            },
        },
        "obligation": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["title", "steps", "evidence_type", "due_in_days", "clause_ref"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "steps": {"type": "array", "items": {"type": "string"}},
                "evidence_type": {"type": "string"},
                "due_in_days": {"type": ["integer", "null"], "minimum": 0},
                "clause_ref": {"type": "string"},
            },
        },
        "recurrence": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["frequency", "due_day", "due_month_offset", "clause_ref"],
            "properties": {
                "frequency": {"type": "string", "enum": list(FREQUENCIES)},
                "due_day": {"type": "integer", "minimum": 1, "maximum": 31},
                "due_month_offset": {"type": "integer", "minimum": 0, "maximum": 24},
                "clause_ref": {"type": "string"},
            },
        },
        "amounts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "value_inr", "clause_ref"],
                "properties": {
                    "label": {"type": "string", "minLength": 1},
                    "value_inr": {"type": "integer", "minimum": 0},
                    "clause_ref": {"type": "string"},
                },
            },
        },
        "citations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["clause_ref", "quote"],
                "properties": {
                    "clause_ref": {"type": "string"},
                    "quote": {"type": "string", "minLength": 1},
                },
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


class CandidateParseError(ValueError):
    """The model's answer is not a candidate: not JSON, or not the shape the schema asks for."""


@dataclass(frozen=True, slots=True)
class AppliesTo:
    attribute: str
    operator: str
    value: object
    clause_ref: str


@dataclass(frozen=True, slots=True)
class Obligation:
    title: str
    steps: tuple[str, ...]
    evidence_type: str
    due_in_days: int | None
    clause_ref: str


@dataclass(frozen=True, slots=True)
class RecurrenceFields:
    frequency: str
    due_day: int
    due_month_offset: int
    clause_ref: str


@dataclass(frozen=True, slots=True)
class Amount:
    label: str
    value_inr: int
    clause_ref: str


@dataclass(frozen=True, slots=True)
class Citation:
    clause_ref: str
    quote: str


@dataclass(frozen=True, slots=True)
class CandidateFields:
    title: str
    summary: str
    doc_kind: str
    change_kind: str
    effective_from: date | None
    effective_to: date | None
    references: tuple[str, ...]
    applies_to: tuple[AppliesTo, ...]
    obligation: Obligation | None
    recurrence: RecurrenceFields | None
    amounts: tuple[Amount, ...]
    citations: tuple[Citation, ...]
    confidence: float
    extra: Mapping[str, object] = field(default_factory=dict, hash=False)

    def cited_refs(self) -> frozenset[str]:
        """Every clause reference the candidate leans on."""
        refs = {c.clause_ref for c in self.citations}
        refs.update(p.clause_ref for p in self.applies_to)
        refs.update(a.clause_ref for a in self.amounts)
        if self.obligation is not None:
            refs.add(self.obligation.clause_ref)
        if self.recurrence is not None:
            refs.add(self.recurrence.clause_ref)
        return frozenset(refs)

    def to_mapping(self) -> dict[str, object]:
        """JSON-ready, the inverse of ``candidate_from_mapping``."""
        return {
            "title": self.title,
            "summary": self.summary,
            "doc_kind": self.doc_kind,
            "change_kind": self.change_kind,
            "effective_from": None
            if self.effective_from is None
            else self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "references": list(self.references),
            "applies_to": [
                {
                    "attribute": p.attribute,
                    "operator": p.operator,
                    "value": p.value,
                    "clause_ref": p.clause_ref,
                }
                for p in self.applies_to
            ],
            "obligation": None
            if self.obligation is None
            else {
                "title": self.obligation.title,
                "steps": list(self.obligation.steps),
                "evidence_type": self.obligation.evidence_type,
                "due_in_days": self.obligation.due_in_days,
                "clause_ref": self.obligation.clause_ref,
            },
            "recurrence": None
            if self.recurrence is None
            else {
                "frequency": self.recurrence.frequency,
                "due_day": self.recurrence.due_day,
                "due_month_offset": self.recurrence.due_month_offset,
                "clause_ref": self.recurrence.clause_ref,
            },
            "amounts": [
                {"label": a.label, "value_inr": a.value_inr, "clause_ref": a.clause_ref}
                for a in self.amounts
            ],
            "citations": [{"clause_ref": c.clause_ref, "quote": c.quote} for c in self.citations],
            "confidence": self.confidence,
        }


def parse_candidate(text: str) -> CandidateFields:
    """The model's text as candidate fields; any deviation from the schema is a parse error."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CandidateParseError(f"not JSON: {exc.msg} at {exc.pos}") from exc
    return candidate_from_mapping(data)


def candidate_from_mapping(data: object) -> CandidateFields:
    if not isinstance(data, Mapping):
        raise CandidateParseError("the candidate must be a JSON object")
    missing = [key for key in CANDIDATE_SCHEMA["required"] if key not in data]
    if missing:
        raise CandidateParseError(f"missing fields: {', '.join(missing)}")
    return CandidateFields(
        title=_text(data, "title"),
        summary=_text(data, "summary"),
        doc_kind=_choice(data, "doc_kind", DOC_KINDS),
        change_kind=_choice(data, "change_kind", CHANGE_KINDS),
        effective_from=_date(data, "effective_from"),
        effective_to=_date(data, "effective_to"),
        references=tuple(_texts(data, "references")),
        applies_to=tuple(
            _applies_to(item, index) for index, item in enumerate(_items(data, "applies_to"))
        ),
        obligation=_obligation(data.get("obligation")),
        recurrence=_recurrence(data.get("recurrence")),
        amounts=tuple(_amount(item, index) for index, item in enumerate(_items(data, "amounts"))),
        citations=tuple(
            _citation(item, index) for index, item in enumerate(_items(data, "citations"))
        ),
        confidence=_confidence(data.get("confidence")),
        extra={k: v for k, v in data.items() if k not in CANDIDATE_SCHEMA["properties"]},
    )


def conformance_problems(fields: CandidateFields) -> tuple[str, ...]:
    """What in ``fields`` the schema refuses although ``parse_candidate`` reads it: a title or a
    summary longer than the schema allows, no citation, a due month offset past the schema's
    maximum. The rule extraction asks again for an answer with any of these, and keeps none as
    a candidate, so every candidate it publishes fits ``CANDIDATE_SCHEMA``; the eval harness
    scores the parse alone."""
    properties = CANDIDATE_SCHEMA["properties"]
    problems: list[str] = []
    for name in ("title", "summary"):
        limit = int(properties[name]["maxLength"])
        if len(getattr(fields, name)) > limit:
            problems.append(f"{name} is longer than {limit} characters")
    if len(fields.citations) < int(properties["citations"]["minItems"]):
        problems.append("citations must cite at least one clause")
    offsets = properties["recurrence"]["properties"]["due_month_offset"]
    if fields.recurrence is not None and fields.recurrence.due_month_offset > int(
        offsets["maximum"]
    ):
        problems.append(f"recurrence.due_month_offset is more than {offsets['maximum']}")
    return tuple(problems)


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CandidateParseError(f"{key} must be non-empty text")
    return value.strip()


def _texts(data: Mapping[str, object], key: str) -> list[str]:
    items = _items(data, key)
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise CandidateParseError(f"{key} must be a list of non-empty text")
    return [str(item).strip() for item in items]


def _choice(data: Mapping[str, object], key: str, allowed: Sequence[str]) -> str:
    value = data.get(key)
    if value not in allowed:
        raise CandidateParseError(f"{key} must be one of {', '.join(allowed)}, got {value!r}")
    return str(value)


def _date(data: Mapping[str, object], key: str) -> date | None:
    value = data.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise CandidateParseError(f"{key} must be an ISO date or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CandidateParseError(f"{key} must be an ISO date, got {value!r}") from exc


def _items(data: Mapping[str, object], key: str) -> Sequence[object]:
    value = data.get(key)
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise CandidateParseError(f"{key} must be a list")
    return value


def _mapping(item: object, where: str) -> Mapping[str, object]:
    if not isinstance(item, Mapping):
        raise CandidateParseError(f"{where} must be an object")
    return item


def _ref(item: Mapping[str, object], where: str) -> str:
    value = item.get("clause_ref")
    if not isinstance(value, str) or not value.strip():
        raise CandidateParseError(f"{where} needs a clause_ref")
    return value.strip()


def _int(item: Mapping[str, object], key: str, where: str, *, optional: bool = False) -> int | None:
    value = item.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CandidateParseError(f"{where}.{key} must be a whole number")
    return value


def _applies_to(item: object, index: int) -> AppliesTo:
    where = f"applies_to[{index}]"
    mapping = _mapping(item, where)
    operator = mapping.get("operator")
    if operator not in OPERATORS:
        raise CandidateParseError(f"{where}.operator must be one of {', '.join(OPERATORS)}")
    attribute = mapping.get("attribute")
    if not isinstance(attribute, str) or not attribute:
        raise CandidateParseError(f"{where}.attribute must be text")
    value = mapping.get("value")
    if isinstance(value, list):
        value = tuple(value)
    return AppliesTo(attribute, str(operator), value, _ref(mapping, where))


def _obligation(item: object) -> Obligation | None:
    if item is None:
        return None
    mapping = _mapping(item, "obligation")
    steps = mapping.get("steps") or ()
    if (
        not isinstance(steps, Sequence)
        or isinstance(steps, str)
        or not all(isinstance(s, str) for s in steps)
    ):
        raise CandidateParseError("obligation.steps must be a list of text")
    evidence = mapping.get("evidence_type") or ""
    if not isinstance(evidence, str):
        raise CandidateParseError("obligation.evidence_type must be text")
    return Obligation(
        title=_text(mapping, "title"),
        steps=tuple(str(s).strip() for s in steps if str(s).strip()),
        evidence_type=evidence.strip(),
        due_in_days=_int(mapping, "due_in_days", "obligation", optional=True),
        clause_ref=_ref(mapping, "obligation"),
    )


def _recurrence(item: object) -> RecurrenceFields | None:
    if item is None:
        return None
    mapping = _mapping(item, "recurrence")
    due_day = _int(mapping, "due_day", "recurrence")
    offset = _int(mapping, "due_month_offset", "recurrence", optional=True) or 0
    if due_day is None or not 1 <= due_day <= 31:
        raise CandidateParseError("recurrence.due_day must be between 1 and 31")
    return RecurrenceFields(
        frequency=_choice(mapping, "frequency", FREQUENCIES),
        due_day=due_day,
        due_month_offset=offset,
        clause_ref=_ref(mapping, "recurrence"),
    )


def _amount(item: object, index: int) -> Amount:
    where = f"amounts[{index}]"
    mapping = _mapping(item, where)
    value = _int(mapping, "value_inr", where)
    assert value is not None
    return Amount(label=_text(mapping, "label"), value_inr=value, clause_ref=_ref(mapping, where))


def _citation(item: object, index: int) -> Citation:
    where = f"citations[{index}]"
    mapping = _mapping(item, where)
    return Citation(clause_ref=_ref(mapping, where), quote=_text(mapping, "quote"))


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CandidateParseError("confidence must be a number between 0 and 1")
    if not 0 <= value <= 1:
        raise CandidateParseError(f"confidence must be between 0 and 1, got {value}")
    return float(value)
