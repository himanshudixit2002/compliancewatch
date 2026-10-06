"""Request and response bodies of the review task routes."""

from datetime import date, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domain_kernel.documents import DocumentType, clause_id_for
from domain_kernel.ids import RuleVersionId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from rulebook.api.publication_schemas import CitationIn, EventOut, LifecycleOut
from rulebook.api.read_schemas import CitationOut, RuleVersionOut
from rulebook.application.publication import MAX_CITATIONS, CitationInput
from rulebook.application.review_tasks import (
    MAX_RELATIONS,
    CandidateDetail,
    NewRule,
    RelationChoice,
    TaskDecision,
    TaskDetail,
)
from rulebook.domain.documents import StoredDocument
from rulebook.domain.drafting import (
    EDITABLE_FIELDS,
    MAX_QUESTION,
    MAX_SUMMARY,
    MAX_TITLE,
    MAX_TODO,
    DraftEdit,
)
from rulebook.domain.intake import (
    MAX_RULE_KEY,
    CandidateOutcome,
    CandidateSummary,
    RuleCandidateStatus,
    RuleRejectReason,
    version_closed,
)
from rulebook.domain.publication import DecisionAction, RuleVersionDecision, required_approvals
from rulebook.domain.review_tasks import (
    MAX_NOTE,
    QueuedTask,
    ReviewDecision,
    ReviewTask,
    ReviewTaskKind,
    ReviewTaskStats,
    ReviewTaskStatus,
    TaskKey,
)

RULE_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class ReviewTaskOut(BaseModel):
    task_id: UUID
    rule_version_id: UUID | None = Field(
        description="The version the task reviews; null for a candidate task not drafted yet"
    )
    kind: ReviewTaskKind = Field(
        description=(
            "seed: a draft the seed calendar wrote; candidate: a rule candidate the pipeline "
            "extracted, and the version drafted from it"
        )
    )
    candidate_id: UUID | None = Field(description="A candidate task's rule candidate")
    priority: int = Field(description="Higher comes first within a regulator")
    regulator: str
    status: ReviewTaskStatus
    opened_at: datetime
    claimed_by: UUID | None = Field(description="The analyst who claimed the task")
    claimed_at: datetime | None
    decision: ReviewDecision | None
    decided_by: UUID | None
    decided_at: datetime | None
    note: str = Field(description="The decision's note")

    @classmethod
    def from_task(cls, task: ReviewTask) -> Self:
        return cls(
            task_id=task.task_id,
            rule_version_id=None if task.rule_version_id is None else task.rule_version_id.value,
            kind=task.kind,
            candidate_id=task.candidate_id,
            priority=task.priority,
            regulator=task.regulator,
            status=task.status,
            opened_at=task.opened_at,
            claimed_by=None if task.claimed_by is None else task.claimed_by.value,
            claimed_at=task.claimed_at,
            decision=task.decision,
            decided_by=None if task.decided_by is None else task.decided_by.value,
            decided_at=task.decided_at,
            note=task.note,
        )


class QueuedCandidateOut(BaseModel):
    """What the queue shows of a candidate task's candidate."""

    candidate_id: UUID
    document_id: UUID
    status: RuleCandidateStatus
    outcome: CandidateOutcome = Field(
        description="extracted, or unparseable: no candidate, so an analyst drafts by hand"
    )
    confidence: float
    needs_review: bool = Field(description="The extraction asked for review")
    issue_count: int = Field(description="What the validators found wrong with it")
    suggested_rule_key: str | None
    high_impact_suggested: bool

    @classmethod
    def from_summary(cls, summary: CandidateSummary) -> Self:
        return cls(
            candidate_id=summary.candidate_id,
            document_id=summary.document_id.value,
            status=summary.status,
            outcome=summary.outcome,
            confidence=summary.confidence,
            needs_review=summary.needs_review,
            issue_count=summary.issue_count,
            suggested_rule_key=summary.suggested_rule_key,
            high_impact_suggested=summary.high_impact_suggested,
        )


class QueuedTaskOut(ReviewTaskOut):
    rule_key: str | None = Field(
        description="The version's rule; before drafting, the key suggested for the candidate"
    )
    version: int | None = Field(description="The version's number; null before drafting")
    title: str = Field(description="The version's title, or the candidate's before drafting")
    version_status: RuleVersionStatus | None = Field(description="Null before drafting")
    high_impact: bool = Field(description="Before drafting, what the candidate suggests")
    approvals: int = Field(description="Distinct approvers of the version's current review round")
    required_approvals: int = Field(description="One, or two different ones when high impact")
    candidate: QueuedCandidateOut | None = Field(description="A candidate task's candidate")

    @classmethod
    def from_queued(cls, queued: QueuedTask) -> Self:
        return cls(
            **ReviewTaskOut.from_task(queued.task).model_dump(),
            rule_key=queued.rule_key,
            version=queued.version,
            title=queued.title,
            version_status=queued.version_status,
            high_impact=queued.high_impact,
            approvals=queued.approvals,
            required_approvals=required_approvals(queued.high_impact),
            candidate=None
            if queued.candidate is None
            else QueuedCandidateOut.from_summary(queued.candidate),
        )


