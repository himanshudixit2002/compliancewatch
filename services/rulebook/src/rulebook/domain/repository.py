"""What the rulebook use cases need from storage, as protocols. Regulatory data is global: there
is no tenant and no row-level security on these tables."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleId, RuleVersionId, UserId
from domain_kernel.knowledge import EntityType, RuleRelation
from domain_kernel.status import RuleVersionStatus
from domain_kernel.vectors import ClauseFilter, Vector
from rulebook.domain.alignment import EntityLookup
from rulebook.domain.changes import ChangeEntry, ChangeQuery
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.events import RulebookEvent
from rulebook.domain.graph import (
    ClauseDetail,
    EntityRecord,
    MentionedClause,
    RelationQuery,
    RelationRecord,
)
from rulebook.domain.intake import RuleCandidate
from rulebook.domain.publication import PendingReplacement, RuleVersionDecision
from rulebook.domain.relations import CandidateStatus, RelationCandidate
from rulebook.domain.review import EntityReviewItem, MentionGroup, ReviewQueueStats
from rulebook.domain.review_tasks import QueuedTask, ReviewTask, ReviewTaskStats, TaskQuery
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord, VersionPage
from rulebook.domain.runs import ExtractionRun, RuleSummary
from rulebook.domain.search import CitedClause, ClauseEmbedding


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

    def clause(self, clause_id: ClauseId) -> ClauseDetail | None:
        """One clause with its document, whichever document it is in."""
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

    def describe(self, entity_id: CanonicalEntityId) -> EntityRecord | None:
        """The entity with its aliases."""
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

    def entity_at(
        self, clause_id: ClauseId, span_start: int, entity_type: EntityType
    ) -> CanonicalEntityId | None:
        """The entity recorded for the mention of this type starting at this point, if any."""
        ...

    def clauses_mentioning(
        self, entity_id: CanonicalEntityId, as_of: date | None, limit: int
    ) -> Sequence[MentionedClause]:
        """Clauses that mention the entity, newest document first (undated ones last), then by
        document and clause order. With ``as_of``, only documents published on or before it, and
        each clause says whether it is out of force on that date."""
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

    def group_items(
        self, entity_type: EntityType, proposed_name: str
    ) -> tuple[EntityReviewItem, ...]:
        """Every open item of the group, without locking."""
        ...

    def save(self, item: EntityReviewItem) -> None: ...

    def queue_stats(self) -> ReviewQueueStats:
        """Open items per entity type and the time the oldest open item was queued."""
        ...


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

    def set_target_entity_at(
        self,
        clause_id: ClauseId,
        span_start: int,
        entity_type: EntityType,
        entity_id: CanonicalEntityId,
    ) -> int:
        """Point open unaligned candidates whose target is the mention at this span at the
        entity; how many."""
        ...


class RelationRepository(Protocol):
    def add(self, relation: RuleRelation, *, relation_id: UUID, candidate_id: UUID | None) -> bool:
        """Insert unless the same edge exists; whether this call inserted it."""
        ...

    def supersedes_edges(self) -> Mapping[RuleVersionId, frozenset[RuleVersionId]]:
        """Each rule version with the versions it supersedes."""
        ...

    def lock_supersession(self) -> None:
        """Serialise supersession approvals until the transaction ends, so two approvals
        cannot each pass the cycle check and together close a cycle."""
        ...

    def find(self, query: RelationQuery) -> Sequence[RelationRecord]:
        """Relations matching every id the query names, ordered by relation id."""
        ...

    def remove_approved(self, rule_version_id: RuleVersionId) -> tuple[UUID, ...]:
        """Delete the relations from the version that relation candidates were approved into,
        and return those candidates' ids in id order; a relation with no candidate stays. The
        caller removes only a draft's relations, once the rule candidate it was drafted from is
        rejected, and reopens each candidate in the same transaction
        (``relations.reopen_relations``)."""
        ...


class RuleVersionRepository(Protocol):
    def in_force(self, as_of: date, page: VersionPage) -> Sequence[RuleVersionRecord]:
        """Versions in force on ``as_of`` (``rule_versions.in_force``) that ``page`` admits,
        ordered by rule key then version, at most ``page.limit``."""
        ...

    def ended(self, since: date, page: VersionPage) -> Sequence[RuleVersionRecord]:
        """Versions that ended on or after ``since`` (``rule_versions.ended_since``: never a
        withdrawn one) that ``page`` admits, ordered by rule key then version, at most
        ``page.limit``."""
        ...

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionRecord | None:
        """The version in any status."""
        ...

    def lock(self, rule_version_id: RuleVersionId) -> RuleVersionRecord | None:
        """The version, locked for the rest of the transaction."""
        ...

    def lock_many(
        self, rule_version_ids: Sequence[RuleVersionId]
    ) -> Mapping[RuleVersionId, RuleVersionRecord]:
        """The versions that exist among ``rule_version_ids``, locked in id order."""
        ...

    def of_rule(self, rule_id: RuleId) -> Sequence[RuleVersionRecord]:
        """Every version of the rule, by version number."""
        ...

    def save_lifecycle(self, record: RuleVersionRecord) -> None:
        """Write the columns the review and publish flow changes: status, seed status,
        ``effective_to``, ``published_at``, ``submitted_at`` and ``high_impact``."""
        ...

    def save_draft(self, record: RuleVersionRecord) -> None:
        """Write the content an analyst edits in a draft (``review_tasks.EDITABLE_FIELDS``):
        title, summary, specification, obligation template, recurrence, the effective period
        and the open questions."""
        ...

    def record_decision(self, decision: RuleVersionDecision) -> None:
        """Append one row to the version's decision audit."""
        ...

    def decisions(self, rule_version_id: RuleVersionId) -> tuple[RuleVersionDecision, ...]:
        """The version's decision audit, oldest first."""
        ...

    def approvers(self, rule_version_id: RuleVersionId, since: datetime) -> frozenset[UserId]:
        """Who approved the version at or after ``since``, the start of the review round."""
        ...

    def replaced_by_others(
        self, rule_version_ids: Sequence[RuleVersionId], excluding: RuleVersionId
    ) -> frozenset[RuleVersionId]:
        """The versions among ``rule_version_ids`` that a published or superseded version other
        than ``excluding`` supersedes, corrects or withdraws."""
        ...

    def pending_replacements(self, today: date) -> Sequence[PendingReplacement]:
        """Published versions replaced by a published or superseded version whose
        ``effective_from`` is on or before ``today``."""
        ...

    def lock_publication(self) -> None:
        """Serialise publishing, withdrawing and the sweep until the transaction ends, so two
        of them cannot both pass the checks on the same versions."""
        ...

    def changes(self, query: ChangeQuery) -> Sequence[ChangeEntry]:
        """The changes the decision log records (``rulebook.domain.changes``) that ``query``
        asks for, newest first: changed at or after ``since``, of a version whose rule
        ``regulator`` issues, after ``after``, at most ``limit``."""
        ...

    def latest_version(self, rule_key: str) -> RuleVersionRecord | None:
        """The latest version of the rule with this key, in any status, with the rule locked
        for the rest of the transaction so two drafts never take one version number; None when
        no rule has the key."""
        ...

    def add_rule_and_version(self, record: RuleVersionRecord, *, new_rule: bool) -> None:
        """Insert ``record`` as a new draft version, its rule first when ``new_rule`` (with the
        record's rule id, key, regulator and level). A new rule whose key another rule has is
        ``RuleKeyTakenError``; the version number must follow the rule's latest."""
        ...


