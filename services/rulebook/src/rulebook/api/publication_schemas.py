"""Request and response bodies of the citation, review and publish routes."""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain_kernel.ids import ClauseId
from domain_kernel.knowledge import RelationKind
from domain_kernel.status import RuleVersionStatus
from rulebook.api.read_schemas import CitationOut
from rulebook.application.publication import (
    MAX_CITATIONS,
    CitationInput,
    CitationReport,
    Publication,
    SweepReport,
    VersionState,
)
from rulebook.domain.events import RuleEvent
from rulebook.domain.seed import SeedStatus


class CitationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: UUID
    quote: str = Field(
        min_length=1, max_length=400, description="Verbatim text of the clause the rule rests on"
    )

    def to_input(self) -> CitationInput:
        return CitationInput(clause_id=ClauseId(self.clause_id), quote=self.quote)


class CitationsIn(BaseModel):
    """Clauses the version cites. Every quote must be in its clause or nothing is stored."""

    model_config = ConfigDict(extra="forbid")

    citations: list[CitationIn] = Field(min_length=1, max_length=MAX_CITATIONS)


class CitationsOut(BaseModel):
    added: int
    unchanged: int
    citations: list[CitationOut] = Field(description="Every citation of the version now")

    @classmethod
    def from_report(cls, report: CitationReport) -> Self:
        return cls(
            added=report.added,
            unchanged=report.unchanged,
            citations=[CitationOut.from_record(citation) for citation in report.citations],
        )


class ActorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: UUID = Field(
        description="The analyst taking the step; a signed-in user's token overrides it"
    )
    note: str = Field(default="", max_length=2_000)


class SubmitIn(ActorIn):
    high_impact: bool = Field(
        default=False,
        description="Needs two different approvers; once set, a later submission keeps it",
    )


class EventOut(BaseModel):
    event_id: UUID
    topic: str
    correlation_id: UUID
    causation_id: UUID | None

    @classmethod
    def from_event(cls, event: RuleEvent) -> Self:
        return cls(
            event_id=event.event_id.value,
            topic=type(event).topic,
            correlation_id=event.correlation_id.value,
            causation_id=None if event.causation_id is None else event.causation_id.value,
        )


class LifecycleOut(BaseModel):
    rule_version_id: UUID
    rule_id: UUID
    version: int
    status: RuleVersionStatus
    seed_status: SeedStatus
    high_impact: bool
    effective_from: date
    effective_to: date | None
    submitted_at: datetime | None = Field(description="Start of the current review round")
    published_at: datetime | None
    approved_by: list[UUID] = Field(description="Approvers of the current review round")
    required_approvals: int
    events: list[EventOut] = Field(description="Events this step wrote to the outbox")

    @classmethod
    def from_state(cls, state: VersionState) -> Self:
        record = state.record
        return cls(
            rule_version_id=record.rule_version_id.value,
            rule_id=record.rule_id.value,
            version=record.version,
            status=record.status,
            seed_status=record.seed_status,
            high_impact=record.high_impact,
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            submitted_at=record.submitted_at,
            published_at=record.published_at,
            approved_by=[approver.value for approver in state.approvers],
            required_approvals=state.required_approvals,
            events=[EventOut.from_event(event) for event in state.events],
        )


class ReplacementOut(BaseModel):
    rule_version_id: UUID
    relation: RelationKind
    effective_to: date | None = Field(description="The replaced version's end after the cut")
    status: RuleVersionStatus = Field(description="Its status now")
    moves_to: RuleVersionStatus
    pending: bool = Field(
        description="True until the published version takes effect; the daily sweep moves it"
    )


class DeadlineChangeOut(BaseModel):
    rule_version_id: UUID
    period_label: str | None
    new_due_on: date
    evidence_clause_id: UUID


class PublicationOut(LifecycleOut):
    correlation_id: UUID
    replacements: list[ReplacementOut]
    deadline_changes: list[DeadlineChangeOut]
    attribute_keys: list[str]

    @classmethod
    def from_publication(cls, publication: Publication) -> Self:
        plan = publication.plan
        state = VersionState(plan.published, plan.approved_by, publication.events)
        return cls(
            **LifecycleOut.from_state(state).model_dump(),
            correlation_id=publication.correlation_id.value,
            replacements=[
                ReplacementOut(
                    rule_version_id=r.target.rule_version_id.value,
                    relation=r.relation,
                    effective_to=r.effective_to,
                    status=r.updated.status,
                    moves_to=r.moves_to,
                    pending=not r.due,
                )
                for r in plan.replacements
            ],
            deadline_changes=[
                DeadlineChangeOut(
                    rule_version_id=change.target.rule_version_id.value,
                    period_label=change.period_label,
                    new_due_on=change.new_due_on,
                    evidence_clause_id=change.evidence_clause_id.value,
                )
                for change in plan.deadline_changes
            ],
            attribute_keys=list(plan.attribute_keys),
        )


class TransitionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date | None = Field(
        default=None, description="Day to sweep up to; today in India when empty, never later"
    )


class TransitionOut(BaseModel):
    rule_version_id: UUID
    rule_id: UUID
    status: RuleVersionStatus
    caused_by_rule_version_id: UUID
    effective_from: date


class TransitionsOut(BaseModel):
    as_of: date
    transitions: list[TransitionOut]
    events: list[EventOut]

    @classmethod
    def from_report(cls, report: SweepReport) -> Self:
        return cls(
            as_of=report.as_of,
            transitions=[
                TransitionOut(
                    rule_version_id=t.target_id.value,
                    rule_id=t.target_rule_id.value,
                    status=t.moves_to,
                    caused_by_rule_version_id=t.replacing_id.value,
                    effective_from=t.replacing_from,
                )
                for t in report.transitions
            ],
            events=[EventOut.from_event(event) for event in report.events],
        )
