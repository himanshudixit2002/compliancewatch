"""Decided rule candidates as draft cases of the extraction golden set.

``ExportDecidedCandidates(since)`` reads every candidate an analyst approved or rejected at or
after ``since``. An approved one becomes a case in the shape ``evals/golden/extraction`` holds
(``pipeline.label`` reads it; ``evals/golden/extraction/README.md`` describes it):

- ``label_status`` is ``draft``, ``labelled_by`` the user who decided the candidate (their id; a
  name is personal data), ``reviewed_by`` empty: nobody has reviewed it as a golden label, and
  nothing here marks one reviewed;
- ``source`` and ``document`` come from the stored document and its clauses, as registered;
- ``expected`` is the candidate shape (``CANDIDATE_SCHEMA``) read from the approved version's
  content: its title and summary, effective dates, conditions (an ``all_of`` of conditions, the
  only specification the shape holds), obligation template and recurrence, and the quotes the
  version cites from the document. The shape names a clause for each condition, the obligation
  and the recurrence; the candidate's own clause is kept where it named the same, else the
  version's first citation. ``doc_kind``, ``change_kind``, ``references`` and ``amounts`` are
  not in a version, so they come from the model's candidate, and ``notes`` says so;
- ``export`` records where the case came from: the candidate, its version, the prompt, the
  decision and the fields the analyst edited.

The golden shape has no place for a negative case (``expected: null`` is an unlabelled case, not
"no rule"), so a rejected candidate is listed in the export's summary with its reason, never
written as a case. A candidate whose approved content the shape cannot hold (conditions other
than an ``all_of`` of conditions, nothing cited in its document) is listed as skipped, with why.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from domain_kernel.ids import RuleVersionId
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.intake import RuleCandidate, RuleCandidateStatus
from rulebook.domain.publication import DecisionAction
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord

DOC_KINDS: Final = ("notification", "circular", "press_release", "act_amendment")
CHANGE_KINDS: Final = ("none", "corrigendum", "withdrawal", "amendment", "extension")
_SLUG: Final = re.compile(r"[^a-z0-9]+")
NOTES: Final = (
    "Exported as a draft from the rulebook's review: expected is the approved version's content "
    "in the candidate shape. doc_kind, change_kind, references and amounts are the model's, "
    "which a version does not hold: check them. A second analyst reviews the case before "
    "label_status moves on; nothing here is reviewed."
)


def slug(text: str) -> str:
    return _SLUG.sub("-", text.casefold()).strip("-")


@dataclass(frozen=True, slots=True)
class ExportedCase:
    """One approved candidate as a draft golden case: ``content`` is the case file's mapping."""

    case_id: str
    candidate_id: UUID
    rule_version_id: RuleVersionId
    decided_by: str
    decided_at: datetime
    content: Mapping[str, Any] = field(hash=False)


@dataclass(frozen=True, slots=True)
class ExportedRejection:
    """A rejected candidate, which the golden shape cannot hold as a case."""

    candidate_id: UUID
    document_id: str
    reason: str
    decided_by: str
    decided_at: datetime
    title: str


@dataclass(frozen=True, slots=True)
class SkippedCandidate:
    candidate_id: UUID
    why: str


@dataclass(frozen=True, slots=True)
class GoldenExport:
    since: datetime
    cases: tuple[ExportedCase, ...] = ()
    rejections: tuple[ExportedRejection, ...] = ()
    skipped: tuple[SkippedCandidate, ...] = ()

    def summary(self) -> dict[str, Any]:
        """What the export did, as the summary file keeps it."""
        return {
            "since": self.since.isoformat(),
            "label_status": "draft",
            "note": (
                "Draft cases for an analyst to review; nothing is marked reviewed. The golden "
                "shape has no negative case, so rejected candidates are listed here only."
            ),
            "cases": [
                {
                    "case_id": case.case_id,
                    "file": f"cases/{case.case_id}.yaml",
                    "candidate_id": str(case.candidate_id),
                    "rule_version_id": str(case.rule_version_id),
                    "decided_by": case.decided_by,
                    "decided_at": case.decided_at.isoformat(),
                }
                for case in self.cases
            ],
            "rejections": [
                {
                    "candidate_id": str(rejection.candidate_id),
                    "document_id": rejection.document_id,
                    "reason": rejection.reason,
                    "decided_by": rejection.decided_by,
                    "decided_at": rejection.decided_at.isoformat(),
                    "title": rejection.title,
                }
                for rejection in self.rejections
            ],
            "skipped": [
                {"candidate_id": str(skipped.candidate_id), "why": skipped.why}
                for skipped in self.skipped
            ],
        }


