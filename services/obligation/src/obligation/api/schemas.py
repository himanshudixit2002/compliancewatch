"""Response bodies of the obligation API."""

from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel

from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.domain.model import Obligation


class ObligationOut(BaseModel):
    """One obligation: due_at is the end of the due day in India, given in UTC. The period is
    half-open (period_end is the day after its last day), and null for a rule that does not
    recur."""

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

    @classmethod
    def from_obligation(cls, obligation: Obligation) -> "ObligationOut":
        period = obligation.period
        return cls(
            obligation_id=obligation.id.value,
            business_id=obligation.business_id.value,
            rule_version_id=obligation.rule_version_id.value,
            decision_id=obligation.decision_id.value,
            title=obligation.title,
            steps=list(obligation.steps),
            evidence_type=obligation.evidence_type,
            period_label=None if period is None else period.label,
            period_start=None if period is None else period.start,
            period_end=None if period is None else period.end,
            due_at=_utc(obligation.due_at),
            status=obligation.status,
            closed_at=_utc(obligation.closed_at),
            closed_reason=obligation.closed_reason,
        )


def _utc(instant: datetime | None) -> datetime | None:
    return None if instant is None else instant.astimezone(UTC)
