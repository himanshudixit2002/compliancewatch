"""Rule candidates: what the pipeline's extraction proposed for a document, queued for an
analyst who drafts a rule version from it, and the draft a candidate maps to.

The pipeline publishes rule.candidate.created for every extraction it stores: 1.0.0 carried the
scores, 1.1.0 added the candidate itself in the extraction schema's shape, how the extraction
ended, the validators' issues, a suggested rule key and the cited clauses. The intake reads an
event into a ``CandidateIntake`` (``from_payload``; a payload the contract refuses is
``CandidatePayloadInvalidError``), keeps it once per candidate id as a ``RuleCandidate`` and opens
a review task of kind ``candidate`` for it, queued under the candidate's regulator in lower case
(the pipeline's source registry says ``CBIC``, the rulebook's rules ``cbic``) at a priority:

- 100: the candidate looks high impact (``suggest_high_impact``): it extends a deadline or
  withdraws something, applies to every taxpayer, or names amounts;
- 80: there is no candidate to draft from (the extraction was unparseable, or a 1.0.0 event
  carried none), so an analyst drafts the rule by hand;
- 50: the extraction asked for review, or the validators found an issue;
- 10: anything else.

Nothing is drafted by itself: no transition discards a draft, so a wrong automatic draft would
linger. An analyst drafts a version from the candidate: ``draft_content`` maps the candidate into
the kernel's forms and names what does not map, and ``drafted_content`` applies the analyst's
edits, checks the result as the seed calendar is checked (``drafting.content_problems``) and
names what the analyst changed. A candidate is ``open`` until drafted, ``drafted`` once a version
is made from it, then ``approved`` when that version's review round completes, or ``rejected``
with a reason, before or after drafting.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final, NoReturn
from uuid import UUID

from domain_kernel._validation import require_aware, require_date, require_instance
from domain_kernel.errors import DomainError, InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId, RuleVersionId, UserId
from domain_kernel.ontology import Ontology
from domain_kernel.predicates import specification_from_mapping, specification_to_mapping
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate
from rulebook.domain.drafting import (
    EDITABLE_FIELDS,
    MAX_SUMMARY,
    MAX_TITLE,
    DraftEdit,
    changed_paths,
    checked_values,
    content_problems,
)
from rulebook.domain.errors import (
    CandidateAlreadyDraftedError,
    CandidateNotDraftedError,
    CandidatePayloadInvalidError,
    DraftIncompleteError,
)

HIGH_IMPACT_PRIORITY: Final = 100
HAND_DRAFT_PRIORITY: Final = 80
REVIEW_PRIORITY: Final = 50
ROUTINE_PRIORITY: Final = 10
MAX_REGULATOR: Final = 40
MAX_MODEL: Final = 120
MAX_PROMPT_VERSION: Final = 60
MAX_RULE_KEY: Final = 80
RULE_KEY: Final = re.compile(r"[a-z][a-z0-9_]*")
"""A rule key, as the seed calendar names rules (``gstr3b_monthly``)."""
SUGGESTED_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,62}")
"""The pattern rule.candidate.created gives a suggested rule key."""
EXTRACTED_TYPES: Final = frozenset({"notification", "circular", "act_amendment"})
"""The document types rules are extracted from."""
HIGH_IMPACT_CHANGES: Final = frozenset({"withdrawal", "extension"})
REQUIRED_CONTENT: Final = ("title", "specification", "obligation_template", "effective_from")
"""What a draft cannot do without; the rest defaults (``CONTENT_DEFAULTS``)."""
CONTENT_DEFAULTS: Final[Mapping[str, object]] = {
    "summary": "",
    "recurrence": None,
    "effective_to": None,
    "todo": (),
}


class CandidateOutcome(StrEnum):
    """How the extraction ended: ``extracted``, the model's answer read as a candidate (the
    validators may still send it to review); ``unparseable``, no candidate, twice."""

    EXTRACTED = "extracted"
    UNPARSEABLE = "unparseable"


class RuleCandidateStatus(StrEnum):
    OPEN = "open"
    DRAFTED = "drafted"
    APPROVED = "approved"
    REJECTED = "rejected"


class RuleRejectReason(StrEnum):
    """Why an analyst rejects a candidate: the document states no rule, the model read it
    wrongly, another candidate or rule holds it already, the product does not cover it, or
    there was no candidate to draft from."""

    NOT_A_RULE = "not_a_rule"
    WRONG_EXTRACTION = "wrong_extraction"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"
    UNPARSEABLE = "unparseable"


@dataclass(frozen=True, slots=True)
class ExtractionIssue:
    """What a validator of the extraction found wrong, as the event names it."""

    code: str
    detail: str
    clause_ref: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {"code": self.code, "detail": self.detail, "clause_ref": self.clause_ref}


@dataclass(frozen=True, slots=True)
class CandidateIntake:
    """A rule.candidate.created payload as the intake reads it. ``fields`` is the candidate in
    the extraction schema's shape, None when there is none; ``regulator`` is in lower case."""

    candidate_id: UUID
    document_id: DocumentId
    regulator: str
    model: str
    prompt_version: str
    confidence: float
    citation_count: int
    needs_review: bool
    outcome: CandidateOutcome = CandidateOutcome.EXTRACTED
    fields: Mapping[str, object] | None = field(default=None, hash=False)
    issues: tuple[ExtractionIssue, ...] = ()
    suggested_rule_key: str | None = None
    clause_ids: tuple[ClauseId, ...] = ()
    doc_type: str | None = None
    source_id: UUID | None = None
    source_key: str | None = None
    ontology_version: str | None = None

    @classmethod
    def from_payload(cls, payload: object) -> "CandidateIntake":
        """The intake of a rule.candidate.created payload (1.0.0 or 1.1.x). Fields the contract
        does not name are ignored; one it names with a value it refuses, or a missing required
        one, is ``CandidatePayloadInvalidError``. A missing ``outcome`` is ``extracted``."""
        if not isinstance(payload, Mapping):
            raise CandidatePayloadInvalidError("the payload is not an object")
        read = _Reader(payload)
        outcome = read.choice("outcome", CandidateOutcome, default=CandidateOutcome.EXTRACTED)
        candidate = payload.get("candidate")
        if candidate is not None and not isinstance(candidate, Mapping):
            read.refuse("candidate", "must be an object or null")
        if outcome is CandidateOutcome.UNPARSEABLE and candidate is not None:
            read.refuse("candidate", "an unparseable extraction has no candidate")
        return cls(
            candidate_id=read.uuid("candidate_id"),
            document_id=DocumentId(read.uuid("document_id")),
            regulator=read.text("regulator", MAX_REGULATOR).lower(),
            model=read.text("model", MAX_MODEL),
            prompt_version=read.text("prompt_version", MAX_PROMPT_VERSION),
            confidence=read.fraction("confidence"),
            citation_count=read.count("citation_count"),
            needs_review=read.flag("needs_review"),
            outcome=outcome,
            fields=None if candidate is None else dict(candidate),
            issues=read.issues("issues"),
            suggested_rule_key=read.optional_key("suggested_rule_key"),
            clause_ids=tuple(ClauseId(clause) for clause in read.uuids("clause_ids")),
            doc_type=read.optional_member("doc_type", EXTRACTED_TYPES),
            source_id=read.optional_uuid("source_id"),
            source_key=read.optional_text("source_key"),
            ontology_version=read.optional_text("ontology_version"),
        )

    @property
    def drafts_by_hand(self) -> bool:
        """Whether there is no candidate to draft from."""
        return self.fields is None

    def priority(self) -> int:
        """Where the candidate's task stands in its regulator's queue: high impact first, then
        the ones an analyst drafts by hand, then the ones that asked for review."""
        if suggest_high_impact(self.fields)[0]:
            return HIGH_IMPACT_PRIORITY
        if self.outcome is CandidateOutcome.UNPARSEABLE or self.drafts_by_hand:
            return HAND_DRAFT_PRIORITY
        if self.needs_review or self.issues:
            return REVIEW_PRIORITY
        return ROUTINE_PRIORITY

    def stored_payload(self) -> dict[str, object]:
        """What ``rule_candidate.payload`` keeps of the event besides its columns, JSON-ready."""
        return {
            "candidate": None if self.fields is None else dict(self.fields),
            "issues": [issue.to_mapping() for issue in self.issues],
            "suggested_rule_key": self.suggested_rule_key,
            "clause_ids": [str(clause) for clause in self.clause_ids],
            "doc_type": self.doc_type,
            "source": {
                "source_id": None if self.source_id is None else str(self.source_id),
                "source_key": self.source_key,
            },
            "ontology_version": self.ontology_version,
        }