class TaskCursor(BaseModel):
    """The keyset of the queue: the regulator, the priority, when the task opened and its id."""

    r: str
    p: int
    o: AwareDatetime
    i: UUID

    @classmethod
    def of(cls, queued: QueuedTask) -> Self:
        task = queued.task
        return cls(r=task.regulator, p=task.priority, o=task.opened_at, i=task.task_id)

    def key(self) -> TaskKey:
        return TaskKey(self.r, self.p, self.o, self.i)


class SeedTasksOut(BaseModel):
    opened: int = Field(description="Tasks this request opened; 0 when every draft has one")
    task_ids: list[UUID]


class ClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: UUID = Field(
        description="The analyst claiming the task; a signed-in user's token overrides it"
    )


Question = Annotated[str, Field(min_length=1, max_length=MAX_QUESTION)]


class DraftFieldsIn(BaseModel):
    """The content fields of a draft, each one optional: a field left out keeps its value, and
    null clears ``recurrence`` or ``effective_to``."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    summary: str | None = Field(default=None, max_length=MAX_SUMMARY)
    specification: dict[str, Any] | None = Field(
        default=None, description="The kernel's predicate tree mapping"
    )
    obligation_template: dict[str, Any] | None = None
    recurrence: dict[str, Any] | None = Field(default=None, description="null: no recurrence")
    effective_from: date | None = None
    effective_to: date | None = Field(default=None, description="Exclusive; null: open-ended")
    todo: list[Question] | None = Field(
        default=None, max_length=MAX_TODO, description="The open questions, all of them"
    )

    def to_edit(self) -> DraftEdit | None:
        sent = [name for name in EDITABLE_FIELDS if name in self.model_fields_set]
        if not sent:
            return None
        return DraftEdit({name: getattr(self, name) for name in sent})


class DraftEditIn(DraftFieldsIn):
    """The fields to change, each one optional: a field left out keeps its value, and null
    clears ``recurrence`` or ``effective_to``. ``citations`` are added, never removed, and every
    quote must be in its clause. At least one field or one citation."""

    actor_id: UUID = Field(
        description="The analyst who claimed the task; a signed-in user's token overrides it"
    )
    note: str = Field(default="", max_length=MAX_NOTE, description="Why, for the audit")
    citations: list[CitationIn] | None = Field(default=None, min_length=1, max_length=MAX_CITATIONS)

    def to_citations(self) -> list[CitationInput]:
        return [citation.to_input() for citation in self.citations or ()]


class NewRuleIn(BaseModel):
    """The rule a draft starts when its key is new."""

    model_config = ConfigDict(extra="forbid")

    regulator: str = Field(
        min_length=1, max_length=40, description="The candidate's regulator; compared in lower case"
    )
    level: AttributeLevel = Field(description="Where the rule applies: entity, registration...")

    def to_new_rule(self) -> NewRule:
        return NewRule(regulator=self.regulator, level=self.level)


class RelationChoiceIn(BaseModel):
    """A relation candidate of the candidate's document to approve onto the new draft."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID = Field(description="The relation candidate")
    target_rule_version_id: UUID | None = Field(
        default=None,
        description=(
            "The version it targets: needed for supersedes, extends_deadline, corrects and "
            "withdraws, and for a relation that names a rule"
        ),
    )

    def to_choice(self) -> RelationChoice:
        target = self.target_rule_version_id
        return RelationChoice(
            candidate_id=self.candidate_id,
            target_rule_version_id=None if target is None else RuleVersionId(target),
        )


