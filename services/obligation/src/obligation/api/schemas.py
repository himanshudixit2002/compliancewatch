"""Request and response bodies of the obligation API."""

from datetime import UTC, date, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from domain_kernel.ids import EntityId
from domain_kernel.status import ClosureReason, ObligationStatus, RuleVersionStatus
from obligation.application.export import TenantDataExport
from obligation.application.queries import ListedObligation
from obligation.application.tracking import MIN_WAIVER_CHARS, ObligationDetail, StatusAction
from obligation.domain.comments import MAX_COMMENT_CHARS, ObligationComment
from obligation.domain.history import MAX_NOTE_CHARS, ChangeKind, ObligationChange
from obligation.domain.model import Obligation
from obligation.domain.rule_versions import Citation, RuleVersionRef

REVIEWED = "reviewed"
"""The seed status of a rule an analyst checked against its source."""


class ObligationOut(BaseModel):
    """One obligation: due_at is the end of the due day in India, given in UTC. The period is
    half-open (period_end is the day after its last day), and null for a rule that does not
    recur. profile_version is the profile version of the decision that made it (null for one made
    before it was kept); assignee_id the user it is given to, or null."""

    obligation_id: UUID
    business_id: UUID
    rule_version_id: UUID
    decision_id: UUID
    title: str
    steps: list[str]
    evidence_type: str
    period_label: str | None
    period_start: date | None
    period_end: date | None
    due_at: datetime | None
    status: ObligationStatus
    closed_at: datetime | None
    closed_reason: ClosureReason | None
    profile_version: int | None
    assignee_id: UUID | None

    @classmethod
    def from_obligation(cls, obligation: Obligation) -> "ObligationOut":
        return cls.model_validate(_obligation_fields(obligation))


class RuleVersionFactsOut(BaseModel):
    """What the obligation service keeps of the rule version an obligation comes from.
    ``reviewed`` is false while the seed rule is not reviewed (``seed_status`` needs_review),
    the cue for a not-yet-reviewed notice; ``approved_by`` lists the approvers of the round it
    was published from and ``published_at`` when, the reviewed-by line."""

    rule_version_id: UUID
    rule_key: str
    title: str
    status: RuleVersionStatus
    effective_from: date
    effective_to: date | None
    seed_status: str
    reviewed: bool
    approved_by: list[UUID]
    published_at: datetime | None

    @classmethod
    def from_ref(cls, ref: RuleVersionRef) -> "RuleVersionFactsOut":
        return cls(
            rule_version_id=ref.rule_version_id.value,
            rule_key=ref.rule_key,
            title=ref.title,
            status=ref.status,
            effective_from=ref.effective_from,
            effective_to=ref.effective_to,
            seed_status=ref.seed_status,
            reviewed=ref.seed_status == REVIEWED,
            approved_by=[approver.value for approver in ref.approved_by],
            published_at=_utc(ref.published_at),
        )


class CitationOut(BaseModel):
    """A verified quote of the clause the obligation comes from."""

    citation_id: UUID
    clause_id: UUID
    document_id: UUID
    clause_ref: str
    quote: str
    match_score: float | None
    verified_at: datetime | None

    @classmethod
    def from_citation(cls, citation: Citation) -> "CitationOut":
        return cls(
            citation_id=citation.citation_id,
            clause_id=citation.clause_id,
            document_id=citation.document_id,
            clause_ref=citation.clause_ref,
            quote=citation.quote,
            match_score=citation.match_score,
            verified_at=_utc(citation.verified_at),
        )


class ChangeOut(BaseModel):
    """One change of the obligation. ``reason`` is the reschedule or closure reason ('' for the
    other kinds) and ``note`` what the person said (a waiver's reason); ``actor`` is the user who
    made the change, null when the system did or no token named the caller. A reschedule names
    both due dates, an assignment both assignees."""

    change_id: UUID
    kind: ChangeKind
    occurred_at: datetime
    status_after: ObligationStatus
    reason: str
    note: str
    previous_due_at: datetime | None
    new_due_at: datetime | None
    previous_assignee_id: UUID | None
    new_assignee_id: UUID | None
    caused_by_rule_version_id: UUID | None
    actor: UUID | None

    @classmethod
    def from_change(cls, change: ObligationChange) -> "ChangeOut":
        return cls(
            change_id=change.id.value,
            kind=change.kind,
            occurred_at=change.occurred_at.astimezone(UTC),
            status_after=change.status_after,
            reason=change.reason,
            note=change.note,
            previous_due_at=_utc(change.previous_due_at),
            new_due_at=_utc(change.new_due_at),
            previous_assignee_id=_uuid(change.previous_assignee_id),
            new_assignee_id=_uuid(change.new_assignee_id),
            caused_by_rule_version_id=_uuid(change.caused_by_rule_version_id),
            actor=_uuid(change.actor),
        )


class CommentOut(BaseModel):
    """One comment. ``author_id`` is the user who wrote it, null when no token named the caller;
    ``author_label`` the author as the audit log labels them (the user's roles, or
    ``system:obligation``), never a name."""

    comment_id: UUID
    obligation_id: UUID
    author_id: UUID | None
    author_label: str
    body: str
    created_at: datetime

    @classmethod
    def from_comment(cls, comment: ObligationComment) -> "CommentOut":
        return cls(
            comment_id=comment.id.value,
            obligation_id=comment.obligation_id.value,
            author_id=_uuid(comment.author_id),
            author_label=comment.author_label,
            body=comment.body,
            created_at=comment.created_at.astimezone(UTC),
        )


