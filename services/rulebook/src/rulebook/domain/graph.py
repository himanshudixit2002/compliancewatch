"""The knowledge graph as the read API returns it: entities, the clauses that mention them, the
relations between rule versions and their targets, and a clause with its document.

Resolving a name uses the same rules as alignment (``rulebook.domain.alignment``): the name is
normalised for its type, then matched exactly or through the one alias of exactly one entity.
Nothing is matched fuzzily, so a caller learns why a name did not resolve instead of getting a
guess.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleVersionId
from domain_kernel.knowledge import EntityType, RelationKind
from rulebook.domain.alignment import ReviewReason
from rulebook.domain.documents import StoredClause, StoredDocument


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNQUALIFIED = "unqualified"
    EMPTY = "empty"


STATUS_BY_REASON = {
    ReviewReason.NO_MATCH: ResolutionStatus.NOT_FOUND,
    ReviewReason.AMBIGUOUS_ALIAS: ResolutionStatus.AMBIGUOUS,
    ReviewReason.EMPTY_NAME: ResolutionStatus.EMPTY,
    ReviewReason.UNQUALIFIED: ResolutionStatus.UNQUALIFIED,
}
"""Why alignment would queue a name for review, as the status of a resolve."""


@dataclass(frozen=True, slots=True)
class EntityRecord:
    entity_id: CanonicalEntityId
    entity_type: EntityType
    canonical_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityResolution:
    """What a name resolves to: the entity when ``resolved``, the entities sharing the alias
    when ``ambiguous``, neither otherwise. ``normalised`` is the name that was looked up."""

    status: ResolutionStatus
    normalised: str
    entity: EntityRecord | None = None
    candidates: tuple[EntityRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ClauseDetail:
    """A clause with the document it belongs to."""

    clause: StoredClause
    document: StoredDocument


@dataclass(frozen=True, slots=True)
class MentionSpan:
    """Where a clause names the entity: the verbatim text and its half-open span."""

    text: str
    span_start: int
    span_end: int


@dataclass(frozen=True, slots=True)
class MentionedClause:
    """A clause that mentions an entity, with every span that does."""

    detail: ClauseDetail
    mentions: tuple[MentionSpan, ...]


@dataclass(frozen=True, slots=True)
class RelationRecord:
    """A rule relation with its evidence clause's ref and document, and, when it came from a
    candidate, the candidate's period and new due date (``extends_deadline`` only)."""

    relation_id: UUID
    from_rule_version_id: RuleVersionId
    relation: RelationKind
    to_kind: str
    to_ref: str
    to_rule_version_id: RuleVersionId | None
    to_entity_id: CanonicalEntityId | None
    evidence_clause_id: ClauseId
    evidence_clause_ref: str
    evidence_document_id: DocumentId
    candidate_id: UUID | None = None
    period_label: str | None = None
    new_due_on: date | None = None


@dataclass(frozen=True, slots=True)
class RelationQuery:
    """Relations from a version, to a version or to an entity; at least one of the three. With
    ``published_only`` the version a relation starts from must have been published (published
    or superseded): a draft's relations are not part of the rulebook yet."""

    from_rule_version_id: RuleVersionId | None = None
    to_rule_version_id: RuleVersionId | None = None
    to_entity_id: CanonicalEntityId | None = None
    relation: RelationKind | None = None
    published_only: bool = True
    limit: int = 100

    def __post_init__(self) -> None:
        if (
            self.from_rule_version_id is None
            and self.to_rule_version_id is None
            and self.to_entity_id is None
        ):
            raise InvariantViolationError(
                "name from_rule_version_id, to_rule_version_id or to_entity_id"
            )
        if self.limit < 1:
            raise InvariantViolationError("limit must be at least 1")