class DraftFromCandidateIn(BaseModel):
    """A version drafted from the task's candidate: into the rule ``rule_key`` names (its next
    version), or a new rule with that key when ``new_rule`` gives its regulator and level. The
    content is the candidate's with ``edits`` applied; the citations are the candidate's quotes
    unless ``citations`` lists the ones to cite (an empty list cites none for now); the
    relation candidates listed are approved onto the draft."""

    model_config = ConfigDict(extra="forbid")

    actor_id: UUID = Field(
        description="The analyst who claimed the task; a signed-in user's token overrides it"
    )
    rule_key: str = Field(
        min_length=1,
        max_length=MAX_RULE_KEY,
        pattern=RULE_KEY_PATTERN,
        description="The rule the version belongs to, such as gstr3b_monthly",
    )
    new_rule: NewRuleIn | None = Field(
        default=None, description="Only for a key no rule has: the new rule's regulator and level"
    )
    edits: DraftFieldsIn | None = Field(
        default=None, description="What to change in the content the candidate proposes"
    )
    citations: list[CitationIn] | None = Field(
        default=None,
        max_length=MAX_CITATIONS,
        description="The quotes to cite instead of the candidate's; every one is verified",
    )
    relation_candidates: list[RelationChoiceIn] = Field(
        default_factory=list, max_length=MAX_RELATIONS
    )
    note: str = Field(default="", max_length=MAX_NOTE, description="Why, for the audit")

    def to_citations(self) -> list[CitationInput] | None:
        if self.citations is None:
            return None
        return [citation.to_input() for citation in self.citations]


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: UUID = Field(description="Who decides; a signed-in user's token overrides it")
    decision: ReviewDecision
    note: str = Field(
        default="", max_length=MAX_NOTE, description="Why; required to return or reject"
    )
    high_impact: bool = Field(
        default=False,
        description=(
            "With approve: tag the version high impact before this approval counts, so it needs "
            "two different approvers; a tag, once set, stays"
        ),
    )
    reason: RuleRejectReason | None = Field(
        default=None,
        description="With reject, and only for a candidate task: why the candidate is rejected",
    )


class AuditEntryOut(BaseModel):
    """A row of the version's decision audit."""

    decision_id: UUID
    action: DecisionAction
    from_status: RuleVersionStatus
    to_status: RuleVersionStatus
    actor_id: UUID | None
    caused_by_rule_version_id: UUID | None
    note: str
    decided_at: datetime

    @classmethod
    def from_decision(cls, decision: RuleVersionDecision) -> Self:
        return cls(
            decision_id=decision.decision_id,
            action=decision.action,
            from_status=decision.from_status,
            to_status=decision.to_status,
            actor_id=None if decision.actor_id is None else decision.actor_id.value,
            caused_by_rule_version_id=None
            if decision.caused_by is None
            else decision.caused_by.value,
            note=decision.note,
            decided_at=decision.decided_at,
        )


class TaskDocumentOut(BaseModel):
    """A document the version cites: its stored clauses are at ``GET /v1/rulebook/documents/
    {document_id}``, its file at the pipeline's ``GET /v1/pipeline/documents/{document_id}/raw``."""

    document_id: UUID
    regulator: str
    doc_type: DocumentType
    external_ref: str
    title: str
    url: str
    published_at: date | None

    @classmethod
    def from_document(cls, document: StoredDocument) -> Self:
        return cls(
            document_id=document.document_id.value,
            regulator=document.regulator,
            doc_type=document.doc_type,
            external_ref=document.external_ref,
            title=document.title,
            url=document.url,
            published_at=document.published_at,
        )


class ExtractionIssueOut(BaseModel):
    code: str = Field(description="The check that failed, such as citation_quote_not_found")
    detail: str
    clause_ref: str | None


class ProposedCitationOut(BaseModel):
    clause_ref: str
    clause_id: UUID = Field(description="The id the kernel derives for the clause in the document")
    quote: str


class ProposedDraftOut(BaseModel):
    """The draft the candidate proposes, in the stored forms, before the analyst's edits: each
    field the candidate maps, null for one it does not (``problems`` says why), and its
    quotes. ``POST .../draft`` starts from it."""

    title: str | None
    summary: str | None
    specification: dict[str, Any] | None = Field(
        description="An all_of of the candidate's applies_to; null when a condition is refused"
    )
    obligation_template: dict[str, Any] | None
    recurrence: dict[str, Any] | None = Field(description="Null: a one-off duty, or a problem")
    effective_from: date | None
    effective_to: date | None
    citations: list[ProposedCitationOut]
    problems: list[str] = Field(description="Each field that does not map, and why")


