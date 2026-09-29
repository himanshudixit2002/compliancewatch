"""Ids the rulebook derives for its own rows, so a repeated submission lands on the same row."""

from uuid import UUID

from domain_kernel.ids import ClauseId, DocumentId, EntityId, RuleVersionId, derive_id
from domain_kernel.knowledge import EntityType, RelationKind


def review_id_for(clause_id: ClauseId, entity_type: EntityType, span_start: int) -> UUID:
    """One review item per mention: its clause, type and start."""
    return derive_id(
        EntityId, "entity_review", str(clause_id), entity_type.value, str(span_start)
    ).value


def candidate_id_for(
    document_id: DocumentId,
    relation: RelationKind,
    target_type: EntityType,
    target_name: str,
    evidence_clause_id: ClauseId,
) -> UUID:
    """One relation candidate per semantic proposal, whoever proposed it first."""
    return derive_id(
        EntityId,
        "relation_candidate",
        str(document_id),
        relation.value,
        target_type.value,
        target_name,
        str(evidence_clause_id),
    ).value


def run_id_for(document_id: DocumentId, stage: str, extractor: str) -> UUID:
    return derive_id(EntityId, "extraction_run", str(document_id), stage, extractor).value


def rule_relation_id_for(
    from_rule_version: UUID, relation: RelationKind, to_kind: str, to_ref: str, clause_id: ClauseId
) -> UUID:
    return derive_id(
        EntityId,
        "rule_relation",
        str(from_rule_version),
        relation.value,
        to_kind,
        to_ref,
        str(clause_id),
    ).value


def citation_id_for(rule_version_id: RuleVersionId, clause_id: ClauseId, quote: str) -> UUID:
    """One citation per version, clause and quote: adding the same citation again is a no-op."""
    return derive_id(EntityId, "citation", str(rule_version_id), str(clause_id), quote).value
