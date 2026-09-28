"""What the rulebook use cases need from storage, as protocols. Regulatory data is global: there
is no tenant and no row-level security on these tables."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleVersionId
from domain_kernel.knowledge import EntityType, RuleRelation
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.alignment import EntityLookup
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.relations import CandidateStatus, RelationCandidate
from rulebook.domain.review import EntityReviewItem, MentionGroup
from rulebook.domain.runs import ExtractionRun, RuleSummary


class DocumentRepository(Protocol):
    def get(self, document_id: DocumentId) -> StoredDocument | None: ...

    def add(self, document: StoredDocument) -> bool:
        """Insert unless a row with the id exists; whether this call inserted it."""
        ...

    def clauses(self, document_id: DocumentId) -> tuple[StoredClause, ...]:
        """The document's clauses in order; empty when there are none."""
        ...

    def add_clauses(self, clauses: Sequence[StoredClause]) -> None:
        """Insert the clauses; ones whose id exists already are left as they are."""
        ...


class EntityRepository(EntityLookup, Protocol):
    def get(self, entity_id: CanonicalEntityId) -> tuple[EntityType, str] | None:
        """The entity's type and canonical name."""
        ...

    def create_or_get(self, entity_type: EntityType, name: str) -> tuple[CanonicalEntityId, bool]:
        """The entity with this canonical name, created when missing; whether it was created."""
        ...

    def add_alias(self, entity_id: CanonicalEntityId, alias: str) -> bool:
        """Add an alias unless the entity has it; whether it was added."""
        ...


class MentionRepository(Protocol):
    def add(
        self,
        clause_id: ClauseId,
        entity_id: CanonicalEntityId,
        mention_text: str,
        span_start: int,
        span_end: int,
        *,
        method: str,
        extractor: str,
    ) -> bool:
        """Record a resolved mention unless it is recorded; whether this call recorded it."""
        ...


class ReviewRepository(Protocol):
    def enqueue(self, item: EntityReviewItem) -> bool:
        """Queue an unresolved mention unless it is queued; whether this call queued it."""
        ...

    def open_groups(
        self, entity_type: EntityType | None, limit: int, after: tuple[str, str] | None
    ) -> Sequence[MentionGroup]:
        """Open groups ordered by (entity type, proposed name), after the given key."""
        ...

    def lock_group(
        self, entity_type: EntityType, proposed_name: str
    ) -> tuple[EntityReviewItem, ...]:
        """Every item of the group, open or decided, locked for this transaction."""
        ...

    def save(self, item: EntityReviewItem) -> None: ...


class CandidateRepository(Protocol):
    def add(self, candidate: RelationCandidate) -> bool:
        """Insert unless a candidate with the id exists; whether this call inserted it."""
        ...

    def lock(self, candidate_id: UUID) -> RelationCandidate | None: ...

    def page(
        self,
        status: CandidateStatus | None,
        document_id: DocumentId | None,
        limit: int,
        after: UUID | None,
    ) -> Sequence[RelationCandidate]:
        """Candidates ordered by id, after the given one."""
        ...

    def save(self, candidate: RelationCandidate) -> None: ...

    def set_target_entity(
        self, entity_type: EntityType, name: str, entity_id: CanonicalEntityId
    ) -> int:
        """Point open candidates whose target is this unaligned name at the entity; how many."""
        ...


class RelationRepository(Protocol):
    def add(self, relation: RuleRelation, *, relation_id: UUID, candidate_id: UUID | None) -> bool:
        """Insert unless the same edge exists; whether this call inserted it."""
        ...

    def supersedes_edges(self) -> Mapping[RuleVersionId, frozenset[RuleVersionId]]:
        """Each rule version with the versions it supersedes."""
        ...


class RuleCatalog(Protocol):
    def list_rules(self) -> tuple[RuleSummary, ...]: ...

    def rule_id(self, rule_key: str) -> UUID | None: ...

    def version_status(self, rule_version_id: RuleVersionId) -> RuleVersionStatus | None: ...


class RunRepository(Protocol):
    def record(self, run: ExtractionRun) -> bool:
        """Insert unless a run with the id exists; whether this call inserted it."""
        ...


class KnowledgeUnitOfWork(Protocol):
    @property
    def documents(self) -> DocumentRepository: ...

    @property
    def entities(self) -> EntityRepository: ...

    @property
    def mentions(self) -> MentionRepository: ...

    @property
    def reviews(self) -> ReviewRepository: ...

    @property
    def candidates(self) -> CandidateRepository: ...

    @property
    def relations(self) -> RelationRepository: ...

    @property
    def rules(self) -> RuleCatalog: ...

    @property
    def runs(self) -> RunRepository: ...


class KnowledgeUnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        """One transaction: committed when the block exits cleanly, rolled back otherwise."""
        ...
