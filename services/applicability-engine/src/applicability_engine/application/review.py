"""The review queue: keeping items in step with the decisions, listing them, resolving one.

``track_review`` runs in the unit of work that stores a decision, so an item opens, follows or
is settled in the same transaction as the decision behind it (``domain.review`` has the rule).
``ListReviewItems`` reads a tenant's items oldest first with the decision each one is about.
``ResolveReviewItem`` settles an open item for a reviewer: ``applies`` and ``not_applicable``
append a decision with trigger ``review``, made from the decision under review (its predicates,
profile version and year) with the reviewer's result and confidence 1, and publish its
``applicability.decided``; ``dismiss`` appends nothing. The item is held while it is resolved,
so two reviewers cannot both settle it.

Every resolution writes its audit entry in the same unit of work, so the two commit or roll back
together: ``applicability.review.resolve`` on the item, of the item's tenant, with the actor the
request names, the note as the reason and the item's state before and after. An item a later
decision settles by itself (``track_review``: ``dismiss`` with no person) writes none, since no
person acted and the item records the decision that settled it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

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
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.confidence import CERTAIN
from domain_kernel.events import utc_now
from domain_kernel.ids import DecisionId, TenantId, UserId

MAX_ITEMS = 201
"""The most one read returns: the longest page and the row that tells there is another."""
RESOLVE_ACTION: Final = "applicability.review.resolve"
"""The audit action of a reviewer's resolution."""
REVIEW_SUBJECT: Final = "review_item"


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
    """``resolved_by`` is the reviewer the item records; ``actor`` is who the audit entry names,
    the verified reviewer or else the system (``py_common.audit.audit_actor``), and
    ``correlation_id`` the request behind it."""

    tenant_id: TenantId
    item_id: ReviewItemId
    resolution: Resolution
    resolved_by: UserId
    note: str
    actor: AuditActor
    correlation_id: str | None = None


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
            uow.audit.write(_resolution_entry(item, resolved, request, at=now))
        return ReviewEntry(resolved, basis)


def review_trigger_ref(item_id: ReviewItemId) -> str:
    return f"review:{item_id}"


def _resolution_entry(
    before: ReviewItem, after: ReviewItem, request: ResolveRequest, *, at: datetime
) -> AuditEntry:
    """The audit entry of a reviewer's resolution of ``before`` into ``after``."""
    return AuditEntry(
        action=RESOLVE_ACTION,
        tenant_id=after.tenant_id,
        subject_type=REVIEW_SUBJECT,
        subject_id=str(after.item_id),
        actor=request.actor,
        reason=request.note,
        before=_audited(before),
        after=_audited(after),
        occurred_at=at,
        correlation_id=request.correlation_id,
    )


def _audited(item: ReviewItem) -> dict[str, object]:
    """What an audit entry keeps of an item: its status, the decision under review, and how and
    by whom it was resolved."""
    return {
        "status": item.status.value,
        "decision_id": str(item.decision_id),
        "resolution": None if item.resolution is None else item.resolution.value,
        "resolved_by": None if item.resolved_by is None else str(item.resolved_by),
        "resolution_decision_id": None
        if item.resolution_decision_id is None
        else str(item.resolution_decision_id),
    }


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
