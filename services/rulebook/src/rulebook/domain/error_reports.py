"""Error reports as the rulebook reviews them: what a tenant's member said is wrong with an
obligation, masked, waiting for the regulatory team's decision.

The obligation service emits ``error_report.submitted`` with the description masked for personal
identifiers; the rulebook keeps that text and nothing else of the tenant's (``ErrorReview``, one
per report, keyed by the report so a redelivered event changes nothing). An analyst, reviewer or
admin decides it once (``decide``): ``confirmed`` names the rule version that corrects the
reported one, which the application checks has a ``corrects`` relation to it, and its publication
replaces the reported version through the publish lifecycle; ``rejected`` leaves the version as
it is. The decision goes back to the obligation service as ``error_report.decided``, keyed by the
tenant. A tenant's erasure nulls the review's tenant and empties its text; the decision stays as
a fact about the rule.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Final
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance, require_int
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import EntityId, ObligationId, RuleVersionId, TenantId, UserId, derive_id
from rulebook.domain.errors import CorrectingVersionRequiredError, ErrorReviewClosedError

MAX_DESCRIPTION_CHARS: Final = 2_000
MAX_NOTES_CHARS: Final = 2_000
MAX_PAGE: Final = 200


class ErrorCategory(StrEnum):
    """What the reporter says is wrong; the values are the contract's."""

    DUE_DATE = "due_date"
    APPLICABILITY = "applicability"
    STEPS = "steps"
    CITATION = "citation"
    OTHER = "other"


class ErrorReviewStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ErrorOutcome(StrEnum):
    """What the regulatory team decided; the values are the contract's."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"


DECIDED_STATUSES: Final = {
    ErrorOutcome.CONFIRMED: ErrorReviewStatus.CONFIRMED,
    ErrorOutcome.REJECTED: ErrorReviewStatus.REJECTED,
}


def review_id_for(report_id: UUID) -> UUID:
    """One review per report: its id derives from the report's, so a redelivered
    ``error_report.submitted`` lands on the same row."""
    return derive_id(EntityId, "error_report_review", str(report_id)).value


@dataclass(frozen=True, slots=True)
class ErrorReview:
    review_id: UUID
    report_id: UUID
    tenant_id: TenantId | None
    """The reporting tenant; None once the tenant was erased."""
    obligation_id: ObligationId
    rule_version_id: RuleVersionId
    category: ErrorCategory
    description_masked: str
    """The reporter's account as the obligation service masked it; '' once the tenant was
    erased."""
    received_at: datetime
    status: ErrorReviewStatus = ErrorReviewStatus.OPEN
    decided_by: UserId | None = None
    decided_at: datetime | None = None
    notes: str = ""
    correcting_rule_version_id: RuleVersionId | None = None

    def __post_init__(self) -> None:
        require_instance(self.review_id, UUID, "review_id")
        require_instance(self.report_id, UUID, "report_id")
        if self.tenant_id is not None:
            require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.category, ErrorCategory, "category")
        require_instance(self.description_masked, str, "description_masked")
        if len(self.description_masked) > MAX_DESCRIPTION_CHARS:
            raise InvariantViolationError(
                f"description_masked has at most {MAX_DESCRIPTION_CHARS} characters"
            )
        require_aware(self.received_at, "received_at")
        require_instance(self.status, ErrorReviewStatus, "status")
        require_instance(self.notes, str, "notes")
        if len(self.notes) > MAX_NOTES_CHARS:
            raise InvariantViolationError(f"notes have at most {MAX_NOTES_CHARS} characters")
        decided = self.status is not ErrorReviewStatus.OPEN
        if decided != (self.decided_at is not None) or decided != (self.decided_by is not None):
            raise InvariantViolationError("decided_by and decided_at are set exactly when decided")
        if self.decided_at is not None:
            require_aware(self.decided_at, "decided_at")
            require_instance(self.decided_by, UserId, "decided_by")
        if self.correcting_rule_version_id is not None:
            require_instance(
                self.correcting_rule_version_id, RuleVersionId, "correcting_rule_version_id"
            )
        if self.status is ErrorReviewStatus.CONFIRMED and self.correcting_rule_version_id is None:
            raise InvariantViolationError("a confirmed review names the version that corrects it")
        if self.status is not ErrorReviewStatus.CONFIRMED and self.correcting_rule_version_id:
            raise InvariantViolationError("only a confirmed review names a correcting version")

    @property
    def is_open(self) -> bool:
        return self.status is ErrorReviewStatus.OPEN

    def decide(
        self,
        outcome: ErrorOutcome,
        *,
        by: UserId,
        at: datetime,
        notes: str = "",
        correcting_rule_version_id: RuleVersionId | None = None,
    ) -> "ErrorReview":
        """The review decided; a decided one refuses another decision
        (``ErrorReviewClosedError``), and a confirmation without the correcting version is
        ``CorrectingVersionRequiredError``."""
        self.require_open()
        require_instance(outcome, ErrorOutcome, "outcome")
        if outcome is ErrorOutcome.CONFIRMED and correcting_rule_version_id is None:
            raise CorrectingVersionRequiredError(
                f"confirming error report {self.report_id} names the rule version that corrects "
                f"{self.rule_version_id}"
            )
        return replace(
            self,
            status=DECIDED_STATUSES[outcome],
            decided_by=by,
            decided_at=at,
            notes=notes,
            correcting_rule_version_id=correcting_rule_version_id
            if outcome is ErrorOutcome.CONFIRMED
            else None,
        )

    def erased(self) -> "ErrorReview":
        """The review once its tenant was erased: no tenant, no text; the decision stays."""
        return replace(self, tenant_id=None, description_masked="")

    def require_open(self) -> None:
        """``ErrorReviewClosedError`` unless the review is still open."""
        if not self.is_open:
            raise ErrorReviewClosedError(
                f"error report {self.report_id} was decided ({self.status.value}) and never changes"
            )


def queue_position(review: ErrorReview) -> tuple[str, datetime, UUID]:
    """Where a review stands in the queue: by the rule version it is about, then oldest first,
    then by id."""
    return (str(review.rule_version_id), review.received_at, review.review_id)


@dataclass(frozen=True, slots=True)
class ErrorReviewKey:
    """The review a page of the queue starts after."""

    rule_version_id: RuleVersionId
    received_at: datetime
    review_id: UUID

    @classmethod
    def of(cls, review: ErrorReview) -> "ErrorReviewKey":
        return cls(review.rule_version_id, review.received_at, review.review_id)

    @property
    def position(self) -> tuple[str, datetime, UUID]:
        return (str(self.rule_version_id), self.received_at, self.review_id)


@dataclass(frozen=True, slots=True)
class ErrorReviewQuery:
    """Which reviews a page holds: of ``status`` and ``rule_version_id`` when given, after
    ``after`` in queue order, at most ``limit``."""

    status: ErrorReviewStatus | None = ErrorReviewStatus.OPEN
    rule_version_id: RuleVersionId | None = None
    after: ErrorReviewKey | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        limit = require_int(self.limit, "limit", minimum=1)
        if limit > MAX_PAGE + 1:
            raise InvariantViolationError(f"a page reads at most {MAX_PAGE + 1} reviews")

    def admits(self, review: ErrorReview) -> bool:
        return (
            self.status in (None, review.status)
            and self.rule_version_id in (None, review.rule_version_id)
            and (self.after is None or queue_position(review) > self.after.position)
        )


@dataclass(frozen=True, slots=True)
class ErrorReviewGroup:
    """The open reviews of one rule version: how many, since when, and what the version is."""

    rule_version_id: RuleVersionId
    open_count: int
    oldest_received_at: datetime
    rule_key: str | None = None
    version: int | None = None
    title: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorReportDecided(DomainEvent):
    """The regulatory team's decision on a tenant's report, keyed by the tenant."""

    topic: ClassVar[str] = "error_report.decided"
    schema_version: ClassVar[str] = "1.0.0"

    report_id: UUID
    rule_version_id: RuleVersionId
    outcome: ErrorOutcome
    notes: str
    correcting_rule_version_id: RuleVersionId | None
    decided_at: datetime

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is None:
            raise InvariantViolationError("error_report.decided belongs to a tenant")
        require_instance(self.report_id, UUID, "report_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.outcome, ErrorOutcome, "outcome")
        require_instance(self.notes, str, "notes")
        if self.correcting_rule_version_id is not None:
            require_instance(
                self.correcting_rule_version_id, RuleVersionId, "correcting_rule_version_id"
            )
        require_aware(self.decided_at, "decided_at")

    @property
    def partition_key(self) -> str:
        """The tenant: the obligation service reads a tenant's decisions in order."""
        return str(self.tenant_id)
