"""The entity review queue: mentions alignment could not resolve, and what an analyst decides.

Items are reviewed per group, one (entity type, proposed name) at a time, because the same
unresolved name tends to appear in many clauses: one decision closes them all. A decision
creates the entity, adds the name as an alias of an existing one, or rejects the group.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId
from domain_kernel.knowledge import EntityType
from rulebook.domain.alignment import ReviewReason


class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class Resolution(StrEnum):
    CREATED = "created"
    ALIASED = "aliased"
    MATCHED = "matched"


class EntityRejectReason(StrEnum):
    NOT_AN_ENTITY = "not_an_entity"
    WRONG_TYPE = "wrong_type"
    TEXT_ARTIFACT = "text_artifact"
    OUT_OF_SCOPE = "out_of_scope"


class MentionDecision(StrEnum):
    CREATE_ENTITY = "create_entity"
    ADD_ALIAS = "add_alias"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class EntityReviewItem:
    """One unresolved mention: where it is, what the grammar proposed, and the decision."""

    review_id: UUID
    document_id: DocumentId
    clause_id: ClauseId
    entity_type: EntityType
    mention_text: str
    span_start: int
    span_end: int
    proposed_name: str
    reason: ReviewReason
    extractor: str
    status: ReviewStatus = ReviewStatus.OPEN
    resolution: Resolution | None = None
    resolved_entity_id: CanonicalEntityId | None = None
    reject_reason: EntityRejectReason | None = None
    decided_by: str = ""
    decided_at: datetime | None = None
    note: str = ""

    def resolve(
        self,
        entity_id: CanonicalEntityId,
        resolution: Resolution,
        *,
        decided_by: str,
        at: datetime,
        note: str = "",
    ) -> "EntityReviewItem":
        self._require_open()
        return replace(
            self,
            status=ReviewStatus.RESOLVED,
            resolution=resolution,
            resolved_entity_id=entity_id,
            decided_by=decided_by,
            decided_at=at,
            note=note,
        )

    def reject(
        self, reason: EntityRejectReason, *, decided_by: str, at: datetime, note: str = ""
    ) -> "EntityReviewItem":
        self._require_open()
        return replace(
            self,
            status=ReviewStatus.REJECTED,
            reject_reason=reason,
            decided_by=decided_by,
            decided_at=at,
            note=note,
        )

    def _require_open(self) -> None:
        if self.status is not ReviewStatus.OPEN:
            raise InvariantViolationError(f"review item {self.review_id} is {self.status.value}")


@dataclass(frozen=True, slots=True)
class MentionGroup:
    """Open review items that share an entity type and a proposed name."""

    entity_type: EntityType
    proposed_name: str
    open_count: int
    examples: tuple[EntityReviewItem, ...]
