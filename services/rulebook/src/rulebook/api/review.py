"""Knowledge written by the pipeline (mentions, relation candidates; ``PipelineWrite``) and the
analyst's review of it (the queues, ``ReviewRead``; entity groups and candidate approvals,
``AnalystWrite``, which records a signed-in user as the one who decided), plus the rule list the
pipeline offers the model."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.ids import CanonicalEntityId, DocumentId, RuleVersionId
from domain_kernel.knowledge import EntityType
from py_common.problems import problem_responses
from rulebook.api.deps import AnalystWrite, PipelineAccess, ReviewRead, Wired, decided_by
from rulebook.api.schemas import (
    AlignmentOut,
    ApprovalOut,
    ApproveIn,
    DecisionIn,
    GroupDecisionOut,
    MentionGroupOut,
    MentionsIn,
    RejectIn,
    RelationCandidateOut,
    RelationsIn,
    ReviewItemOut,
    RuleOut,
    StagingOut,
)
from rulebook.domain.relations import CandidateStatus

router = APIRouter()


@router.put(
    "/documents/{document_id}/mentions",
    summary="Align the entity mentions found in a document; the unresolved go to review",
    tags=["knowledge"],
    dependencies=[PipelineAccess],
    responses=problem_responses(401, 403, 404, 422, 503),
)
def submit_mentions(document_id: UUID, body: MentionsIn, wired: Wired) -> AlignmentOut:
    report = wired.align_mentions.run(
        DocumentId(document_id), body.extractor, [m.to_submitted() for m in body.mentions]
    )
    return AlignmentOut(aligned=report.aligned, queued=report.queued, unchanged=report.unchanged)


@router.put(
    "/documents/{document_id}/relation-candidates",
    summary="Stage the relations proposed for a document; idempotent per proposal",
    tags=["knowledge"],
    dependencies=[PipelineAccess],
    responses=problem_responses(401, 403, 404, 422, 503),
)
def submit_relations(document_id: UUID, body: RelationsIn, wired: Wired) -> StagingOut:
    report = wired.stage_relations.run(DocumentId(document_id), body.to_submission())
    return StagingOut(
        created=report.created, unchanged=report.unchanged, candidate_ids=list(report.candidate_ids)
    )


@router.get(
    "/review/entities",
    summary="Open entity review groups: one per (entity type, proposed name)",
    tags=["review"],
    dependencies=[ReviewRead],
    responses=problem_responses(401, 403),
)
def list_entity_groups(
    wired: Wired,
    entity_type: EntityType | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after_type: EntityType | None = None,
    after_name: str | None = None,
) -> list[MentionGroupOut]:
    after = None if after_type is None else (after_type.value, after_name or "")
    groups = wired.list_entity_groups.run(entity_type, limit, after)
    return [MentionGroupOut.from_group(group) for group in groups]


@router.get(
    "/review/entities/items",
    summary="Every open mention of one group, with the review ids a decision can name",
    tags=["review"],
    dependencies=[ReviewRead],
    responses=problem_responses(401, 403),
)
def list_group_items(
    wired: Wired, entity_type: EntityType, proposed_name: str = ""
) -> list[ReviewItemOut]:
    items = wired.list_group_items.run(entity_type, proposed_name)
    return [ReviewItemOut.from_item(item) for item in items]


@router.post(
    "/review/entities/decisions",
    summary="Create the entity, add the name to one, or reject every open mention of a group",
    tags=["review"],
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def decide_entity_group(body: DecisionIn, analyst: AnalystWrite, wired: Wired) -> GroupDecisionOut:
    decision = wired.decide_entity_group.run(
        body.entity_type,
        body.proposed_name,
        body.decision,
        decided_by=decided_by(analyst, body.decided_by),
        entity_id=None if body.entity_id is None else CanonicalEntityId(body.entity_id),
        reject_reason=body.reject_reason,
        note=body.note,
        review_ids=body.review_ids,
    )
    return GroupDecisionOut.from_decision(decision)


@router.get(
    "/review/relations",
    summary="Relation candidates, open ones by default, in id order",
    tags=["review"],
    dependencies=[ReviewRead],
    responses=problem_responses(401, 403),
)
def list_relation_candidates(
    wired: Wired,
    status: CandidateStatus | None = CandidateStatus.OPEN,
    document_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after: UUID | None = None,
) -> list[RelationCandidateOut]:
    found = wired.list_relations.run(
        status, None if document_id is None else DocumentId(document_id), limit, after
    )
    return [RelationCandidateOut.from_candidate(candidate) for candidate in found]


@router.post(
    "/review/relations/{candidate_id}/approve",
    summary="Approve a candidate into a rule relation from a draft rule version",
    tags=["review"],
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def approve_relation(
    candidate_id: UUID, body: ApproveIn, analyst: AnalystWrite, wired: Wired
) -> ApprovalOut:
    """The version the relation starts from must be a draft (409
    rulebook-rule-version-not-editable) that is not closed: a draft made from a rule candidate
    that was rejected takes no relation (409 rulebook-rule-version-closed)."""
    approval = wired.approve_relation.run(
        candidate_id,
        RuleVersionId(body.from_rule_version_id),
        None if body.target_rule_version_id is None else RuleVersionId(body.target_rule_version_id),
        decided_by=decided_by(analyst, body.decided_by),
        note=body.note,
    )
    return ApprovalOut(
        candidate_id=approval.candidate_id, rule_relation_id=approval.rule_relation_id
    )


@router.post(
    "/review/relations/{candidate_id}/reject",
    summary="Reject a candidate with a reason",
    tags=["review"],
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def reject_relation(
    candidate_id: UUID, body: RejectIn, analyst: AnalystWrite, wired: Wired
) -> RelationCandidateOut:
    rejected = wired.reject_relation.run(
        candidate_id, body.reason, decided_by=decided_by(analyst, body.decided_by), note=body.note
    )
    return RelationCandidateOut.from_candidate(rejected)


@router.get("/rules", summary="Rules by key with their latest title", tags=["rules"])
def list_rules(wired: Wired) -> list[RuleOut]:
    """Each rule with the title of its latest version. A draft made from a rule candidate that
    was rejected is closed and never its rule's latest version, so a rule only such drafts have
    is left out."""
    return [RuleOut.from_summary(rule) for rule in wired.list_rules.run()]
