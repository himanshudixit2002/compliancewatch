"""Request and response bodies of the rulebook API."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from domain_kernel.documents import PARSER_VERSION_PATTERN, Clause, DocumentType
from domain_kernel.ids import DocumentId, SourceId
from domain_kernel.knowledge import EntityType, RelationKind
from rulebook.application.alignment import SubmittedMention
from rulebook.application.documents import Registration
from rulebook.application.relations import RelationSubmission, SubmittedCandidate
from rulebook.application.review import GroupDecision
from rulebook.domain.documents import CLAUSE_REF_PATTERN, StoredClause, StoredDocument
from rulebook.domain.relations import (
    CandidateIssue,
    CandidateRejectReason,
    RelationCandidate,
)
from rulebook.domain.review import (
    EntityRejectReason,
    EntityReviewItem,
    MentionDecision,
    MentionGroup,
)
from rulebook.domain.runs import RuleSummary

SHA256_PATTERN = r"^[0-9a-f]{64}$"
DECIDED_BY = "Who decided; a signed-in user's token overrides it with that user's id"


class ClauseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_ref: str = Field(pattern=CLAUSE_REF_PATTERN, examples=["en.p3"])
    text: str = Field(min_length=1, max_length=50_000)
    page: int | None = Field(default=None, ge=1)

    def to_clause(self) -> Clause:
        return Clause(clause_ref=self.clause_ref, text=self.text, page=self.page)


class DocumentIn(BaseModel):
    """A parsed regulator document. The id in the path must be the first half of ``sha256``."""

    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    sha256: str = Field(pattern=SHA256_PATTERN)
    regulator: str = Field(min_length=1, max_length=40, examples=["CBIC"])
    doc_type: DocumentType
    external_ref: str = Field(default="", max_length=200, examples=["01/2026-Central Tax"])
    url: str = Field(min_length=1, max_length=2_000)
    title: str = Field(default="", max_length=2_000)
    language: str = Field(min_length=1, max_length=8, examples=["en"])
    media_type: str = Field(min_length=1, max_length=80, examples=["application/pdf"])
    parser_version: str = Field(pattern=PARSER_VERSION_PATTERN, max_length=40, examples=["pdf@1"])
    published_at: date | None = None
    fetched_at: AwareDatetime
    raw_uri: str | None = Field(default=None, max_length=2_000)
    clauses: list[ClauseIn] = Field(min_length=1, max_length=2_000)

    def to_document(self, document_id: UUID) -> StoredDocument:
        return StoredDocument(
            document_id=DocumentId(document_id),
            source_id=SourceId(self.source_id),
            sha256=self.sha256,
            regulator=self.regulator,
            doc_type=self.doc_type,
            url=self.url,
            language=self.language,
            media_type=self.media_type,
            parser_version=self.parser_version,
            fetched_at=self.fetched_at,
            external_ref=self.external_ref,
            title=self.title,
            published_at=self.published_at,
            raw_uri=self.raw_uri,
        )


class RegisteredOut(BaseModel):
    document_id: UUID
    created: bool
    clause_ids: dict[str, UUID] = Field(description="Clause ref to the id every service derives")
    metadata_differs: list[str] = Field(
        description="Fields whose submitted value differs from the stored one; the stored wins"
    )

    @classmethod
    def from_registration(cls, registration: Registration) -> Self:
        return cls(
            document_id=registration.document_id.value,
            created=registration.created,
            clause_ids={ref: clause_id.value for ref, clause_id in registration.clause_ids.items()},
            metadata_differs=list(registration.metadata_differs),
        )


class ClauseOut(BaseModel):
    clause_id: UUID
    clause_ref: str
    ordinal: int
    page: int | None
    text: str

    @classmethod
    def from_clause(cls, clause: StoredClause) -> Self:
        return cls(
            clause_id=clause.clause_id.value,
            clause_ref=clause.clause_ref,
            ordinal=clause.ordinal,
            page=clause.page,
            text=clause.text,
        )


class DocumentOut(BaseModel):
    document_id: UUID
    source_id: UUID
    sha256: str
    regulator: str
    doc_type: DocumentType
    external_ref: str
    url: str
    title: str
    language: str
    media_type: str
    parser_version: str
    published_at: date | None
    clauses: list[ClauseOut]

    @classmethod
    def from_stored(cls, document: StoredDocument, clauses: tuple[StoredClause, ...]) -> Self:
        return cls(
            document_id=document.document_id.value,
            source_id=document.source_id.value,
            sha256=document.sha256,
            regulator=document.regulator,
            doc_type=document.doc_type,
            external_ref=document.external_ref,
            url=document.url,
            title=document.title,
            language=document.language,
            media_type=document.media_type,
            parser_version=document.parser_version,
            published_at=document.published_at,
            clauses=[ClauseOut.from_clause(clause) for clause in clauses],
        )


class MentionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_ref: str = Field(pattern=CLAUSE_REF_PATTERN)
    entity_type: EntityType
    text: str = Field(min_length=1, max_length=2_000)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=1)
    proposed_name: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def _span_is_forward(self) -> Self:
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be greater than span_start")
        return self

    def to_submitted(self) -> SubmittedMention:
        return SubmittedMention(
            clause_ref=self.clause_ref,
            entity_type=self.entity_type,
            text=self.text,
            span_start=self.span_start,
            span_end=self.span_end,
            proposed_name=self.proposed_name,
        )


class MentionsIn(BaseModel):
    """The mentions an extractor found in one document; the extractor names itself."""

    model_config = ConfigDict(extra="forbid")

    extractor: str = Field(pattern=PARSER_VERSION_PATTERN, max_length=60, examples=["grammar@1"])
    mentions: list[MentionIn] = Field(max_length=20_000)


class AlignmentOut(BaseModel):
    aligned: int
    queued: int
    unchanged: int


class IssueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=60)
    detail: str = Field(default="", max_length=2_000)


class CandidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation: RelationKind
    target_type: EntityType
    target_name: str = Field(min_length=1, max_length=400)
    target_clause_ref: str = Field(pattern=CLAUSE_REF_PATTERN)
    target_span_start: int = Field(ge=0)
    target_span_end: int = Field(ge=1)
    rule_key: str | None = Field(default=None, max_length=80)
    evidence_clause_ref: str = Field(pattern=CLAUSE_REF_PATTERN)
    evidence_quote: str = Field(min_length=8, max_length=400)
    quote_score: float = Field(ge=0, le=1)
    period_label: str | None = Field(default=None, max_length=16)
    new_due_on: date | None = None
    confidence: float = Field(ge=0, le=1)
    issues: list[IssueIn] = Field(default_factory=list, max_length=50)
    needs_review: bool

    @model_validator(mode="after")
    def _span_is_forward(self) -> Self:
        if self.target_span_end <= self.target_span_start:
            raise ValueError("target_span_end must be greater than target_span_start")
        return self

    def to_submitted(self) -> SubmittedCandidate:
        return SubmittedCandidate(
            relation=self.relation,
            target_type=self.target_type,
            target_name=self.target_name,
            target_clause_ref=self.target_clause_ref,
            target_span_start=self.target_span_start,
            target_span_end=self.target_span_end,
            evidence_clause_ref=self.evidence_clause_ref,
            evidence_quote=self.evidence_quote,
            quote_score=self.quote_score,
            confidence=self.confidence,
            needs_review=self.needs_review,
            rule_key=self.rule_key,
            period_label=self.period_label,
            new_due_on=self.new_due_on,
            issues=tuple(CandidateIssue(i.code, i.detail) for i in self.issues),
        )


class RelationsIn(BaseModel):
    """What one run of the relation stage produced for a document, including the run's own
    issues and any model output it could not turn into a candidate."""

    model_config = ConfigDict(extra="forbid")

    extractor: str = Field(min_length=1, max_length=60, examples=["extraction.rule_relations@1"])
    model: str = Field(default="", max_length=120)
    outcome: Literal["ok", "needs_review", "no_targets", "unparseable", "failed"]
    run_issues: list[IssueIn] = Field(default_factory=list, max_length=200)
    candidates: list[CandidateIn] = Field(default_factory=list, max_length=200)

    def to_submission(self) -> RelationSubmission:
        return RelationSubmission(
            extractor=self.extractor,
            model=self.model,
            outcome=self.outcome,
            candidates=tuple(c.to_submitted() for c in self.candidates),
            run_issues=tuple({"code": i.code, "detail": i.detail} for i in self.run_issues),
        )


class StagingOut(BaseModel):
    created: int
    unchanged: int
    candidate_ids: list[UUID]


class ReviewItemOut(BaseModel):
    review_id: UUID
    document_id: UUID
    clause_id: UUID
    mention_text: str
    span_start: int
    span_end: int
    reason: str

    @classmethod
    def from_item(cls, item: EntityReviewItem) -> Self:
        return cls(
            review_id=item.review_id,
            document_id=item.document_id.value,
            clause_id=item.clause_id.value,
            mention_text=item.mention_text,
            span_start=item.span_start,
            span_end=item.span_end,
            reason=item.reason.value,
        )


class MentionGroupOut(BaseModel):
    entity_type: EntityType
    proposed_name: str
    open_count: int
    examples: list[ReviewItemOut]

    @classmethod
    def from_group(cls, group: MentionGroup) -> Self:
        return cls(
            entity_type=group.entity_type,
            proposed_name=group.proposed_name,
            open_count=group.open_count,
            examples=[ReviewItemOut.from_item(item) for item in group.examples],
        )


class DecisionIn(BaseModel):
    """Decide every open mention of one (entity type, proposed name)."""

    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    proposed_name: str = Field(max_length=400)
    decision: MentionDecision
    entity_id: UUID | None = Field(default=None, description="The entity to add the name to")
    reject_reason: EntityRejectReason | None = None
    review_ids: list[UUID] | None = Field(
        default=None,
        max_length=200,
        description=(
            "The mentions this decision covers. Required for a name that does not name one "
            "entity across documents (empty, or a section or rule without its statute)"
        ),
    )
    decided_by: str = Field(min_length=1, max_length=120, description=DECIDED_BY)
    note: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def _decision_has_what_it_needs(self) -> Self:
        if self.decision is MentionDecision.ADD_ALIAS and self.entity_id is None:
            raise ValueError("add_alias needs entity_id")
        if self.decision is MentionDecision.REJECT and self.reject_reason is None:
            raise ValueError("reject needs reject_reason")
        return self


class GroupDecisionOut(BaseModel):
    status: str
    resolution: str | None
    entity_id: UUID | None
    items_closed: int
    relation_targets_updated: int

    @classmethod
    def from_decision(cls, decision: GroupDecision) -> Self:
        return cls(
            status=decision.status.value,
            resolution=None if decision.resolution is None else decision.resolution.value,
            entity_id=None if decision.entity_id is None else decision.entity_id.value,
            items_closed=decision.items_closed,
            relation_targets_updated=decision.relation_targets_updated,
        )


class RelationCandidateOut(BaseModel):
    candidate_id: UUID
    document_id: UUID
    relation: RelationKind
    target_type: EntityType
    target_name: str
    target_entity_id: UUID | None
    target_rule_key: str | None
    evidence_clause_id: UUID
    evidence_quote: str
    quote_score: float
    period_label: str | None
    new_due_on: date | None
    prompt_version: str
    model: str
    confidence: float
    issues: list[IssueIn]
    needs_review: bool
    status: str
    reject_reason: str | None
    decided_by: str

    @classmethod
    def from_candidate(cls, candidate: RelationCandidate) -> Self:
        return cls(
            candidate_id=candidate.candidate_id,
            document_id=candidate.document_id.value,
            relation=candidate.relation,
            target_type=candidate.target_type,
            target_name=candidate.target_name,
            target_entity_id=None
            if candidate.target_entity_id is None
            else candidate.target_entity_id.value,
            target_rule_key=candidate.target_rule_key,
            evidence_clause_id=candidate.evidence_clause_id.value,
            evidence_quote=candidate.evidence_quote,
            quote_score=candidate.quote_score,
            period_label=candidate.period_label,
            new_due_on=candidate.new_due_on,
            prompt_version=candidate.prompt_version,
            model=candidate.model,
            confidence=candidate.confidence,
            issues=[IssueIn(code=i.code, detail=i.detail) for i in candidate.issues],
            needs_review=candidate.needs_review,
            status=candidate.status.value,
            reject_reason=None
            if candidate.reject_reason is None
            else candidate.reject_reason.value,
            decided_by=candidate.decided_by,
        )


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_rule_version_id: UUID = Field(description="The new version the relation starts from")
    target_rule_version_id: UUID | None = Field(
        default=None, description="The affected version, for relations that target one"
    )
    decided_by: str = Field(min_length=1, max_length=120, description=DECIDED_BY)
    note: str = Field(default="", max_length=2_000)


class ApprovalOut(BaseModel):
    candidate_id: UUID
    rule_relation_id: UUID


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: CandidateRejectReason
    decided_by: str = Field(min_length=1, max_length=120, description=DECIDED_BY)
    note: str = Field(default="", max_length=2_000)


class RuleOut(BaseModel):
    rule_key: str
    rule_id: UUID
    regulator: str
    title: str

    @classmethod
    def from_summary(cls, rule: RuleSummary) -> Self:
        return cls(
            rule_key=rule.rule_key, rule_id=rule.rule_id, regulator=rule.regulator, title=rule.title
        )