def suggest_high_impact(fields: Mapping[str, object] | None) -> tuple[bool, tuple[str, ...]]:
    """Whether a candidate looks high impact, and why: it extends a deadline or withdraws
    something, its ``applies_to`` is empty (every taxpayer), or it names amounts. A suggestion:
    the version starts high impact, and a reviewer may raise a version but never lower it."""
    if fields is None:
        return False, ()
    reasons: list[str] = []
    change = fields.get("change_kind")
    if isinstance(change, str) and change in HIGH_IMPACT_CHANGES:
        reasons.append(f"change_kind is {change}")
    applies_to = fields.get("applies_to")
    if _items(applies_to) == []:
        reasons.append("applies_to is empty, so it applies to every taxpayer")
    amounts = fields.get("amounts")
    if _items(amounts):
        reasons.append("it names amounts")
    return bool(reasons), tuple(reasons)


@dataclass(frozen=True, slots=True)
class RuleCandidate:
    """A candidate as the rulebook keeps it: the event's scores in columns, the rest of it in
    ``payload`` (``CandidateIntake.stored_payload``), and where its review got to."""

    candidate_id: UUID
    document_id: DocumentId
    regulator: str
    model: str
    prompt_version: str
    confidence: float
    citation_count: int
    needs_review: bool
    outcome: CandidateOutcome
    payload: Mapping[str, object] = field(hash=False)
    event_id: UUID
    created_at: datetime
    suggested_rule_key: str | None = None
    high_impact_suggested: bool = False
    status: RuleCandidateStatus = RuleCandidateStatus.OPEN
    reject_reason: RuleRejectReason | None = None
    rule_version_id: RuleVersionId | None = None
    decided_by: UserId | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        require_instance(self.candidate_id, UUID, "candidate_id")
        require_instance(self.document_id, DocumentId, "document_id")
        if self.regulator != self.regulator.lower() or not self.regulator.strip():
            raise InvariantViolationError("a candidate's regulator is lower case and not blank")
        if not 0.0 <= self.confidence <= 1.0:
            raise InvariantViolationError("confidence must be between 0 and 1")
        require_instance(self.outcome, CandidateOutcome, "outcome")
        require_instance(self.status, RuleCandidateStatus, "status")
        require_aware(self.created_at, "created_at")
        decided = self.decided_by is not None and self.decided_at is not None
        undecided = self.decided_by is None and self.decided_at is None
        drafted = self.rule_version_id is not None
        consistent = {
            RuleCandidateStatus.OPEN: undecided and not drafted and self.reject_reason is None,
            RuleCandidateStatus.DRAFTED: undecided and drafted and self.reject_reason is None,
            RuleCandidateStatus.APPROVED: decided and drafted and self.reject_reason is None,
            RuleCandidateStatus.REJECTED: decided and self.reject_reason is not None,
        }[self.status]
        if not consistent:
            raise InvariantViolationError(
                f"rule candidate {self.candidate_id}: a {self.status.value} candidate's version, "
                "reason and decision do not agree"
            )
        if self.decided_at is not None:
            require_aware(self.decided_at, "decided_at")

    @classmethod
    def received(
        cls,
        intake: CandidateIntake,
        *,
        event_id: UUID,
        at: datetime,
        suggested_rule_key: str | None,
    ) -> "RuleCandidate":
        """The candidate the intake keeps of ``intake``: open, with the suggestion the intake
        chose and whether it looks high impact."""
        return cls(
            candidate_id=intake.candidate_id,
            document_id=intake.document_id,
            regulator=intake.regulator,
            model=intake.model,
            prompt_version=intake.prompt_version,
            confidence=intake.confidence,
            citation_count=intake.citation_count,
            needs_review=intake.needs_review,
            outcome=intake.outcome,
            payload=intake.stored_payload(),
            event_id=event_id,
            created_at=at,
            suggested_rule_key=suggested_rule_key,
            high_impact_suggested=suggest_high_impact(intake.fields)[0],
        )

    @property
    def fields(self) -> Mapping[str, object] | None:
        """The candidate in the extraction schema's shape; None when there is none."""
        found = self.payload.get("candidate")
        return found if isinstance(found, Mapping) else None

    @property
    def issues(self) -> tuple[ExtractionIssue, ...]:
        return tuple(
            ExtractionIssue(
                str(issue.get("code", "")),
                str(issue.get("detail", "")),
                None if issue.get("clause_ref") is None else str(issue.get("clause_ref")),
            )
            for issue in _items(self.payload.get("issues")) or []
            if isinstance(issue, Mapping)
        )

    @property
    def title(self) -> str:
        """The candidate's title, or empty when there is no candidate."""
        fields = self.fields
        title = None if fields is None else fields.get("title")
        return title if isinstance(title, str) else ""

    @property
    def high_impact_reasons(self) -> tuple[str, ...]:
        return suggest_high_impact(self.fields)[1]

    def drafted(self, rule_version_id: RuleVersionId) -> "RuleCandidate":
        """The candidate once a version is drafted from it; a candidate is drafted once."""
        if self.status is not RuleCandidateStatus.OPEN:
            raise CandidateAlreadyDraftedError(
                f"rule candidate {self.candidate_id} is {self.status.value}"
                + ("" if self.rule_version_id is None else f" (version {self.rule_version_id})")
            )
        return replace(self, status=RuleCandidateStatus.DRAFTED, rule_version_id=rule_version_id)

    def approved(self, *, by: UserId, at: datetime) -> "RuleCandidate":
        """The candidate once the review round of its version completed."""
        if self.status is not RuleCandidateStatus.DRAFTED:
            raise CandidateNotDraftedError(
                f"rule candidate {self.candidate_id} is {self.status.value}: only a drafted "
                "candidate is approved"
            )
        return replace(self, status=RuleCandidateStatus.APPROVED, decided_by=by, decided_at=at)

    def rejected(self, reason: RuleRejectReason, *, by: UserId, at: datetime) -> "RuleCandidate":
        """The candidate rejected, before or after drafting; a draft made from it stays."""
        if self.status not in (RuleCandidateStatus.OPEN, RuleCandidateStatus.DRAFTED):
            raise InvariantViolationError(
                f"rule candidate {self.candidate_id} was {self.status.value} already"
            )
        require_instance(reason, RuleRejectReason, "reason")
        return replace(
            self,
            status=RuleCandidateStatus.REJECTED,
            reject_reason=reason,
            decided_by=by,
            decided_at=at,
        )