class CandidateOut(BaseModel):
    """A candidate task's rule candidate: the extraction as stored, its document (its file is at
    the pipeline's ``GET /v1/pipeline/documents/{document_id}/raw``) and the draft it
    proposes."""

    candidate_id: UUID
    document_id: UUID
    document: TaskDocumentOut | None
    regulator: str
    model: str
    prompt_version: str
    confidence: float
    citation_count: int = Field(description="Quotes the pipeline verified against the clauses")
    needs_review: bool
    outcome: CandidateOutcome
    status: RuleCandidateStatus
    reject_reason: RuleRejectReason | None
    rule_version_id: UUID | None = Field(description="The version drafted from it")
    suggested_rule_key: str | None
    suggested_rule_known: bool = Field(description="Whether a rule has the suggested key")
    high_impact_suggested: bool
    high_impact_reasons: list[str]
    candidate: dict[str, Any] | None = Field(
        description="The candidate in the extraction schema's shape; null when unparseable"
    )
    issues: list[ExtractionIssueOut]
    clause_ids: list[UUID]
    doc_type: str | None
    source_key: str | None
    ontology_version: str | None
    proposed: ProposedDraftOut
    event_id: UUID = Field(description="The rule.candidate.created event it came with")
    created_at: datetime
    decided_by: UUID | None
    decided_at: datetime | None

    @classmethod
    def from_detail(cls, detail: CandidateDetail) -> Self:
        candidate = detail.candidate
        payload = candidate.payload
        source = payload.get("source")
        values = detail.proposed.values
        return cls(
            candidate_id=candidate.candidate_id,
            document_id=candidate.document_id.value,
            document=None
            if detail.document is None
            else TaskDocumentOut.from_document(detail.document),
            regulator=candidate.regulator,
            model=candidate.model,
            prompt_version=candidate.prompt_version,
            confidence=candidate.confidence,
            citation_count=candidate.citation_count,
            needs_review=candidate.needs_review,
            outcome=candidate.outcome,
            status=candidate.status,
            reject_reason=candidate.reject_reason,
            rule_version_id=None
            if candidate.rule_version_id is None
            else candidate.rule_version_id.value,
            suggested_rule_key=candidate.suggested_rule_key,
            suggested_rule_known=detail.suggested_rule_known,
            high_impact_suggested=candidate.high_impact_suggested,
            high_impact_reasons=list(detail.high_impact_reasons),
            candidate=None if candidate.fields is None else dict(candidate.fields),
            issues=[
                ExtractionIssueOut(
                    code=issue.code, detail=issue.detail, clause_ref=issue.clause_ref
                )
                for issue in candidate.issues
            ],
            clause_ids=[UUID(str(clause)) for clause in _texts(payload.get("clause_ids"))],
            doc_type=_text_or_none(payload.get("doc_type")),
            source_key=None
            if not isinstance(source, dict)
            else _text_or_none(source.get("source_key")),
            ontology_version=_text_or_none(payload.get("ontology_version")),
            proposed=ProposedDraftOut(
                title=_text_or_none(values.get("title")),
                summary=_text_or_none(values.get("summary")),
                specification=_dict_or_none(values.get("specification")),
                obligation_template=_dict_or_none(values.get("obligation_template")),
                recurrence=_dict_or_none(values.get("recurrence")),
                effective_from=_date_or_none(values.get("effective_from")),
                effective_to=_date_or_none(values.get("effective_to")),
                citations=[
                    ProposedCitationOut(
                        clause_ref=quote.clause_ref,
                        clause_id=clause_id_for(candidate.document_id, quote.clause_ref).value,
                        quote=quote.quote,
                    )
                    for quote in detail.proposed.citations
                ],
                problems=[
                    *detail.proposed.problem_list,
                    *(f"citations: {problem}" for problem in detail.proposed.citation_problems),
                ],
            ),
            event_id=candidate.event_id,
            created_at=candidate.created_at,
            decided_by=None if candidate.decided_by is None else candidate.decided_by.value,
            decided_at=candidate.decided_at,
        )


