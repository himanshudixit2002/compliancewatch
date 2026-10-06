"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rulebook.application.alignment import AlignMentions
from rulebook.application.changes import ListChanges
from rulebook.application.documents import ReadDocument, RegisterDocument
from rulebook.application.graph import (
    ListEntityClauses,
    ListRelations,
    ReadClause,
    ReadEntity,
    ResolveEntity,
)
from rulebook.application.publication import (
    AddCitations,
    ApplyDueTransitions,
    ApproveVersion,
    PublishVersion,
    ReturnToDraft,
    SubmitForReview,
    WithdrawVersion,
)
from rulebook.application.relations import (
    ApproveRelationCandidate,
    ListRelationCandidates,
    ListRules,
    RejectRelationCandidate,
    StageRelationCandidates,
)
from rulebook.application.review import DecideMentionGroup, ListGroupItems, ListMentionGroups
from rulebook.application.review_tasks import (
    ClaimReviewTask,
    DecideReviewTask,
    DraftFromCandidate,
    EditReviewDraft,
    ListReviewTasks,
    OpenSeedReviewTasks,
    ReadReviewStats,
    ReadReviewTask,
)
from rulebook.application.rule_versions import (
    ListCitations,
    ListEndedVersions,
    ListRulesInForce,
    ListRuleVersions,
    ReadRuleVersion,
)
from rulebook.application.search import ListUnembeddedClauses, SearchClauses, StoreEmbeddings
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.settings import RulebookSettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: RulebookSettings
    unit_of_work: KnowledgeUnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    register_document: RegisterDocument
    read_document: ReadDocument
    align_mentions: AlignMentions
    list_entity_groups: ListMentionGroups
    list_group_items: ListGroupItems
    decide_entity_group: DecideMentionGroup
    stage_relations: StageRelationCandidates
    list_relations: ListRelationCandidates
    approve_relation: ApproveRelationCandidate
    reject_relation: RejectRelationCandidate
    list_rules: ListRules
    list_rules_in_force: ListRulesInForce
    list_ended_versions: ListEndedVersions
    list_rule_versions: ListRuleVersions
    read_rule_version: ReadRuleVersion
    list_citations: ListCitations
    resolve_entity: ResolveEntity
    read_entity: ReadEntity
    list_entity_clauses: ListEntityClauses
    list_rule_relations: ListRelations
    read_clause: ReadClause
    store_embeddings: StoreEmbeddings
    list_unembedded: ListUnembeddedClauses
    search_clauses: SearchClauses
    add_citations: AddCitations
    submit_version: SubmitForReview
    return_version: ReturnToDraft
    approve_version: ApproveVersion
    publish_version: PublishVersion
    withdraw_version: WithdrawVersion
    apply_transitions: ApplyDueTransitions
    list_changes: ListChanges
    open_seed_tasks: OpenSeedReviewTasks
    list_review_tasks: ListReviewTasks
    claim_review_task: ClaimReviewTask
    read_review_task: ReadReviewTask
    draft_from_candidate: DraftFromCandidate
    edit_review_draft: EditReviewDraft
    decide_review_task: DecideReviewTask
    read_review_stats: ReadReviewStats