@dataclass(frozen=True, slots=True)
class CandidateSummary:
    """What the review queue shows of a candidate task's candidate."""

    candidate_id: UUID
    document_id: DocumentId
    status: RuleCandidateStatus
    outcome: CandidateOutcome
    confidence: float
    needs_review: bool
    issue_count: int
    suggested_rule_key: str | None
    high_impact_suggested: bool
    title: str

    @classmethod
    def of(cls, candidate: RuleCandidate) -> "CandidateSummary":
        return cls(
            candidate_id=candidate.candidate_id,
            document_id=candidate.document_id,
            status=candidate.status,
            outcome=candidate.outcome,
            confidence=candidate.confidence,
            needs_review=candidate.needs_review,
            issue_count=len(candidate.issues),
            suggested_rule_key=candidate.suggested_rule_key,
            high_impact_suggested=candidate.high_impact_suggested,
            title=candidate.title,
        )


@dataclass(frozen=True, slots=True)
class ProposedCitation:
    """A quote the candidate cites, by the ref of its clause in the candidate's document."""

    clause_ref: str
    quote: str


@dataclass(frozen=True, slots=True)
class DraftContent:
    """What a candidate proposes for a draft: ``values`` holds, in the kernel's stored forms,
    each content field that maps (title, summary, specification, obligation_template,
    recurrence, effective_from, effective_to); ``problems`` says why each other one does not;
    ``citations`` are the quotes it cites and ``citation_problems`` the ones that do not read."""

    values: Mapping[str, object] = field(default_factory=dict, hash=False)
    problems: Mapping[str, tuple[str, ...]] = field(default_factory=dict, hash=False)
    citations: tuple[ProposedCitation, ...] = ()
    citation_problems: tuple[str, ...] = ()

    @property
    def problem_list(self) -> tuple[str, ...]:
        """``field: why`` for every field that does not map, in field order."""
        order = {name: index for index, name in enumerate(EDITABLE_FIELDS)}
        return tuple(
            f"{name}: {problem}"
            for name in sorted(self.problems, key=lambda name: order.get(name, len(order)))
            for problem in self.problems[name]
        )


