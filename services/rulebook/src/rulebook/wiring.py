"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rulebook.application.alignment import AlignMentions
from rulebook.application.documents import ReadDocument, RegisterDocument
from rulebook.application.relations import (
    ApproveRelationCandidate,
    ListRelationCandidates,
    ListRules,
    RejectRelationCandidate,
    StageRelationCandidates,
)
from rulebook.application.review import DecideMentionGroup, ListMentionGroups
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
    decide_entity_group: DecideMentionGroup
    stage_relations: StageRelationCandidates
    list_relations: ListRelationCandidates
    approve_relation: ApproveRelationCandidate
    reject_relation: RejectRelationCandidate
    list_rules: ListRules
