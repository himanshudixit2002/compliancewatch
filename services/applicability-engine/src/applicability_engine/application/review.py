"""The review queue: keeping items in step with the decisions, listing them, resolving one.

``track_review`` runs in the unit of work that stores a decision, so an item opens, follows or
is settled in the same transaction as the decision behind it (``domain.review`` has the rule).
``ListReviewItems`` reads a tenant's items oldest first with the decision each one is about.
``ResolveReviewItem`` settles an open item for a reviewer: ``applies`` and ``not_applicable``
append a decision with trigger ``review``, made from the decision under review (its predicates,
profile version and year) with the reviewer's result and confidence 1, and publish its
``applicability.decided``; ``dismiss`` appends nothing. The item is held while it is resolved,
so two reviewers cannot both settle it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from applicability_engine.domain.errors import ReviewItemNotFoundError, ReviewItemResolvedError
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.model import Decision, Trigger, decision_id_for
from applicability_engine.domain.repository import UnitOfWork, UnitOfWorkFactory
from applicability_engine.domain.review import (
    Resolution,
    ReviewItem,
    ReviewItemId,
    ReviewItemKey,
    ReviewStatus,
    review_reason,
)
from domain_kernel.confidence import CERTAIN
from domain_kernel.events import utc_now
from domain_kernel.ids import DecisionId, TenantId, UserId

MAX_ITEMS = 201
"""The most one read returns: the longest page and the row that tells there is another."""


class ReviewChange(StrEnum):
    OPENED = "opened"
    FOLLOWED = "followed"
    SETTLED = "settled"


def track_review(uow: UnitOfWork, decision: Decision, *, at: datetime) -> ReviewChange | None:
    """Open, move or settle the review item of ``decision``'s business and rule version in the
    unit of work that stores the decision; what changed, or None."""
    current = uow.reviews.open_for(decision.business_id, decision.rule_version_id)
    reason = review_reason(decision)
    if reason is not None:
        if current is None:
            uow.reviews.add(ReviewItem.open(decision, reason))
            return ReviewChange.OPENED
        if current.decision_id != decision.decision_id:
            uow.reviews.save(current.follow(decision, reason))
            return ReviewChange.FOLLOWED
        return None
    if current is not None and not decision.needs_review:
        uow.reviews.save(current.settled_by(decision, at=at))
        return ReviewChange.SETTLED
    return None


@dataclass(frozen=True, slots=True)
class ReviewEntry:
    """An item with the decision it is about."""

    item: ReviewItem
    decision: Decision


@dataclass(frozen=True, slots=True)
class ReviewQuery:
    tenant_id: TenantId
    limit: int
    status: ReviewStatus | None = None
    after: ReviewItemKey | None = None


class ListReviewItems:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: ReviewQuery) -> Sequence[ReviewEntry]:
        with self._unit_of_work(query.tenant_id) as uow:
            items = uow.reviews.list(
                status=query.status,
                after=query.after,
                limit=min(max(query.limit, 1), MAX_ITEMS),
            )
            decisions = {
                decision.decision_id: decision
                for decision in uow.decisions.get_many([item.decision_id for item in items])
            }
        return tuple(ReviewEntry(item, decisions[item.decision_id]) for item in items)


@dataclass(frozen=True, slots=True)
class ResolveRequest:
    tenant_id: TenantId
    item_id: ReviewItemId
    resolution: Resolution
    resolved_by: UserId
    note: str


class ResolveReviewItem:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, request: ResolveRequest) -> ReviewEntry:
        now = self._clock()
        with self._unit_of_work(request.tenant_id) as uow:
            item = uow.reviews.get(request.item_id, for_update=True)
            if item is None:
                raise ReviewItemNotFoundError(str(request.item_id))
            if not item.is_open:
                raise ReviewItemResolvedError(str(request.item_id))
            basis = uow.decisions.get(item.decision_id)
            if basis is None:  # pragma: no cover - a foreign key keeps the decision
                raise ReviewItemNotFoundError(str(request.item_id))
            appended = _resolution_decision(item, basis, request.resolution, at=now)
            if appended is not None:
                uow.decisions.add(appended)
                uow.events.publish(ApplicabilityDecided.of(appended))
            resolved = item.resolve(
                request.resolution,
                by=request.resolved_by,
                at=now,
                note=request.note,
                decision_id=None if appended is None else appended.decision_id,
            )
            uow.reviews.save(resolved)
        return ReviewEntry(resolved, basis)


def review_trigger_ref(item_id: ReviewItemId) -> str:
    return f"review:{item_id}"


def _resolution_decision(
    item: ReviewItem, basis: Decision, resolution: Resolution, *, at: datetime
) -> Decision | None:
    result = resolution.result
    if result is None:
        return None
    reference = review_trigger_ref(item.item_id)
    decision_id: DecisionId = decision_id_for(reference, item.business_id, item.rule_version_id)
    return Decision(
        decision_id=decision_id,
        tenant_id=item.tenant_id,
        business_id=item.business_id,
        rule_version_id=item.rule_version_id,
        result=result,
        confidence=CERTAIN,
        evaluated=basis.evaluated,
        profile_version=basis.profile_version,
        decided_at=at,
        trigger=Trigger.REVIEW,
        as_of_fy=basis.as_of_fy,
        trigger_ref=reference,
    )