def draft_content(fields: Mapping[str, object] | None) -> DraftContent:
    """The draft ``fields`` (a candidate in the extraction schema's shape) proposes. Each
    ``applies_to`` item is a predicate of an ``all_of`` (an empty list applies to everyone); a
    predicate the kernel refuses leaves the specification out, so a refused condition never
    widens who the rule applies to. The obligation is the template (its clause ref is not kept),
    the recurrence and the dates are read as the kernel reads them. Without a candidate,
    nothing is proposed and the analyst gives everything."""
    if fields is None:
        return DraftContent()
    values: dict[str, object] = {}
    problems: dict[str, list[str]] = {}

    def keep(name: str, value: object) -> None:
        values[name] = value

    def refuse(name: str, problem: str) -> None:
        problems.setdefault(name, []).append(problem)

    title = fields.get("title")
    if not isinstance(title, str) or not title.strip():
        refuse("title", "the candidate gives none")
    elif len(title.strip()) > MAX_TITLE:
        refuse("title", f"at most {MAX_TITLE} characters")
    else:
        keep("title", title.strip())
    summary = fields.get("summary")
    if isinstance(summary, str) and len(summary.strip()) <= MAX_SUMMARY:
        keep("summary", summary.strip())
    elif summary is not None:
        refuse("summary", f"a text of at most {MAX_SUMMARY} characters")
    specification, refused = _specification_of(fields.get("applies_to"))
    if refused:
        for problem in refused:
            refuse("specification", problem)
    else:
        keep("specification", specification)
    _read_into(values, problems, "obligation_template", _template_of, fields.get("obligation"))
    _read_into(values, problems, "recurrence", _recurrence_of, fields.get("recurrence"))
    for name in ("effective_from", "effective_to"):
        _read_into(values, problems, name, _date_of, fields.get(name))
    if values.get("effective_from", "") is None:
        del values["effective_from"]
        refuse("effective_from", "the candidate gives none")
    citations, citation_problems = _citations_of(fields.get("citations"))
    return DraftContent(
        values=values,
        problems={name: tuple(found) for name, found in problems.items()},
        citations=citations,
        citation_problems=citation_problems,
    )


