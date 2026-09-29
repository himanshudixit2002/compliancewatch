"""Response bodies of the read API: rule versions, citations, entities, relations and clauses."""

from datetime import date, datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, Field

from domain_kernel.documents import DocumentType
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.graph import (
    ClauseDetail,
    EntityRecord,
    EntityResolution,
    MentionedClause,
    RelationRecord,
    ResolutionStatus,
)
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord
from rulebook.domain.seed import SeedStatus


class RuleVersionOut(BaseModel):
    rule_version_id: UUID
    rule_id: UUID
    rule_key: str
    regulator: str
    level: AttributeLevel
    version: int
    status: RuleVersionStatus
    title: str
    summary: str
    specification: dict[str, Any] = Field(description="The kernel's predicate tree mapping")
    obligation_template: dict[str, Any]
    recurrence: dict[str, Any] | None
    effective_from: date
    effective_to: date | None = Field(description="Exclusive; null while open-ended")
    source: dict[str, Any]
    seed_status: SeedStatus
    todo: list[str]
    published_at: datetime | None
    high_impact: bool = Field(description="Publishing needs two different approvers (ADR-006)")

    @classmethod
    def from_record(cls, record: RuleVersionRecord) -> Self:
        return cls(
            rule_version_id=record.rule_version_id.value,
            rule_id=record.rule_id.value,
            rule_key=record.rule_key,
            regulator=record.regulator,
            level=record.level,
            version=record.version,
            status=record.status,
            title=record.title,
            summary=record.summary,
            specification=dict(record.specification),
            obligation_template=dict(record.obligation_template),
            recurrence=None if record.recurrence is None else dict(record.recurrence),
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            source=dict(record.source),
            seed_status=record.seed_status,
            todo=list(record.todo),
            published_at=record.published_at,
            high_impact=record.high_impact,
        )


class CitationOut(BaseModel):
    citation_id: UUID
    rule_version_id: UUID
    clause_id: UUID
    document_id: UUID
    clause_ref: str
    quote: str
    verified: bool
    match_score: float | None
    verified_at: datetime | None

    @classmethod
    def from_record(cls, citation: CitationRecord) -> Self:
        return cls(
            citation_id=citation.citation_id,
            rule_version_id=citation.rule_version_id.value,
            clause_id=citation.clause_id.value,
            document_id=citation.document_id.value,
            clause_ref=citation.clause_ref,
            quote=citation.quote,
            verified=citation.verified,
            match_score=citation.match_score,
            verified_at=citation.verified_at,
        )


class RuleVersionDetailOut(RuleVersionOut):
    citations: list[CitationOut]

    @classmethod
    def from_detail(cls, record: RuleVersionRecord, citations: tuple[CitationRecord, ...]) -> Self:
        return cls(
            **RuleVersionOut.from_record(record).model_dump(),
            citations=[CitationOut.from_record(citation) for citation in citations],
        )


class EntityOut(BaseModel):
    entity_id: UUID
    entity_type: EntityType
    canonical_name: str
    aliases: list[str]

    @classmethod
    def from_record(cls, entity: EntityRecord) -> Self:
        return cls(
            entity_id=entity.entity_id.value,
            entity_type=entity.entity_type,
            canonical_name=entity.canonical_name,
            aliases=list(entity.aliases),
        )


class EntityResolutionOut(BaseModel):
    status: ResolutionStatus = Field(
        description=(
            "resolved: entity is set. ambiguous: the name is an alias of every entity in "
            "candidates. not_found: nothing has the name. unqualified: a section or rule "
            "without its statute (39@cgst-act). empty: nothing left after normalising"
        )
    )
    entity_type: EntityType
    name: str
    normalised: str
    entity: EntityOut | None
    candidates: list[EntityOut]

    @classmethod
    def from_resolution(cls, entity_type: EntityType, name: str, found: EntityResolution) -> Self:
        return cls(
            status=found.status,
            entity_type=entity_type,
            name=name,
            normalised=found.normalised,
            entity=None if found.entity is None else EntityOut.from_record(found.entity),
            candidates=[EntityOut.from_record(entity) for entity in found.candidates],
        )


class ClauseDetailOut(BaseModel):
    clause_id: UUID
    document_id: UUID
    clause_ref: str
    ordinal: int
    page: int | None
    text: str
    regulator: str
    doc_type: DocumentType
    external_ref: str
    title: str
    url: str
    language: str
    published_at: date | None

    @classmethod
    def fields_of(cls, detail: ClauseDetail) -> dict[str, Any]:
        clause, document = detail.clause, detail.document
        return {
            "clause_id": clause.clause_id.value,
            "document_id": clause.document_id.value,
            "clause_ref": clause.clause_ref,
            "ordinal": clause.ordinal,
            "page": clause.page,
            "text": clause.text,
            "regulator": document.regulator,
            "doc_type": document.doc_type,
            "external_ref": document.external_ref,
            "title": document.title,
            "url": document.url,
            "language": document.language,
            "published_at": document.published_at,
        }

    @classmethod
    def from_detail(cls, detail: ClauseDetail) -> Self:
        return cls(**cls.fields_of(detail))


class MentionOut(BaseModel):
    text: str
    span_start: int
    span_end: int


class MentionedClauseOut(ClauseDetailOut):
    mentions: list[MentionOut]
    out_of_force: bool = Field(
        description=(
            "The clause is cited with a verified quote by a published, superseded or withdrawn "
            "version and none of them is in force on as_of; false without as_of or a citation"
        )
    )

    @classmethod
    def from_mentioned(cls, found: MentionedClause) -> Self:
        return cls(
            **cls.fields_of(found.detail),
            mentions=[
                MentionOut(text=span.text, span_start=span.span_start, span_end=span.span_end)
                for span in found.mentions
            ],
            out_of_force=found.out_of_force,
        )


class RelationOut(BaseModel):
    relation_id: UUID
    from_rule_version_id: UUID
    relation: RelationKind
    to_kind: str = Field(description="rule_version or an entity type")
    to_ref: str = Field(description="The target version's id or the entity's canonical name")
    to_rule_version_id: UUID | None
    to_entity_id: UUID | None
    evidence_clause_id: UUID
    evidence_clause_ref: str
    evidence_document_id: UUID
    candidate_id: UUID | None
    period_label: str | None
    new_due_on: date | None

    @classmethod
    def from_record(cls, relation: RelationRecord) -> Self:
        return cls(
            relation_id=relation.relation_id,
            from_rule_version_id=relation.from_rule_version_id.value,
            relation=relation.relation,
            to_kind=relation.to_kind,
            to_ref=relation.to_ref,
            to_rule_version_id=None
            if relation.to_rule_version_id is None
            else relation.to_rule_version_id.value,
            to_entity_id=None if relation.to_entity_id is None else relation.to_entity_id.value,
            evidence_clause_id=relation.evidence_clause_id.value,
            evidence_clause_ref=relation.evidence_clause_ref,
            evidence_document_id=relation.evidence_document_id.value,
            candidate_id=relation.candidate_id,
            period_label=relation.period_label,
            new_due_on=relation.new_due_on,
        )