class ObligationDetailOut(ObligationOut):
    """One obligation with what its page shows: the facts of its rule version (null when the
    rulebook has no such version), the verified citations of the clause it comes from, its
    history, oldest first, and its comments, oldest first."""

    rule_version: RuleVersionFactsOut | None
    citations: list[CitationOut]
    history: list[ChangeOut]
    comments: list[CommentOut]

    @classmethod
    def from_detail(cls, detail: ObligationDetail) -> "ObligationDetailOut":
        ref = detail.ref
        return cls.model_validate(
            {
                **_obligation_fields(detail.obligation),
                "rule_version": None if ref is None else RuleVersionFactsOut.from_ref(ref),
                "citations": []
                if ref is None
                else [CitationOut.from_citation(citation) for citation in ref.citations],
                "history": [ChangeOut.from_change(change) for change in detail.history],
                "comments": [CommentOut.from_comment(comment) for comment in detail.comments],
            }
        )


class BusinessObligationOut(ObligationOut):
    """One obligation of the business's list, with the facts of its rule version and the
    verified citations of its clause, as the detail shows them: ``rule_version`` is null, and
    ``citations`` empty, for a version the service has not kept yet (the detail then reads it
    from the rulebook). The detail adds the history and the comments."""

    rule_version: RuleVersionFactsOut | None
    citations: list[CitationOut]

    @classmethod
    def from_listed(cls, listed: ListedObligation) -> "BusinessObligationOut":
        ref = listed.ref
        return cls.model_validate(
            {
                **_obligation_fields(listed.obligation),
                "rule_version": None if ref is None else RuleVersionFactsOut.from_ref(ref),
                "citations": []
                if ref is None
                else [CitationOut.from_citation(citation) for citation in ref.citations],
            }
        )


class BusinessObligationCursor(BaseModel):
    """Where a page of a business's obligations ends: the due date (null for none) and the id
    of the last one on it."""

    due_at: AwareDatetime | None
    id: UUID


Note = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_NOTE_CHARS),
    Field(description="Why, if you say; required for a waiver; kept in the history and the audit"),
]


class StatusIn(BaseModel):
    """``start`` moves an open obligation to in progress; ``complete`` closes it as done;
    ``waive`` closes it as waived and needs a ``reason`` of at least ten characters."""

    model_config = ConfigDict(extra="forbid")

    action: StatusAction
    reason: Note = ""

    @model_validator(mode="after")
    def _a_waiver_says_why(self) -> Self:
        if self.action is StatusAction.WAIVE and len(self.reason) < MIN_WAIVER_CHARS:
            raise ValueError(f"a waiver needs a reason of at least {MIN_WAIVER_CHARS} characters")
        return self


class AssigneeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: Annotated[
        UUID | None,
        Field(description="The user of the tenant to give the obligation to; null for nobody"),
    ]


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_COMMENT_CHARS),
        Field(description=f"The comment, 1 to {MAX_COMMENT_CHARS} characters once trimmed"),
    ]


class DataExportOut(BaseModel):
    """The obligation service's part of a tenant's data export. ``sections`` holds every section,
    an empty list when the tenant has nothing in it: ``obligations`` (every obligation, in any
    status), ``changes`` (the change log of each) and ``comments``, each oldest first and then by
    id. Rows carry the fields of the records under their own names, ids as strings, instants and
    days in ISO 8601, enums as their values."""

    service: str
    tenant_id: UUID
    generated_at: AwareDatetime
    sections: dict[str, list[dict[str, Any]]]

    @classmethod
    def from_export(cls, export: TenantDataExport) -> "DataExportOut":
        return cls(
            service=export.service,
            tenant_id=export.tenant_id.value,
            generated_at=export.generated_at.astimezone(UTC),
            sections={name: [dict(row) for row in rows] for name, rows in export.sections.items()},
        )


def _obligation_fields(obligation: Obligation) -> dict[str, Any]:
    period = obligation.period
    return {
        "obligation_id": obligation.id.value,
        "business_id": obligation.business_id.value,
        "rule_version_id": obligation.rule_version_id.value,
        "decision_id": obligation.decision_id.value,
        "title": obligation.title,
        "steps": list(obligation.steps),
        "evidence_type": obligation.evidence_type,
        "period_label": None if period is None else period.label,
        "period_start": None if period is None else period.start,
        "period_end": None if period is None else period.end,
        "due_at": _utc(obligation.due_at),
        "status": obligation.status,
        "closed_at": _utc(obligation.closed_at),
        "closed_reason": obligation.closed_reason,
        "profile_version": obligation.profile_version,
        "assignee_id": _uuid(obligation.assignee_id),
    }


def _utc(instant: datetime | None) -> datetime | None:
    return None if instant is None else instant.astimezone(UTC)


def _uuid(value: EntityId | None) -> UUID | None:
    return None if value is None else value.value