@dataclass(frozen=True, slots=True)
class DraftedContent:
    """The content a draft is stored with, and the dotted paths the analyst changed from what
    the candidate proposed (``changed``; empty when the candidate was taken as it was)."""

    title: str
    summary: str
    specification: Mapping[str, object] = field(hash=False)
    obligation_template: Mapping[str, object] = field(hash=False)
    recurrence: Mapping[str, object] | None = field(hash=False)
    effective_from: date
    effective_to: date | None
    todo: tuple[str, ...]
    changed: tuple[str, ...] = ()


def drafted_content(
    proposed: DraftContent, edit: DraftEdit | None, ontology: Ontology
) -> DraftedContent:
    """The proposal with the analyst's edits applied, checked as ``drafting.edited_record``
    checks an edit: each edited value is read into the kernel's form, a field the candidate could
    not give stays a problem until the analyst gives it, and the content must pass the seed
    calendar's checks. Every problem is reported at once (``DraftIncompleteError``)."""
    edits: dict[str, Any] = {}
    problems: list[str] = []
    if edit is not None:
        edits, problems = checked_values(edit)
    problems.extend(
        problem for problem in proposed.problem_list if problem.split(":", 1)[0] not in edits
    )
    values: dict[str, object] = {**CONTENT_DEFAULTS, **proposed.values, **edits}
    problems.extend(
        f"{name}: the candidate gives none; send it"
        for name in REQUIRED_CONTENT
        if name not in values and name not in proposed.problems
    )
    if problems:
        raise DraftIncompleteError(problems)
    content = DraftedContent(
        title=str(values["title"]),
        summary=str(values["summary"]),
        specification=_mapping(values["specification"]),
        obligation_template=_mapping(values["obligation_template"]),
        recurrence=None if values["recurrence"] is None else _mapping(values["recurrence"]),
        effective_from=require_date(values["effective_from"], "effective_from"),
        effective_to=None
        if values["effective_to"] is None
        else require_date(values["effective_to"], "effective_to"),
        todo=tuple(str(question) for question in _items(values["todo"]) or []),
    )
    problems = content_problems(content, ontology)
    if problems:
        raise DraftIncompleteError(problems)
    before = {**CONTENT_DEFAULTS, **proposed.values}
    after = {name: values[name] for name in EDITABLE_FIELDS}
    return replace(content, changed=changed_paths(before, after))