class CitationRepository(Protocol):
    def for_version(self, rule_version_id: RuleVersionId) -> tuple[CitationRecord, ...]:
        """The version's citations in document and clause order."""
        ...

    def add(self, citation: CitationRecord) -> bool:
        """Insert unless a citation with the id exists; whether this call inserted it."""
        ...


class RuleCandidateRepository(Protocol):
    def add(self, candidate: RuleCandidate) -> bool:
        """Insert unless a candidate with the id exists; whether this call inserted it."""
        ...

    def get(self, candidate_id: UUID) -> RuleCandidate | None: ...

    def lock(self, candidate_id: UUID) -> RuleCandidate | None:
        """The candidate, locked for the rest of the transaction."""
        ...

    def save(self, candidate: RuleCandidate) -> None:
        """Write the candidate's status, version, reject reason and decision."""
        ...


class ReviewTaskRepository(Protocol):
    def add(self, task: ReviewTask) -> bool:
        """Insert unless the version, or the candidate, has a task that is not decided; whether
        this call inserted it."""
        ...

    def get(self, task_id: UUID) -> ReviewTask | None: ...

    def lock(self, task_id: UUID) -> ReviewTask | None:
        """The task, locked for the rest of the transaction."""
        ...

    def save(self, task: ReviewTask) -> None:
        """Write the task's status, claim and decision, and the version a candidate task gets
        when it is drafted. A decided task never changes (``ReviewTaskClosedError``; the
        table's trigger refuses it too), nor does a task's version once it has one."""
        ...

    def page(self, query: TaskQuery) -> Sequence[QueuedTask]:
        """The tasks ``query`` admits, in queue order (``review_tasks.queue_position``), at most
        ``query.limit``, each with its version's summary."""
        ...

    def of_version(self, rule_version_id: RuleVersionId) -> tuple[ReviewTask, ...]:
        """Every task of the version, oldest first."""
        ...

    def of_candidate(self, candidate_id: UUID) -> tuple[ReviewTask, ...]:
        """Every task of the candidate, oldest first."""
        ...

    def drafts_without_task(self) -> Sequence[RuleVersionRecord]:
        """The seed drafts that need review (seed status needs_review, no candidate) and have
        no task that is not decided, by rule key and version. A draft made from a candidate is
        reviewed through its candidate's task, never a seed task."""
        ...

    def stats(self) -> ReviewTaskStats:
        """Tasks per regulator and status, the decisions made, the median time to decide, when
        the oldest task not decided yet was opened, and the decided candidates: approved (and
        how many of those with no edit recorded on their version) and rejected."""
        ...