class _NotExportableError(Exception):
    """The approved content does not fit the golden shape; the message says why."""


class ExportDecidedCandidates:
    def __init__(self, units: KnowledgeUnitOfWorkFactory) -> None:
        self._units = units

    def run(self, since: datetime) -> GoldenExport:
        cases: list[ExportedCase] = []
        rejections: list[ExportedRejection] = []
        skipped: list[SkippedCandidate] = []
        with self._units() as uow:
            for candidate in uow.rule_candidates.decided_since(since):
                if candidate.status is RuleCandidateStatus.REJECTED:
                    rejections.append(_rejection(candidate))
                    continue
                if candidate.status is not RuleCandidateStatus.APPROVED:
                    continue
                try:
                    cases.append(_case(uow, candidate))
                except _NotExportableError as exc:
                    skipped.append(SkippedCandidate(candidate.candidate_id, str(exc)))
        return GoldenExport(since, tuple(cases), tuple(rejections), tuple(skipped))


def _rejection(candidate: RuleCandidate) -> ExportedRejection:
    assert candidate.decided_at is not None  # a rejected candidate is decided
    return ExportedRejection(
        candidate_id=candidate.candidate_id,
        document_id=str(candidate.document_id),
        reason="" if candidate.reject_reason is None else candidate.reject_reason.value,
        decided_by=str(candidate.decided_by),
        decided_at=candidate.decided_at,
        title=candidate.title,
    )


def _case(uow: KnowledgeUnitOfWork, candidate: RuleCandidate) -> ExportedCase:
    if candidate.rule_version_id is None or candidate.decided_at is None:
        raise _NotExportableError("an approved candidate names its version")
    version = uow.rule_versions.get(candidate.rule_version_id)
    document = uow.documents.get(candidate.document_id)
    if version is None or document is None:
        raise _NotExportableError("its version or its document is not stored")
    clauses = uow.documents.clauses(candidate.document_id)
    citations = [
        citation
        for citation in uow.citations.for_version(version.rule_version_id)
        if citation.document_id == candidate.document_id
    ]
    edited = sorted(
        {
            path
            for decision in uow.rule_versions.decisions(version.rule_version_id)
            if decision.action is DecisionAction.EDITED
            for path in _changed_paths(decision.note)
        }
    )
    fields = candidate.fields or {}
    expected = _expected(version, citations, fields, document, clauses)
    number = document.external_ref or document.title or str(document.document_id)
    case_id = f"{slug(number)}-{candidate.candidate_id.hex[-8:]}"
    source = candidate.payload.get("source")
    source_key = source.get("source_key") if isinstance(source, Mapping) else None
    content: dict[str, Any] = {
        "case_id": case_id,
        "label_status": "draft",
        "labelled_by": str(candidate.decided_by),
        "reviewed_by": "",
        "source": {
            "source_key": source_key,
            "number": document.external_ref,
            "title": document.title,
            "url": document.url,
            "published_at": None
            if document.published_at is None
            else document.published_at.isoformat(),
            "sha256": document.sha256,
            "fetched_at": document.fetched_at.isoformat(),
        },
        "document": {
            "doc_type": document.doc_type.value,
            "language": document.language,
            "title": document.title,
            "clauses": [
                {"ref": clause.clause_ref, "page": clause.page, "text": clause.text}
                for clause in clauses
            ],
        },
        "expected": expected,
        "export": {
            "candidate_id": str(candidate.candidate_id),
            "rule_version_id": str(version.rule_version_id),
            "rule_key": version.rule_key,
            "version": version.version,
            "prompt_version": candidate.prompt_version,
            "decided_at": candidate.decided_at.isoformat(),
            "edited": edited,
        },
        "notes": NOTES,
    }
    return ExportedCase(
        case_id=case_id,
        candidate_id=candidate.candidate_id,
        rule_version_id=version.rule_version_id,
        decided_by=str(candidate.decided_by),
        decided_at=candidate.decided_at,
        content=content,
    )