def _read_into(
    values: dict[str, object],
    problems: dict[str, list[str]],
    name: str,
    read: Any,
    raw: object,
) -> None:
    try:
        values[name] = read(raw)
    except (DomainError, TypeError, ValueError, KeyError) as exc:
        problems.setdefault(name, []).append(str(exc))


def _specification_of(applies_to: object) -> tuple[Mapping[str, object], list[str]]:
    conditions = _items(applies_to)
    if conditions is None:
        return {}, ["applies_to must be a list of conditions"]
    items: list[object] = []
    problems: list[str] = []
    for index, item in enumerate(conditions):
        where = f"applies_to[{index}]"
        if not isinstance(item, Mapping):
            problems.append(f"{where} is not a condition")
            continue
        named = f"{where} ({item.get('attribute')} {item.get('operator')})"
        try:
            predicate = specification_from_mapping(
                {
                    "attribute": item.get("attribute"),
                    "operator": item.get("operator"),
                    "value": item.get("value"),
                }
            )
        except (DomainError, TypeError, ValueError) as exc:
            problems.append(f"{named}: {exc}")
            continue
        items.append(specification_to_mapping(predicate))
    return {"all_of": items}, problems


def _template_of(obligation: object) -> Mapping[str, object]:
    if obligation is None:
        raise InvariantViolationError("the candidate names no obligation")
    if not isinstance(obligation, Mapping):
        raise InvariantViolationError("the obligation must be an object")
    steps = obligation.get("steps")
    return ObligationTemplate.from_mapping(
        {
            "title": obligation.get("title"),
            "steps": [] if steps is None else steps,
            "due_in_days": obligation.get("due_in_days"),
            "evidence_type": obligation.get("evidence_type") or "",
        }
    ).to_mapping()


def _recurrence_of(recurrence: object) -> Mapping[str, object] | None:
    if recurrence is None:
        return None
    if not isinstance(recurrence, Mapping):
        raise InvariantViolationError("the recurrence must be an object or null")
    return Recurrence.from_mapping(
        {
            "frequency": recurrence.get("frequency"),
            "due_day": recurrence.get("due_day"),
            "due_month_offset": recurrence.get("due_month_offset", 0),
        }
    ).to_mapping()


def _date_of(raw: object) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return date.fromisoformat(raw)
    return require_date(raw, "date")


def _citations_of(raw: object) -> tuple[tuple[ProposedCitation, ...], tuple[str, ...]]:
    quotes = _items(raw)
    if quotes is None:
        return (), ("citations must be a list",)
    citations: list[ProposedCitation] = []
    problems: list[str] = []
    for index, item in enumerate(quotes):
        ref = item.get("clause_ref") if isinstance(item, Mapping) else None
        quote = item.get("quote") if isinstance(item, Mapping) else None
        if not isinstance(ref, str) or not ref.strip() or not isinstance(quote, str):
            problems.append(f"citations[{index}] names no clause ref and quote")
        elif not quote.strip():
            problems.append(f"citations[{index}] quotes nothing")
        else:
            citations.append(ProposedCitation(ref.strip(), quote))
    return tuple(citations), tuple(problems)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InvariantViolationError(f"expected an object, got {type(value).__name__}")
    return value


def _items(value: object) -> list[object] | None:
    """The items of a JSON list (a list or a tuple), or None for anything else."""
    return list(value) if isinstance(value, list | tuple) else None


