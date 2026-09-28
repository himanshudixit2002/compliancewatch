"""Relation candidates and how an approved one becomes a rule relation.

The pipeline proposes relations for a document before any rule version exists for it, so a
candidate points at its target the way the text does: an entity by type and canonical name
(aligned to an id once review has decided the name), and optionally the key of a rule the
model thinks is affected. An analyst approves it by naming the rule version it starts from,
and for a relation that must target a rule version (``RULE_VERSION_ONLY``) or that carries a
rule hint, the version it targets. The kernel's ``RuleRelation`` then checks the pairing.

Direction is always from the new, causing version to the affected one: ``extends_deadline``
from X to Y becomes the obligation service's deadline change for Y caused by X.
"""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleVersionId
from domain_kernel.knowledge import (
    RULE_VERSION_ONLY,
    EntityRef,
    EntityType,
    RelationKind,
    RuleRelation,
)
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.errors import TargetUnresolvedError, TargetVersionRequiredError

EDITABLE_FROM_STATUSES = frozenset(
    {RuleVersionStatus.DRAFT, RuleVersionStatus.IN_REVIEW, RuleVersionStatus.APPROVED}
)
"""A relation is approved together with the version it starts from, before publication."""


class CandidateStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"


class CandidateRejectReason(StrEnum):
    WRONG_KIND = "wrong_kind"
    WRONG_TARGET = "wrong_target"
    NOT_IN_TEXT = "not_in_text"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class CandidateIssue:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class RelationCandidate:
    candidate_id: UUID
    document_id: DocumentId
    relation: RelationKind
    target_type: EntityType
    target_name: str
    target_clause_id: ClauseId
    target_span_start: int
    target_span_end: int
    evidence_clause_id: ClauseId
    evidence_quote: str
    quote_score: float
    prompt_version: str
    confidence: float
    needs_review: bool
    model: str = ""
    method: str = "model"
    target_entity_id: CanonicalEntityId | None = None
    target_rule_key: str | None = None
    target_rule_id: UUID | None = None
    period_label: str | None = None
    new_due_on: date | None = None
    issues: tuple[CandidateIssue, ...] = field(default=())
    status: CandidateStatus = CandidateStatus.OPEN
    reject_reason: CandidateRejectReason | None = None
    decided_by: str = ""
    decided_at: datetime | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.relation is not RelationKind.EXTENDS_DEADLINE and (
            self.period_label is not None or self.new_due_on is not None
        ):
            raise InvariantViolationError(
                f"a period and a new due date belong to extends_deadline, not {self.relation}"
            )
        if not 8 <= len(self.evidence_quote) <= 400:
            raise InvariantViolationError("evidence_quote must be 8 to 400 characters")
        for name in ("quote_score", "confidence"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise InvariantViolationError(f"{name} must be between 0 and 1")

    def approve(self, *, decided_by: str, at: datetime, note: str = "") -> "RelationCandidate":
        self._require_open()
        return replace(
            self, status=CandidateStatus.APPROVED, decided_by=decided_by, decided_at=at, note=note
        )

    def reject(
        self, reason: CandidateRejectReason, *, decided_by: str, at: datetime, note: str = ""
    ) -> "RelationCandidate":
        self._require_open()
        return replace(
            self,
            status=CandidateStatus.REJECTED,
            reject_reason=reason,
            decided_by=decided_by,
            decided_at=at,
            note=note,
        )

    def _require_open(self) -> None:
        if self.status is not CandidateStatus.OPEN:
            raise InvariantViolationError(f"candidate {self.candidate_id} is {self.status.value}")


def to_rule_relation(
    candidate: RelationCandidate,
    from_version: RuleVersionId,
    target_version: RuleVersionId | None,
    target_entity: tuple[CanonicalEntityId, str] | None = None,
) -> RuleRelation:
    """The rule relation an approval writes. ``target_entity`` is the aligned entity with its
    canonical name, which the relation records instead of the text the candidate carries (an
    alias, or a number without its statute). The kernel checks pairing and self-relation."""
    needs_version = candidate.relation in RULE_VERSION_ONLY or candidate.target_rule_key
    if needs_version and target_version is None:
        raise TargetVersionRequiredError(
            f"{candidate.relation.value} with this candidate needs the target rule version"
        )
    if target_version is not None:
        target: EntityRef | RuleVersionId = target_version
    elif target_entity is None:
        raise TargetUnresolvedError(
            f"{candidate.target_type.value} {candidate.target_name!r} is not aligned yet"
        )
    else:
        target = EntityRef(candidate.target_type, target_entity[1], target_entity[0])
    return RuleRelation(
        from_rule_version_id=from_version,
        relation=candidate.relation,
        target=target,
        evidence_clause_id=candidate.evidence_clause_id,
    )


def find_supersedes_cycle(
    edges: Mapping[RuleVersionId, frozenset[RuleVersionId]],
    new_from: RuleVersionId,
    new_to: RuleVersionId,
) -> tuple[RuleVersionId, ...] | None:
    """The path that ``new_from supersedes new_to`` would close into a cycle, or ``None``.

    ``edges`` maps each version to the versions it supersedes. The new edge closes a cycle when
    ``new_to`` already reaches ``new_from``; the returned path starts at ``new_to``.
    """
    queue: deque[tuple[RuleVersionId, ...]] = deque([(new_to,)])
    seen = {new_to}
    while queue:
        path = queue.popleft()
        if path[-1] == new_from:
            return path
        for successor in edges.get(path[-1], frozenset()):
            if successor not in seen:
                seen.add(successor)
                queue.append((*path, successor))
    return None
