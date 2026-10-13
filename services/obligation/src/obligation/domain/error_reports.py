"""An error a tenant's member reported in one of its obligations, and the regulatory team's
decision about it.

A report names an obligation of the tenant, what kind of error it is (``ErrorCategory``) and the
reporter's account, kept as they wrote it (``description``, one to ``MAX_DESCRIPTION_CHARS``
characters) under row-level security. The rulebook, which every tenant shares, gets the account
masked for personal identifiers (``ErrorReportSubmitted``, the kernel's ``mask_pii_in``, cut to
the same limit) and never the raw text. A report is ``submitted`` until the regulatory team
decides it: ``confirmed``, with the rule version that corrects the reported one, or ``rejected``
with the analyst's notes; a decided report never changes again (``decide`` refuses a second
decision).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Final

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, EntityId, ObligationId, RuleVersionId, TenantId, UserId
from obligation.domain.errors import ErrorReportDecidedError

MAX_DESCRIPTION_CHARS: Final = 2_000
MAX_NOTES_CHARS: Final = 2_000


class ErrorCategory(StrEnum):
    """What the reporter says is wrong; the values are the contract's."""

    DUE_DATE = "due_date"
    APPLICABILITY = "applicability"
    STEPS = "steps"
    CITATION = "citation"
    OTHER = "other"


class ErrorReportStatus(StrEnum):
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ErrorOutcome(StrEnum):
    """What the regulatory team decided; the values are the contract's."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"


DECIDED_STATUSES: Final = {
    ErrorOutcome.CONFIRMED: ErrorReportStatus.CONFIRMED,
    ErrorOutcome.REJECTED: ErrorReportStatus.REJECTED,
}


@dataclass(frozen=True, slots=True)
class ErrorReportId(EntityId):
    """One error report."""


@dataclass(frozen=True, slots=True)
class ErrorReport:
    id: ErrorReportId
    tenant_id: TenantId
    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    category: ErrorCategory
    description: str
    """The reporter's account as they wrote it; it leaves the service masked."""
    status: ErrorReportStatus
    submitted_by: UserId | None
    """The user a verified token named; None when no token named the reporter."""
    submitted_at: datetime
    decided_at: datetime | None = None
    notes: str = ""
    """What the analyst said about the decision."""
    correcting_rule_version_id: RuleVersionId | None = None
    """For a confirmed report, the rule version that corrects the reported one."""

    def __post_init__(self) -> None:
        require_instance(self.id, ErrorReportId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.category, ErrorCategory, "category")
        _bounded(
            require_text(self.description, "description"), MAX_DESCRIPTION_CHARS, "description"
        )
        require_instance(self.status, ErrorReportStatus, "status")
        if self.submitted_by is not None:
            require_instance(self.submitted_by, UserId, "submitted_by")
        require_aware(self.submitted_at, "submitted_at")
        _bounded(require_instance(self.notes, str, "notes"), MAX_NOTES_CHARS, "notes")
        decided = self.status is not ErrorReportStatus.SUBMITTED
        if decided != (self.decided_at is not None):
            raise InvariantViolationError("decided_at is set exactly when the report is decided")
        if self.decided_at is not None:
            require_aware(self.decided_at, "decided_at")
        if self.correcting_rule_version_id is not None:
            require_instance(
                self.correcting_rule_version_id, RuleVersionId, "correcting_rule_version_id"
            )
        if self.status is ErrorReportStatus.CONFIRMED and self.correcting_rule_version_id is None:
            raise InvariantViolationError("a confirmed report names the version that corrects it")
        if self.status is not ErrorReportStatus.CONFIRMED and self.correcting_rule_version_id:
            raise InvariantViolationError("only a confirmed report names a correcting version")

    @property
    def is_open(self) -> bool:
        return self.status is ErrorReportStatus.SUBMITTED

    def decide(
        self,
        outcome: ErrorOutcome,
        *,
        at: datetime,
        notes: str = "",
        correcting_rule_version_id: RuleVersionId | None = None,
    ) -> "ErrorReport":
        """The report as the regulatory team decided it; a decided report refuses another
        decision (``ErrorReportDecidedError``)."""
        if not self.is_open:
            raise ErrorReportDecidedError(str(self.id), self.status.value)
        require_instance(outcome, ErrorOutcome, "outcome")
        return replace(
            self,
            status=DECIDED_STATUSES[outcome],
            decided_at=require_aware(at, "at"),
            notes=notes,
            correcting_rule_version_id=correcting_rule_version_id,
        )


def _bounded(text: str, limit: int, name: str) -> str:
    if len(text) > limit:
        raise InvariantViolationError(f"{name} has at most {limit} characters, got {len(text)}")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorReportSubmitted(DomainEvent):
    """A report left the obligation service for the rulebook, its description masked."""

    topic: ClassVar[str] = "error_report.submitted"
    schema_version: ClassVar[str] = "1.0.0"

    report_id: ErrorReportId
    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    category: ErrorCategory
    description: str
    submitted_at: datetime

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is None:
            raise InvariantViolationError("error_report.submitted belongs to a tenant")
        require_instance(self.report_id, ErrorReportId, "report_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.category, ErrorCategory, "category")
        _bounded(
            require_text(self.description, "description"), MAX_DESCRIPTION_CHARS, "description"
        )
        require_aware(self.submitted_at, "submitted_at")
