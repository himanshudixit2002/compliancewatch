"""What the relation prompt may answer, and reading the answer without trusting it.

The model is asked which of the things the grammar found in a document the document acts on,
and how: supersedes, amends, refers to, exempts, extends a deadline for, corrects, withdraws.
The JSON schema is built per call so that every choice is closed. The target is one of the
listed mention ids, the evidence is one of the document's clause refs, and the rule hint is one
of the known rule keys or null. A regulator document cannot steer the model into naming
something the grammar did not see, and a structurally wrong item never becomes a candidate.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from domain_kernel.knowledge import EntityType, RelationKind
from pipeline.domain.grammar import ExtractedMention

MAX_RELATIONS: Final = 30
MAX_TARGETS: Final = 200
PERIOD_PATTERN: Final = r"^[0-9]{4}-(0[1-9]|1[0-2])$|^[0-9]{4}-[0-9]{2} Q[1-4]$"
"""A month (``2026-03``) or a quarter of a financial year (``2025-26 Q2``)."""

_DOCUMENT_TYPES = frozenset({EntityType.NOTIFICATION, EntityType.CIRCULAR})
PROPOSAL_TARGET_TYPES: Final[Mapping[RelationKind, frozenset[EntityType]]] = {
    RelationKind.SUPERSEDES: _DOCUMENT_TYPES,
    RelationKind.WITHDRAWS: _DOCUMENT_TYPES,
    RelationKind.CORRECTS: _DOCUMENT_TYPES,
    RelationKind.EXTENDS_DEADLINE: _DOCUMENT_TYPES
    | {EntityType.FORM, EntityType.SECTION, EntityType.RULE},
    RelationKind.AMENDS: _DOCUMENT_TYPES | {EntityType.SECTION, EntityType.RULE, EntityType.FORM},
    RelationKind.EXEMPTS: frozenset(EntityType),
    RelationKind.REFERS_TO: frozenset(EntityType),
}
"""Which entity types a proposed relation may point at before any rule version exists. The
relations that end up targeting a rule version point at the document or form that stands for
it until an analyst names the version."""

_FIELDS = (
    "relation",
    "target_mention",
    "rule_key",
    "evidence_clause_ref",
    "evidence_quote",
    "period",
    "new_due_date",
    "confidence",
)
_PERIOD = re.compile(PERIOD_PATTERN)


class RelationParseError(ValueError):
    """The answer is not a JSON object with a ``relations`` list."""


@dataclass(frozen=True, slots=True)
class RawRelation:
    """One item of the model's answer, structurally valid; the validators judge its content."""

    relation: RelationKind
    target_mention: str
    rule_key: str | None
    evidence_clause_ref: str
    evidence_quote: str
    period: str | None
    new_due_date: date | None
    confidence: float


@dataclass(frozen=True, slots=True)
class Unusable:
    """An item that could not become a relation, kept verbatim with the reason."""

    raw: str
    reason: str


def render_mentions(
    mentions: Sequence[ExtractedMention],
) -> tuple[str, Mapping[str, ExtractedMention], bool]:
    """The targets the model may choose from, as ``M<n>`` lines, their mapping, and whether
    the list was cut at ``MAX_TARGETS``. A document's mentions of itself and mentions without
    a canonical name are not targets; the same entity named twice is listed once, at its first
    mention."""
    targets: dict[str, ExtractedMention] = {}
    seen: set[tuple[EntityType, str]] = set()
    truncated = False
    for mention in mentions:
        key = (mention.entity_type, mention.proposed_name)
        if mention.self_ref or not mention.proposed_name or key in seen:
            continue
        if len(targets) == MAX_TARGETS:
            truncated = True
            break
        seen.add(key)
        targets[f"M{len(targets) + 1}"] = mention
    lines = [
        f"{mention_id} [{m.clause_ref}] {m.entity_type.value} {m.proposed_name}: {m.text!r}"
        for mention_id, m in targets.items()
    ]
    return "\n".join(lines), targets, truncated


def relation_schema(
    mention_ids: Sequence[str], clause_refs: Sequence[str], rule_keys: Sequence[str]
) -> dict[str, Any]:
    """The JSON schema of one call: every choice is an enum over this document's values."""
    if not mention_ids or not clause_refs:
        raise ValueError("a relation schema needs at least one target and one clause")
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": list(_FIELDS),
        "properties": {
            "relation": {"type": "string", "enum": [kind.value for kind in RelationKind]},
            "target_mention": {"type": "string", "enum": list(mention_ids)},
            "rule_key": {"type": ["string", "null"], "enum": [*rule_keys, None]},
            "evidence_clause_ref": {"type": "string", "enum": list(clause_refs)},
            "evidence_quote": {"type": "string", "minLength": 8, "maxLength": 400},
            "period": {"type": ["string", "null"], "pattern": PERIOD_PATTERN},
            "new_due_date": {"type": ["string", "null"], "format": "date"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "RuleRelations",
        "type": "object",
        "additionalProperties": False,
        "required": ["relations"],
        "properties": {"relations": {"type": "array", "maxItems": MAX_RELATIONS, "items": item}},
    }


def parse_relations(
    text: str,
    *,
    mention_ids: Sequence[str],
    clause_refs: Sequence[str],
    rule_keys: Sequence[str],
) -> tuple[tuple[RawRelation, ...], tuple[Unusable, ...]]:
    """The structurally valid items of the answer and the ones that are not, with the reason.

    Raises ``RelationParseError`` when the answer as a whole is not ``{"relations": [...]}``.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RelationParseError(f"not JSON: {exc.msg}") from exc
    if not isinstance(data, dict) or set(data) != {"relations"}:
        raise RelationParseError("the answer must be an object with exactly 'relations'")
    items = data["relations"]
    if not isinstance(items, list):
        raise RelationParseError("'relations' must be a list")
    relations: list[RawRelation] = []
    unusable: list[Unusable] = []
    for index, item in enumerate(items):
        raw = json.dumps(item, ensure_ascii=False)[:2_000]
        if index >= MAX_RELATIONS:
            unusable.append(Unusable(raw, f"beyond the first {MAX_RELATIONS} items"))
            continue
        try:
            relations.append(_item(item, set(mention_ids), set(clause_refs), set(rule_keys)))
        except ValueError as exc:
            unusable.append(Unusable(raw, str(exc)))
    return tuple(relations), tuple(unusable)


def _item(
    item: object, mention_ids: set[str], clause_refs: set[str], rule_keys: set[str]
) -> RawRelation:
    if not isinstance(item, dict):
        raise ValueError("an item must be an object")
    if set(item) != set(_FIELDS):
        raise ValueError(f"an item must have exactly {', '.join(_FIELDS)}")
    kind = _choice(item["relation"], {k.value for k in RelationKind}, "relation")
    target = _choice(item["target_mention"], mention_ids, "target_mention")
    clause_ref = _choice(item["evidence_clause_ref"], clause_refs, "evidence_clause_ref")
    rule_key = item["rule_key"]
    if rule_key is not None:
        rule_key = _choice(rule_key, rule_keys, "rule_key")
    quote = item["evidence_quote"]
    if not isinstance(quote, str) or not 8 <= len(quote) <= 400:
        raise ValueError("evidence_quote must be text of 8 to 400 characters")
    period = item["period"]
    if period is not None and (not isinstance(period, str) or not _PERIOD.fullmatch(period)):
        raise ValueError(f"period {period!r} is not a month or a quarter")
    new_due_date = _date(item["new_due_date"])
    confidence = item["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        raise ValueError("confidence must be a number")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return RawRelation(
        relation=RelationKind(kind),
        target_mention=target,
        rule_key=rule_key,
        evidence_clause_ref=clause_ref,
        evidence_quote=quote,
        period=period,
        new_due_date=new_due_date,
        confidence=float(confidence),
    )


def _choice(value: object, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name} {value!r} is not one of the listed values")
    return value


def _date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("new_due_date must be a date as YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"new_due_date {value!r} is not a date") from exc