class EventSink(Protocol):
    """Where the rulebook's events go inside the transaction: the outbox, each keyed by its
    partition key (a rule event by its rule)."""

    def publish(self, event: RulebookEvent) -> None: ...


class RuleCatalog(Protocol):
    def list_rules(self) -> tuple[RuleSummary, ...]: ...

    def rule_id(self, rule_key: str) -> UUID | None: ...

    def version_status(self, rule_version_id: RuleVersionId) -> RuleVersionStatus | None: ...


class ClauseIndex(Protocol):
    """Clause embeddings and the two search legs over clauses."""

    def store(self, model: str, embeddings: Sequence[ClauseEmbedding]) -> tuple[int, int]:
        """Insert each clause's embedding under ``model`` unless the clause has one from that
        model already (a stored embedding is never overwritten); (stored, unchanged)."""
        ...

    def unknown_clauses(self, clause_ids: Sequence[ClauseId]) -> frozenset[ClauseId]:
        """The ids no stored clause has."""
        ...

    def unembedded(
        self, model: str, document_id: DocumentId | None, limit: int, after: ClauseId | None
    ) -> Sequence[ClauseDetail]:
        """Clauses with no embedding from ``model``, in clause id order after ``after``."""
        ...

    def lexical(self, text: str, filters: ClauseFilter, pool: int) -> Sequence[ClauseId]:
        """Up to ``pool`` clauses matching any term of ``text``, best full-text rank first;
        none when the text has no searchable term."""
        ...

    def nearest(
        self, vector: Vector, model: str, filters: ClauseFilter, pool: int
    ) -> Sequence[ClauseId]:
        """Up to ``pool`` clauses embedded by ``model``, nearest by cosine distance first."""
        ...

    def hits(
        self, clause_ids: Sequence[ClauseId], as_of: date | None
    ) -> Mapping[ClauseId, CitedClause]:
        """The clauses with their documents, the versions citing them and whether each is out
        of force on ``as_of``."""
        ...


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
    def rule_versions(self) -> RuleVersionRepository: ...

    @property
    def citations(self) -> CitationRepository: ...

    @property
    def review_tasks(self) -> ReviewTaskRepository: ...

    @property
    def rule_candidates(self) -> RuleCandidateRepository: ...

    @property
    def index(self) -> ClauseIndex: ...

    @property
    def runs(self) -> RunRepository: ...

    @property
    def events(self) -> EventSink: ...


class KnowledgeUnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        """One transaction: committed when the block exits cleanly, rolled back otherwise."""
        ...
