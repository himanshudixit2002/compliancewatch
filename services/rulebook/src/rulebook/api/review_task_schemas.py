"""Request and response bodies of the review task routes."""

from datetime import date, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domain_kernel.documents import DocumentType
from domain_kernel.status import RuleVersionStatus
from rulebook.api.publication_schemas import CitationIn, LifecycleOut
from rulebook.api.read_schemas import CitationOut, RuleVersionOut
from rulebook.application.publication import MAX_CITATIONS, CitationInput
from rulebook.application.review_tasks import TaskDecision, TaskDetail
from rulebook.domain.documents import StoredDocument
from rulebook.domain.publication import DecisionAction, RuleVersionDecision, required_approvals
from rulebook.domain.review_tasks import (
    EDITABLE_FIELDS,
    MAX_NOTE,
    MAX_QUESTION,
    MAX_SUMMARY,
    MAX_TITLE,
    MAX_TODO,
    DraftEdit,
    QueuedTask,
    ReviewDecision,
    ReviewTask,
    ReviewTaskKind,
    ReviewTaskStats,
    ReviewTaskStatus,
    TaskKey,
)


class ReviewTaskOut(BaseModel):
    task_id: UUID
    rule_version_id: UUID
    kind: ReviewTaskKind = Field(description="seed: a draft the seed calendar wrote")
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
            rule_version_id=task.rule_version_id.value,
            kind=task.kind,
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


class QueuedTaskOut(ReviewTaskOut):
    rule_key: str
    version: int
    title: str
    version_status: RuleVersionStatus
    high_impact: bool
    approvals: int = Field(description="Distinct approvers of the version's current review round")
    required_approvals: int = Field(description="One, or two different ones when high impact")

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


class DraftEditIn(BaseModel):
    """The fields to change, each one optional: a field left out keeps its value, and null
    clears ``recurrence`` or ``effective_to``. ``citations`` are added, never removed, and every
    quote must be in its clause. At least one field or one citation."""

    model_config = ConfigDict(extra="forbid")

    actor_id: UUID = Field(
        description="The analyst who claimed the task; a signed-in user's token overrides it"
    )
    note: str = Field(default="", max_length=MAX_NOTE, description="Why, for the audit")
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
    citations: list[CitationIn] | None = Field(default=None, min_length=1, max_length=MAX_CITATIONS)

    def to_edit(self) -> DraftEdit | None:
        sent = [name for name in EDITABLE_FIELDS if name in self.model_fields_set]
        if not sent:
            return None
        return DraftEdit({name: getattr(self, name) for name in sent})

    def to_citations(self) -> list[CitationInput]:
        return [citation.to_input() for citation in self.citations or ()]


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


class ReviewTaskDetailOut(BaseModel):
    task: ReviewTaskOut
    rule_version: RuleVersionOut
    specification_described: list[str] = Field(
        description="The predicate tree as lines, two spaces deeper per level"
    )
    citations: list[CitationOut] = Field(description="With each quote's verification")
    documents: list[TaskDocumentOut] = Field(description="The documents the citations cite")
    source_url: str | None = Field(description="The link the seed calendar gives, if any")
    approved_by: list[UUID] = Field(description="Approvers of the version's current round")
    required_approvals: int
    decisions: list[AuditEntryOut] = Field(description="The version's decision audit")
    tasks: list[ReviewTaskOut] = Field(description="Every task of the version, oldest first")

    @classmethod
    def from_detail(cls, detail: TaskDetail) -> Self:
        url = detail.version.source.get("url")
        return cls(
            task=ReviewTaskOut.from_task(detail.task),
            rule_version=RuleVersionOut.from_record(detail.version),
            specification_described=list(detail.specification_described),
            citations=[CitationOut.from_record(citation) for citation in detail.citations],
            documents=[TaskDocumentOut.from_document(document) for document in detail.documents],
            source_url=url if isinstance(url, str) and url else None,
            approved_by=[approver.value for approver in detail.approvers],
            required_approvals=detail.required_approvals,
            decisions=[AuditEntryOut.from_decision(entry) for entry in detail.decisions],
            tasks=[ReviewTaskOut.from_task(task) for task in detail.tasks],
        )


class TaskDecisionOut(BaseModel):
    task: ReviewTaskOut = Field(
        description="Decided, or open again when the round needs another approver"
    )
    version: LifecycleOut
    next_task_id: UUID | None = Field(description="The task a return opened for the rework")

    @classmethod
    def from_decision(cls, decision: TaskDecision) -> Self:
        return cls(
            task=ReviewTaskOut.from_task(decision.task),
            version=LifecycleOut.from_state(decision.version),
            next_task_id=None if decision.next_task is None else decision.next_task.task_id,
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


class ReviewStatsOut(BaseModel):
    by_status: StatusCountsOut
    by_regulator: list[RegulatorCountsOut]
    decisions: DecisionCountsOut
    median_seconds_to_decide: float | None = Field(
        description="From a task's opening to its decision, over every decided task"
    )
    oldest_open_at: datetime | None = Field(description="The oldest task not decided yet")
    oldest_open_age_seconds: float = Field(description="Its age now; 0 when none waits")

    @classmethod
    def from_stats(cls, stats: ReviewTaskStats, now: datetime) -> Self:
        counts = stats.counts()
        decisions = stats.decision_counts()
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
        )
