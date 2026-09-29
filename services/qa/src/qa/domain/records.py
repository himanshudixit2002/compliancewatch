"""Read models of what the qa service reads from the rulebook, the profile service and the
obligation service, as far as answering needs them. A profile is the kernel's
``ProfileSnapshot``; everything else mirrors one response of the upstream read API.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Final
from uuid import UUID

from domain_kernel.ids import (
    BusinessId,
    CanonicalEntityId,
    ClauseId,
    DocumentId,
    ObligationId,
    RuleVersionId,
)
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.status import ObligationStatus
from domain_kernel.vectors import Vector

INDIA: Final = timezone(timedelta(hours=5, minutes=30))
"""Due dates and the default question date are days in India."""

OPEN_STATUSES: Final = frozenset({ObligationStatus.OPEN, ObligationStatus.IN_PROGRESS})


class ResolutionStatus(StrEnum):
    """How the rulebook resolved a name: ``resolved`` names one entity, ``ambiguous`` is an
    alias of several, ``unqualified`` is a section or rule without its statute, ``empty`` is
    nothing left after normalising."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNQUALIFIED = "unqualified"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class RuleVersion:
    """One rule version in force on the question's date, with the kernel's mapping forms of its
    specification and obligation template."""

    rule_version_id: RuleVersionId
    rule_key: str
    regulator: str
    version: int
    title: str
    effective_from: date
    effective_to: date | None = None
    status: str = "published"
    summary: str = ""
    specification: Mapping[str, object] = field(default_factory=dict, hash=False)
    obligation_template: Mapping[str, object] = field(default_factory=dict, hash=False)

    @property
    def label(self) -> str:
        return f"rule {self.rule_key} version {self.version}"


@dataclass(frozen=True, slots=True)
class VersionCitation:
    """A rule version's pointer to a clause; ``verified`` when the rulebook found the quote."""

    clause_id: ClauseId
    document_id: DocumentId
    clause_ref: str
    quote: str
    verified: bool


@dataclass(frozen=True, slots=True)
class RuleVersionDetail:
    version: RuleVersion
    citations: tuple[VersionCitation, ...] = ()


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: CanonicalEntityId
    entity_type: EntityType
    canonical_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityResolution:
    status: ResolutionStatus
    entity: Entity | None = None
    candidates: tuple[Entity, ...] = ()


@dataclass(frozen=True, slots=True)
class ClauseRecord:
    """A clause with what its document says about it: regulator, type, number and title.

    ``out_of_force`` is the rulebook's word on a search hit or an entity's clause: rule versions
    that were published cite the clause, and none of them is in force on the date asked about.
    A clause no such version cites is never out of force."""

    clause_id: ClauseId
    document_id: DocumentId
    clause_ref: str
    text: str
    regulator: str = ""
    doc_type: str = ""
    external_ref: str = ""
    title: str = ""
    published_at: date | None = None
    out_of_force: bool = False

    @property
    def source(self) -> str:
        """The document's number, else its title: how an answer names where a clause is."""
        return self.external_ref or self.title


@dataclass(frozen=True, slots=True)
class Relation:
    """A published relation from a rule version to another version or to an entity, with the
    clause that states it."""

    relation_id: UUID
    from_rule_version_id: RuleVersionId
    relation: RelationKind
    to_kind: str
    to_ref: str
    evidence_clause_id: ClauseId
    evidence_clause_ref: str
    to_rule_version_id: RuleVersionId | None = None
    to_entity_id: CanonicalEntityId | None = None
    period_label: str | None = None
    new_due_on: date | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A clause from hybrid search with its fused score and the versions citing it."""

    clause: ClauseRecord
    score: float
    cited_by: tuple[RuleVersionId, ...] = ()


@dataclass(frozen=True, slots=True)
class ObligationRecord:
    """One obligation of a business; ``due_at`` is the end of the due day in India, in UTC."""

    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    title: str
    status: ObligationStatus
    period_label: str | None = None
    due_at: datetime | None = None

    @property
    def due_on(self) -> date | None:
        return None if self.due_at is None else self.due_at.astimezone(INDIA).date()

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


@dataclass(frozen=True, slots=True)
class QueryEmbedding:
    """The question's vector and the model that served it; search needs both."""

    model: str
    vector: Vector