def _texts(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list | tuple) else []


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _dict_or_none(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _date_or_none(value: object) -> date | None:
    return value if isinstance(value, date) else None


class ReviewTaskDetailOut(BaseModel):
    task: ReviewTaskOut
    rule_version: RuleVersionOut | None = Field(
        description="The version the task reviews; null for a candidate task not drafted yet"
    )
    specification_described: list[str] = Field(
        description="The predicate tree as lines, two spaces deeper per level"
    )
    citations: list[CitationOut] = Field(description="With each quote's verification")
    documents: list[TaskDocumentOut] = Field(description="The documents the citations cite")
    source_url: str | None = Field(description="The link the version's source gives, if any")
    approved_by: list[UUID] = Field(description="Approvers of the version's current round")
    required_approvals: int
    decisions: list[AuditEntryOut] = Field(description="The version's decision audit")
    tasks: list[ReviewTaskOut] = Field(
        description="Every task of the version (of the candidate before drafting), oldest first"
    )
    candidate: CandidateOut | None = Field(description="A candidate task's rule candidate")

    @classmethod
    def from_detail(cls, detail: TaskDetail) -> Self:
        version = detail.version
        url = None if version is None else version.source.get("url")
        return cls(
            task=ReviewTaskOut.from_task(detail.task),
            rule_version=None
            if version is None
            else RuleVersionOut.from_record(
                version,
                closed=detail.candidate is not None
                and version_closed(version, detail.candidate.candidate),
            ),
            specification_described=list(detail.specification_described),
            citations=[CitationOut.from_record(citation) for citation in detail.citations],
            documents=[TaskDocumentOut.from_document(document) for document in detail.documents],
            source_url=url if isinstance(url, str) and url else None,
            approved_by=[approver.value for approver in detail.approvers],
            required_approvals=detail.required_approvals,
            decisions=[AuditEntryOut.from_decision(entry) for entry in detail.decisions],
            tasks=[ReviewTaskOut.from_task(task) for task in detail.tasks],
            candidate=None
            if detail.candidate is None
            else CandidateOut.from_detail(detail.candidate),
        )


class TaskDecisionOut(BaseModel):
    task: ReviewTaskOut = Field(
        description="Decided, or open again when the round needs another approver"
    )
    version: LifecycleOut | None = Field(
        description="The version after the decision; null for a candidate rejected before drafting"
    )
    next_task_id: UUID | None = Field(description="The task a return opened for the rework")
    candidate_status: RuleCandidateStatus | None = Field(
        description="A candidate task's candidate after the decision"
    )
    events: list[EventOut] = Field(
        description="Events the decision wrote to the outbox: rule.rejected for a candidate"
    )

    @classmethod
    def from_decision(cls, decision: TaskDecision) -> Self:
        return cls(
            task=ReviewTaskOut.from_task(decision.task),
            version=None if decision.version is None else LifecycleOut.from_state(decision.version),
            next_task_id=None if decision.next_task is None else decision.next_task.task_id,
            candidate_status=None if decision.candidate is None else decision.candidate.status,
            events=[EventOut.from_event(event) for event in decision.events],
        )


class StatusCountsOut(BaseModel):
    open: int
    claimed: int
    decided: int


class RegulatorCountsOut(StatusCountsOut):
    regulator: str


class DecisionCountsOut(BaseModel):
    """The decided tasks by their decision."""

    approved: int
    returned: int
    rejected: int


class CandidateCountsOut(BaseModel):
    """The rule candidates analysts decided. ``acceptance_rate`` is the share of them approved
    without edits (ADR-006's measure of the extraction); null while none is decided."""

    decided: int
    approved: int
    approved_without_edits: int = Field(
        description="Approved with no edit recorded on the version drafted from them"
    )
    rejected: int
    acceptance_rate: float | None


class ReviewStatsOut(BaseModel):
    by_status: StatusCountsOut
    by_regulator: list[RegulatorCountsOut]
    decisions: DecisionCountsOut
    median_seconds_to_decide: float | None = Field(
        description="From a task's opening to its decision, over every decided task"
    )
    oldest_open_at: datetime | None = Field(description="The oldest task not decided yet")
    oldest_open_age_seconds: float = Field(description="Its age now; 0 when none waits")
    candidates: CandidateCountsOut

    @classmethod
    def from_stats(cls, stats: ReviewTaskStats, now: datetime) -> Self:
        counts = stats.counts()
        decisions = stats.decision_counts()
        candidates = stats.candidates
        return cls(
            by_status=StatusCountsOut(
                open=counts[ReviewTaskStatus.OPEN],
                claimed=counts[ReviewTaskStatus.CLAIMED],
                decided=counts[ReviewTaskStatus.DECIDED],
            ),
            by_regulator=[
                RegulatorCountsOut(
                    regulator=row.regulator, open=row.open, claimed=row.claimed, decided=row.decided
                )
                for row in stats.by_regulator
            ],
            decisions=DecisionCountsOut(
                approved=decisions[ReviewDecision.APPROVE],
                returned=decisions[ReviewDecision.RETURN],
                rejected=decisions[ReviewDecision.REJECT],
            ),
            median_seconds_to_decide=stats.median_seconds_to_decide,
            oldest_open_at=stats.oldest_open_at,
            oldest_open_age_seconds=stats.oldest_open_age_seconds(now),
            candidates=CandidateCountsOut(
                decided=candidates.decided,
                approved=candidates.approved,
                approved_without_edits=candidates.approved_without_edits,
                rejected=candidates.rejected,
                acceptance_rate=candidates.acceptance_rate,
            ),
        )
