"""Report an error in an obligation, list a tenant's reports, and record the regulatory team's
decision when it comes back (guide section 16, G06).

- ``ReportError``: a member of the tenant reports an error in one of its obligations, while the
  flag ``obligation.error_reports`` is on for the tenant (``ErrorReportsDisabledError``, 404,
  otherwise: the route does not exist for the tenant and nothing is stored). The obligation must
  be the tenant's (``ObligationNotFoundError``). In one unit of work the report is stored as the
  reporter wrote it, under row-level security; ``error_report.submitted`` goes to the outbox with
  the description masked for personal identifiers (the kernel's ``mask_pii``), since the rulebook
  every tenant shares must never hold a tenant's personal data; and an audit entry
  ``error_report.submitted`` names the report, its obligation, rule version and category, never
  the text. The rulebook's consumer turns the event into a review item.
- ``ListErrorReports``: the tenant's reports, newest first, a page at a time, of one status when
  asked.
- ``ApplyErrorDecision``: what the worker's consumer of ``error_report.decided`` (group
  ``obligation.error-decisions``) does with a decision: the report moves to ``confirmed`` (with
  the version that corrects the reported one) or ``rejected``, with the analyst's notes, and an
  audit entry ``error_report.decided`` is written in the same transaction as the consumer's
  ``processed_event`` row. A decision delivered again finds the report decided and changes nothing;
  one for a report the tenant has no row of raises ``ErrorReportNotFoundError``, so the consumer
  retries it and then dead-letters it, where an operator sees the mismatch. The correction itself
  reaches the obligations through the rule events when the correcting version is published: the
  reported version is superseded, its open obligations of the periods the correction takes over
  are closed, and the correcting version's fan-out makes them again with the right dates.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from domain_kernel.audit import AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import EventId, ObligationId, RuleVersionId, TenantId
from domain_kernel.pii import mask_pii
from obligation.application.tracking import Acting, correlation_of
from obligation.domain.error_reports import (
    MAX_DESCRIPTION_CHARS,
    MAX_NOTES_CHARS,
    ErrorCategory,
    ErrorOutcome,
    ErrorReport,
    ErrorReportId,
    ErrorReportStatus,
    ErrorReportSubmitted,
)
from obligation.domain.errors import (
    ErrorReportNotFoundError,
    ErrorReportsDisabledError,
    ObligationNotFoundError,
)
from obligation.domain.flags import ERROR_REPORTS, FeatureFlags
from obligation.domain.repository import ReportAfter, UnitOfWorkFactory
from py_common.audit import audit_actor, current_correlation_id

SUBJECT: Final = "error_report"
SUBMITTED_ACTION: Final = "error_report.submitted"
DECIDED_ACTION: Final = "error_report.decided"
SERVICE: Final = "obligation"
MAX_PAGE: Final = 200


def report_description(text: str) -> str:
    """The reporter's account, trimmed: one to ``MAX_DESCRIPTION_CHARS`` characters."""
    description = text.strip()
    if not description:
        raise InvariantViolationError("a report says what is wrong")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise InvariantViolationError(
            f"a description has at most {MAX_DESCRIPTION_CHARS} characters"
        )
    return description


@dataclass(frozen=True, slots=True)
class NewErrorReport:
    acting: Acting
    obligation_id: ObligationId
    category: ErrorCategory
    description: str


class ReportError:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        flags: FeatureFlags,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._flags = flags
        self._clock = clock

    def run(self, new: NewErrorReport) -> ErrorReport:
        acting = new.acting
        if not self._flags.enabled(ERROR_REPORTS, acting.tenant_id):
            raise ErrorReportsDisabledError()
        description = report_description(new.description)
        now = self._clock()
        with self._unit_of_work(acting.tenant_id) as uow:
            obligation = uow.obligations.get(new.obligation_id)
            if obligation is None:
                raise ObligationNotFoundError(str(new.obligation_id))
            report = ErrorReport(
                id=ErrorReportId.new(),
                tenant_id=acting.tenant_id,
                obligation_id=obligation.id,
                business_id=obligation.business_id,
                rule_version_id=obligation.rule_version_id,
                category=new.category,
                description=description,
                status=ErrorReportStatus.SUBMITTED,
                submitted_by=acting.user_id,
                submitted_at=now,
            )
            uow.error_reports.add(report)
            uow.events.publish(
                ErrorReportSubmitted(
                    tenant_id=acting.tenant_id,
                    occurred_at=now,
                    correlation_id=correlation_of(acting.correlation_id),
                    report_id=report.id,
                    obligation_id=report.obligation_id,
                    business_id=report.business_id,
                    rule_version_id=report.rule_version_id,
                    category=report.category,
                    description=mask_pii(description).text,
                    submitted_at=now,
                )
            )
            uow.audit.write(
                AuditEntry(
                    action=SUBMITTED_ACTION,
                    tenant_id=acting.tenant_id,
                    subject_type=SUBJECT,
                    subject_id=str(report.id),
                    actor=acting.actor,
                    before=None,
                    after={
                        "status": report.status.value,
                        "obligation_id": str(report.obligation_id),
                        "business_id": str(report.business_id),
                        "rule_version_id": str(report.rule_version_id),
                        "category": report.category.value,
                    },
                    occurred_at=now,
                    correlation_id=acting.correlation_id,
                )
            )
        return report


class ListErrorReports:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        tenant_id: TenantId,
        *,
        status: ErrorReportStatus | None = None,
        after: ReportAfter | None = None,
        limit: int = 50,
    ) -> Sequence[ErrorReport]:
        with self._unit_of_work(tenant_id) as uow:
            return uow.error_reports.page(
                status=status, after=after, limit=min(max(limit, 1), MAX_PAGE + 1)
            )


@dataclass(frozen=True, slots=True)
class ErrorDecision:
    """What an ``error_report.decided`` message carries."""

    event_id: EventId
    tenant_id: TenantId
    report_id: ErrorReportId
    rule_version_id: RuleVersionId
    outcome: ErrorOutcome
    notes: str
    correcting_rule_version_id: RuleVersionId | None
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionApplied:
    report: ErrorReport
    changed: bool
    """False when the report was decided already (a redelivery)."""


class ApplyErrorDecision:
    def run(self, decision: ErrorDecision, units: UnitOfWorkFactory) -> DecisionApplied:
        if len(decision.notes) > MAX_NOTES_CHARS:
            raise InvariantViolationError(f"notes have at most {MAX_NOTES_CHARS} characters")
        with units(decision.tenant_id) as uow:
            report = uow.error_reports.get(decision.report_id, lock=True)
            if report is None:
                raise ErrorReportNotFoundError(str(decision.report_id))
            if not report.is_open:
                return DecisionApplied(report, changed=False)
            decided = report.decide(
                decision.outcome,
                at=decision.decided_at,
                notes=decision.notes,
                correcting_rule_version_id=decision.correcting_rule_version_id,
            )
            uow.error_reports.save(decided)
            uow.audit.write(
                AuditEntry(
                    action=DECIDED_ACTION,
                    tenant_id=decision.tenant_id,
                    subject_type=SUBJECT,
                    subject_id=str(decided.id),
                    actor=audit_actor(SERVICE),
                    before={"status": report.status.value},
                    after={
                        "status": decided.status.value,
                        "rule_version_id": str(decided.rule_version_id),
                        "correcting_rule_version_id": None
                        if decided.correcting_rule_version_id is None
                        else str(decided.correcting_rule_version_id),
                    },
                    occurred_at=decision.decided_at,
                    correlation_id=current_correlation_id() or str(decision.event_id),
                )
            )
        return DecisionApplied(decided, changed=True)
