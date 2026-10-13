"""Tenants' error reports in the rulebook: take them in, list them for the regulatory team,
decide them, and answer the obligation service.

- ``IntakeErrorReport``: what the worker's consumer of ``error_report.submitted`` (group
  ``rulebook.error-reports``) does with a report: one ``ErrorReview`` per report, its id derived
  from the report's (``error_reports.review_id_for``), so a redelivered or replayed event finds the
  row and changes nothing. The payload is checked against its contract first; one the contract
  refuses raises, so the consumer retries it and then dead-letters it. The description arrives
  masked (the obligation service masks it with the kernel before it emits the event) and is kept
  as it arrived.
- ``ListErrorReviews``: the queue, by the rule version a report is about, then oldest first, a
  page at a time, open reviews unless another status is asked for; ``groups`` counts the open
  reviews per rule version with the version's rule, number and title, so an analyst sees which
  version draws the reports.
- ``DecideErrorReview``: an analyst, reviewer or admin (``api.deps``) decides a report once.
  ``confirmed`` names the rule version that corrects the reported one, which must exist and have a
  ``corrects`` relation to it, published or not (``CorrectingVersionRequiredError``, 422,
  otherwise): publishing that version through the lifecycle replaces the reported version, and
  the obligation service closes the obligations the correction takes over and makes them again
  from the correcting version. ``rejected`` leaves the version as it is. The decision writes
  ``error_report.decided`` to the outbox, keyed by the reporting tenant, and an audit entry
  ``error_report_review.decided`` (a platform row, the report id as the subject), in one
  transaction. A report of a tenant that was erased since is decided for the record and emits
  nothing: there is no tenant to tell.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from cw_contracts.events.error_report_submitted_v1 import ErrorReportSubmittedV1
from domain_kernel.ids import ObligationId, RuleVersionId, TenantId, UserId
from domain_kernel.knowledge import RelationKind
from rulebook.application.alignment import Clock, default_clock
from rulebook.application.audit import actor_for, entry
from rulebook.domain.error_reports import (
    MAX_PAGE,
    ErrorCategory,
    ErrorOutcome,
    ErrorReportDecided,
    ErrorReview,
    ErrorReviewGroup,
    ErrorReviewKey,
    ErrorReviewQuery,
    ErrorReviewStatus,
    review_id_for,
)
from rulebook.domain.errors import (
    CorrectingVersionRequiredError,
    ErrorReviewNotFoundError,
    UnknownRuleVersionError,
)
from rulebook.domain.graph import RelationQuery
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory

SUBJECT: Final = "error_report"
DECIDED_ACTION: Final = "error_report_review.decided"


@dataclass(frozen=True, slots=True)
class Intake:
    review: ErrorReview
    created: bool
    """False when the report was taken in before (a redelivery)."""


class IntakeErrorReport:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, tenant_id: TenantId, payload: Mapping[str, object]) -> Intake:
        """The report ``payload`` (an ``error_report.submitted`` payload, checked against its
        contract) as the review of ``tenant_id``'s report."""
        report = ErrorReportSubmittedV1.model_validate(payload)
        review = ErrorReview(
            review_id=review_id_for(report.report_id),
            report_id=report.report_id,
            tenant_id=tenant_id,
            obligation_id=ObligationId(report.obligation_id),
            rule_version_id=RuleVersionId(report.rule_version_id),
            category=ErrorCategory(report.category.value),
            description_masked=report.description,
            received_at=self._clock(),
        )
        with self._unit_of_work() as uow:
            if uow.rules.version_status(review.rule_version_id) is None:
                raise UnknownRuleVersionError(str(review.rule_version_id))
            created = uow.error_reviews.add(review)
            stored = review if created else uow.error_reviews.by_report(report.report_id)
        assert stored is not None, "a review not inserted now exists already"
        return Intake(stored, created)


class ListErrorReviews:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        *,
        status: ErrorReviewStatus | None = ErrorReviewStatus.OPEN,
        rule_version_id: RuleVersionId | None = None,
        after: ErrorReviewKey | None = None,
        limit: int = 50,
    ) -> Sequence[ErrorReview]:
        query = ErrorReviewQuery(
            status=status,
            rule_version_id=rule_version_id,
            after=after,
            limit=min(max(limit, 1), MAX_PAGE + 1),
        )
        with self._unit_of_work() as uow:
            return uow.error_reviews.page(query)

    def groups(self) -> Sequence[ErrorReviewGroup]:
        """The open reviews per rule version."""
        with self._unit_of_work() as uow:
            return uow.error_reviews.open_groups()


class DecideErrorReview:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        report_id: UUID,
        outcome: ErrorOutcome,
        *,
        by: UserId,
        notes: str = "",
        correcting_rule_version_id: RuleVersionId | None = None,
    ) -> ErrorReview:
        now = self._clock()
        with self._unit_of_work() as uow:
            review = uow.error_reviews.lock_by_report(report_id)
            if review is None:
                raise ErrorReviewNotFoundError(str(report_id))
            review.require_open()
            correcting = None
            if outcome is ErrorOutcome.CONFIRMED:
                correcting = _correcting_version(uow, review, correcting_rule_version_id)
            decided = review.decide(
                outcome, by=by, at=now, notes=notes, correcting_rule_version_id=correcting
            )
            uow.error_reviews.save(decided)
            if decided.tenant_id is not None:
                uow.events.publish(
                    ErrorReportDecided(
                        tenant_id=decided.tenant_id,
                        occurred_at=now,
                        report_id=decided.report_id,
                        rule_version_id=decided.rule_version_id,
                        outcome=outcome,
                        notes=decided.notes,
                        correcting_rule_version_id=decided.correcting_rule_version_id,
                        decided_at=now,
                    )
                )
            uow.audit.write(
                entry(
                    DECIDED_ACTION,
                    SUBJECT,
                    decided.report_id,
                    actor_for(by),
                    at=now,
                    before={"status": review.status.value},
                    after={
                        "status": decided.status.value,
                        "rule_version_id": str(decided.rule_version_id),
                        "correcting_rule_version_id": None
                        if decided.correcting_rule_version_id is None
                        else str(decided.correcting_rule_version_id),
                        "tenant_erased": decided.tenant_id is None,
                    },
                    reason=notes,
                )
            )
        return decided


def _correcting_version(
    uow: KnowledgeUnitOfWork, review: ErrorReview, correcting: RuleVersionId | None
) -> RuleVersionId:
    """The version that corrects the reported one: named, stored, and related to it with
    ``corrects``, published or not."""
    if correcting is None:
        raise CorrectingVersionRequiredError(
            f"confirming error report {review.report_id} names the rule version that corrects "
            f"{review.rule_version_id}"
        )
    if uow.rules.version_status(correcting) is None:
        raise UnknownRuleVersionError(str(correcting))
    related = uow.relations.find(
        RelationQuery(
            from_rule_version_id=correcting,
            to_rule_version_id=review.rule_version_id,
            relation=RelationKind.CORRECTS,
            published_only=False,
            limit=1,
        )
    )
    if not related:
        raise CorrectingVersionRequiredError(
            f"rule version {correcting} has no corrects relation to {review.rule_version_id}: "
            "approve one onto it first, or name the version that carries it"
        )
    return correcting