class _Reader:
    """Reads the fields of a payload, each failure a ``CandidatePayloadInvalidError`` that names
    the field."""

    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload

    @staticmethod
    def refuse(name: str, why: str) -> NoReturn:
        raise CandidatePayloadInvalidError(f"rule.candidate.created payload: {name} {why}")

    def _required(self, name: str) -> object:
        raw = self._payload.get(name)
        if raw is None:
            self.refuse(name, "is missing")
        return raw

    def uuid(self, name: str) -> UUID:
        raw = self._required(name)
        found = _uuid_of(raw)
        if found is None:
            self.refuse(name, f"is not a uuid: {raw!r}")
        return found

    def optional_uuid(self, name: str) -> UUID | None:
        return None if self._payload.get(name) is None else self.uuid(name)

    def uuids(self, name: str) -> tuple[UUID, ...]:
        raw = self._payload.get(name)
        if raw is None:
            return ()
        if not isinstance(raw, list | tuple):
            self.refuse(name, "must be a list")
        found: list[UUID] = []
        for item in raw:
            parsed = _uuid_of(item)
            if parsed is None:
                self.refuse(name, f"holds {item!r}, not a uuid")
            found.append(parsed)
        if len(set(found)) != len(found):
            self.refuse(name, "lists a clause twice")
        return tuple(found)

    def text(self, name: str, longest: int) -> str:
        raw = self._required(name)
        if not isinstance(raw, str) or not raw.strip():
            self.refuse(name, "must be a non-blank text")
        if len(raw.strip()) > longest:
            self.refuse(name, f"is longer than {longest} characters")
        return raw.strip()

    def optional_text(self, name: str) -> str | None:
        raw = self._payload.get(name)
        if raw is None:
            return None
        if not isinstance(raw, str) or not raw.strip():
            self.refuse(name, "must be a non-blank text or null")
        return raw.strip()

    def optional_key(self, name: str) -> str | None:
        key = self.optional_text(name)
        if key is not None and not SUGGESTED_KEY.fullmatch(key):
            self.refuse(name, f"is not a rule key: {key!r}")
        return key

    def optional_member(self, name: str, members: frozenset[str]) -> str | None:
        found = self.optional_text(name)
        if found is not None and found not in members:
            self.refuse(name, f"must be one of {sorted(members)}, got {found!r}")
        return found

    def choice[E: StrEnum](self, name: str, kind: type[E], *, default: E) -> E:
        raw = self._payload.get(name)
        if raw is None:
            return default
        for member in kind:
            if member.value == raw:
                return member
        self.refuse(name, f"must be one of {[member.value for member in kind]}, got {raw!r}")

    def fraction(self, name: str) -> float:
        raw = self._required(name)
        if (
            isinstance(raw, bool)
            or not isinstance(raw, int | float)
            or not math.isfinite(raw)
            or not 0 <= raw <= 1
        ):
            self.refuse(name, f"must be a number from 0 to 1, got {raw!r}")
        return float(raw)

    def count(self, name: str) -> int:
        raw = self._required(name)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            self.refuse(name, f"must be a whole number of at least 0, got {raw!r}")
        return raw

    def flag(self, name: str) -> bool:
        raw = self._payload.get(name)
        if not isinstance(raw, bool):
            self.refuse(name, f"must be true or false, got {raw!r}")
        return raw

    def issues(self, name: str) -> tuple[ExtractionIssue, ...]:
        raw = self._payload.get(name)
        if raw is None:
            return ()
        if not isinstance(raw, list | tuple):
            self.refuse(name, "must be a list")
        found: list[ExtractionIssue] = []
        for index, item in enumerate(raw):
            where = f"{name}[{index}]"
            if not isinstance(item, Mapping):
                self.refuse(where, "is not an object")
            code, detail, ref = item.get("code"), item.get("detail"), item.get("clause_ref")
            if not isinstance(code, str) or not code.strip() or not isinstance(detail, str):
                self.refuse(where, "needs a code and a detail")
            if ref is not None and not isinstance(ref, str):
                self.refuse(f"{where}.clause_ref", "must be a text or null")
            found.append(ExtractionIssue(code, detail, ref))
        return tuple(found)


def _uuid_of(raw: object) -> UUID | None:
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None