_MORE: Final = re.compile(r" and \d+ more$")
_CHANGED: Final = re.compile(
    r"^(?:drafted from rule candidate [0-9a-fA-F-]+, )?changed (?P<paths>[^:;]*)"
)
"""The head of an ``edited`` decision's note that names the paths, as the rulebook writes it:
``drafted from rule candidate <id>, changed title, citations`` or ``changed title``; the
analyst's own words follow a colon, and a citation count a semicolon."""


def _changed_paths(note: str) -> list[str]:
    """The dotted paths an ``edited`` decision's note names: ``drafted from rule candidate <id>,
    changed title, citations: <note>`` or ``changed title; cited 2 clauses: <note>``. Only the
    note's head is read: ``cited 1 clause: the rate changed`` names none, whatever the analyst
    wrote."""
    head = _CHANGED.match(note)
    if head is None:
        return []
    named = head["paths"]
    return [_MORE.sub("", path.strip()) for path in named.split(",") if path.strip()]


def _expected(
    version: RuleVersionRecord,
    citations: Sequence[CitationRecord],
    fields: Mapping[str, object],
    document: StoredDocument,
    clauses: Sequence[StoredClause],
) -> dict[str, Any]:
    quoted = [{"clause_ref": c.clause_ref, "quote": c.quote} for c in citations]
    if not quoted:
        raise _NotExportableError("its version cites nothing in its document, and a case cites one")
    first_ref = quoted[0]["clause_ref"]
    named = {clause.clause_ref for clause in clauses}

    def clause_of(found: object) -> str:
        ref = found.get("clause_ref") if isinstance(found, Mapping) else None
        return ref if isinstance(ref, str) and ref in named else first_ref

    proposed = _items(fields.get("applies_to"))
    applies_to = []
    for condition in _conditions(version.specification):
        same = next(
            (item for item in proposed if item.get("attribute") == condition["attribute"]), None
        )
        applies_to.append({**condition, "clause_ref": clause_of(same)})
    template = version.obligation_template
    obligation = {
        "title": template.get("title"),
        "steps": [step for step in _items(template.get("steps")) if isinstance(step, str)],
        "evidence_type": template.get("evidence_type") or "",
        "due_in_days": template.get("due_in_days"),
        "clause_ref": clause_of(fields.get("obligation")),
    }
    recurrence = None
    if version.recurrence is not None:
        recurrence = {
            "frequency": version.recurrence.get("frequency"),
            "due_day": version.recurrence.get("due_day"),
            "due_month_offset": version.recurrence.get("due_month_offset", 0),
            "clause_ref": clause_of(fields.get("recurrence")),
        }
    doc_kind = fields.get("doc_kind")
    change_kind = fields.get("change_kind")
    confidence = fields.get("confidence")
    return {
        "title": version.title,
        "summary": version.summary or _text(fields.get("summary")) or version.title,
        "doc_kind": doc_kind if doc_kind in DOC_KINDS else _kind_of(document),
        "change_kind": change_kind if change_kind in CHANGE_KINDS else "none",
        "effective_from": version.effective_from.isoformat(),
        "effective_to": None if version.effective_to is None else version.effective_to.isoformat(),
        "references": [ref for ref in _items(fields.get("references")) if isinstance(ref, str)],
        "applies_to": applies_to,
        "obligation": obligation,
        "recurrence": recurrence,
        "amounts": [item for item in _items(fields.get("amounts")) if isinstance(item, Mapping)],
        "citations": quoted,
        "confidence": confidence if isinstance(confidence, int | float) else 1.0,
    }


def _conditions(specification: Mapping[str, object]) -> list[dict[str, object]]:
    """The conditions of an ``all_of`` of conditions; anything else the golden shape cannot
    hold."""
    if set(specification) != {"all_of"}:
        raise _NotExportableError(
            f"its conditions are {sorted(specification)}, not an all_of of conditions, which is "
            "the only shape a golden case holds"
        )
    found: list[dict[str, object]] = []
    for item in _items(specification["all_of"]):
        if not isinstance(item, Mapping) or set(item) != {"attribute", "operator", "value"}:
            raise _NotExportableError(
                "a condition of its all_of is not an attribute, an operator and a value"
            )
        found.append(
            {"attribute": item["attribute"], "operator": item["operator"], "value": item["value"]}
        )
    return found


def _kind_of(document: StoredDocument) -> str:
    kind = document.doc_type.value
    return kind if kind in DOC_KINDS else "notification"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _items(value: object) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []
