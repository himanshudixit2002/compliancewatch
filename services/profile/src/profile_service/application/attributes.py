"""Store attribute values, answer the next question, assemble snapshots, roll the financial year.

``SetAttributes`` applies a batch of changes to one node: the ontology decides what is valid,
the node bumps its version, ``profile.updated`` goes to the outbox, a ``not_applicable`` answer
opens a review task and records an eval case. ``apply_changes`` does the same inside a unit of
work the caller holds, for use cases that write several nodes at once. ``NextQuestion``
returns one attribute to ask. ``BuildSnapshot`` merges the lineage for the applicability
engine. ``ConfirmFinancialYear`` opens a confirmation task for every entity whose per-year
values are missing for the new year (the April task of ADR-016); ``financial_year_in_india``
names the year a moment falls in.

Every save that changes a value writes one ``profile_node.attributes_changed`` audit entry with
the values it changed, before and after (``application.audit``); the pre-fill writes
``profile_node.prefilled`` through the same path.

An answer closes the review task that asked for it: when a save stores a known or a
does-not-apply value for the attribute (and year) an open task of the node asks about, the task
closes with ``closed_by`` answer in the same transaction, with its ``review_task.closed`` entry
(``close_answered``). An unsure answer closes nothing. A person closes a task explicitly through
``application.review_tasks.ResolveReviewTask``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from domain_kernel._validation import require_aware
from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId, UserId
from domain_kernel.ontology import Ontology
from domain_kernel.profiles import ProfileSnapshot
from profile_service.application.audit import (
    ATTRIBUTES_CHANGED,
    record_attributes,
    record_review_task_closed,
)
from profile_service.domain.errors import ProfileNodeNotFoundError
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import (
    AttributeChange,
    ProfileNode,
    ReviewReason,
    ReviewRequest,
    ReviewTask,
    ValueState,
)
from profile_service.domain.repository import UnitOfWork, UnitOfWorkFactory

ANSWERS: Final = frozenset({ValueState.KNOWN, ValueState.NOT_APPLICABLE})
"""The states that answer a review task's question; unsure leaves it open."""


@dataclass(frozen=True, slots=True)
class SetResult:
    node: ProfileNode
    changed: tuple[str, ...]
    review_tasks: tuple[BusinessId, ...]
    """The review tasks the save opened."""
    closed_review_tasks: tuple[BusinessId, ...] = ()
    """The open tasks of the node the save answered, closed with it."""


class SetAttributes:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ontology: Ontology,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ontology = ontology
        self._clock = clock

    def now(self) -> datetime:
        return self._clock()

    def run(
        self,
        tenant_id: TenantId,
        node_id: BusinessId,
        changes: Sequence[AttributeChange],
        *,
        source: ChangeSource,
        by: UserId | None = None,
    ) -> SetResult:
        now = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            node = uow.profiles.get(node_id)
            if node is None:
                raise ProfileNodeNotFoundError(str(node_id))
            return apply_changes(
                uow,
                tenant_id,
                node,
                changes,
                ontology=self._ontology,
                source=source,
                by=by,
                now=now,
            )


def apply_changes(
    uow: UnitOfWork,
    tenant_id: TenantId,
    node: ProfileNode,
    changes: Sequence[AttributeChange],
    *,
    ontology: Ontology,
    source: ChangeSource,
    by: UserId | None,
    now: datetime,
    audit_action: str = ATTRIBUTES_CHANGED,
) -> SetResult:
    """Apply ``changes`` to ``node`` inside the caller's unit of work.

    The node is saved, ``profile.updated`` goes to the outbox and ``audit_action`` to the audit
    log with the values that changed; each ``not_applicable`` answer opens a review task and
    records an eval case. A batch that changes nothing stores nothing.
    Every use case that writes attributes goes through here, so a rejected value anywhere in a
    unit of work rolls the whole unit back.
    """
    outcome = node.apply(changes, ontology=ontology, source=source, at=now, by=by)
    if outcome.event is None:
        return SetResult(node, (), ())
    uow.profiles.save(outcome.node)
    uow.events.publish(outcome.event)
    record_attributes(uow, audit_action, node, outcome.node, now)
    closed = close_answered(uow, node, outcome.node, now)
    tasks = tuple(open_review(uow, tenant_id, request, now) for request in outcome.reviews)
    for request in outcome.reviews:
        uow.eval_cases.record(_eval_case(outcome.node, request, now))
    return SetResult(outcome.node, outcome.event.changed_attributes, tasks, closed)


def close_answered(
    uow: UnitOfWork, before: ProfileNode, after: ProfileNode, now: datetime
) -> tuple[BusinessId, ...]:
    """Close the open tasks of the node whose attribute (and year) the save answered: a known or
    a does-not-apply value stored where there was none, or another one. Each closure writes its
    ``review_task.closed`` entry in ``uow``."""
    answered = {
        storage_key
        for storage_key, record in after.attributes.items()
        if record.state in ANSWERS and before.attributes.get(storage_key) != record
    }
    closed: list[BusinessId] = []
    for task in uow.profiles.open_review_tasks(after.id):
        if task.storage_key not in answered:
            continue
        done = task.answered(now)
        uow.profiles.save_review_task(done)
        record_review_task_closed(uow, done)
        closed.append(done.id)
    return tuple(closed)


class NextQuestion:
    def __init__(self, unit_of_work: UnitOfWorkFactory, ontology: Ontology) -> None:
        self._unit_of_work = unit_of_work
        self._ontology = ontology

    def run(
        self, tenant_id: TenantId, node_id: BusinessId, *, as_of_fy: FinancialYear
    ) -> str | None:
        with self._unit_of_work(tenant_id) as uow:
            node = uow.profiles.get(node_id)
            if node is None:
                raise ProfileNodeNotFoundError(str(node_id))
            return node.next_question(self._ontology, as_of_fy=as_of_fy)


class BuildSnapshot:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self, tenant_id: TenantId, node_id: BusinessId, *, as_of_fy: FinancialYear | None
    ) -> ProfileSnapshot:
        with self._unit_of_work(tenant_id) as uow:
            node = uow.profiles.get(node_id)
            if node is None:
                raise ProfileNodeNotFoundError(str(node_id))
            return node.snapshot(uow.profiles.lineage(node), as_of_fy=as_of_fy)


IST = timezone(timedelta(hours=5, minutes=30), "IST")
"""Indian Standard Time, in which the financial year turns: midnight on 1 April."""


def financial_year_in_india(at: datetime) -> FinancialYear:
    """The financial year of the date ``at`` falls on in IST."""
    return FinancialYear.for_date(require_aware(at, "at").astimezone(IST).date())


class ConfirmFinancialYear:
    """Open one ``confirm_financial_year`` task per entity and missing per-year attribute.

    Idempotent: a task for the same entity, attribute and year, open or closed, is not opened
    again, so a rerun opens nothing and a task a person dismissed stays dismissed; a year's
    value, once known, is not missing. The worker's schedule runs it for every tenant once the
    year has turned (``profile_service.application.fy_schedule``).
    """

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ontology: Ontology,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ontology = ontology
        self._clock = clock

    def run(self, tenant_id: TenantId, fy: FinancialYear) -> tuple[BusinessId, ...]:
        now = self._clock()
        opened: list[BusinessId] = []
        with self._unit_of_work(tenant_id) as uow:
            existing = {task.dedupe_key for task in uow.profiles.review_tasks()}
            for entity in uow.profiles.entities():
                for key in entity.missing_for_year(self._ontology, fy):
                    request = ReviewRequest(entity.id, key, ReviewReason.CONFIRM_FINANCIAL_YEAR, fy)
                    if (entity.id, key, request.reason, fy.label) in existing:
                        continue
                    opened.append(open_review(uow, tenant_id, request, now))
        return tuple(opened)


def open_review(
    uow: UnitOfWork, tenant_id: TenantId, request: ReviewRequest, now: datetime
) -> BusinessId:
    task = ReviewTask(
        id=BusinessId.new(),
        tenant_id=tenant_id,
        node_id=request.node_id,
        attribute_key=request.attribute_key,
        reason=request.reason,
        as_of_fy=request.as_of_fy,
        open=True,
        created_at=now,
    )
    uow.profiles.add_review_task(task)
    return task.id


def _eval_case(node: ProfileNode, request: ReviewRequest, now: datetime) -> dict[str, object]:
    """A golden case seed: what the business said, for the analyst to label."""
    return {
        "kind": "profile.not_applicable",
        "recorded_at": now.isoformat(),
        "tenant_id": str(node.tenant_id),
        "node_id": str(node.id),
        "level": node.level.value,
        "attribute": request.attribute_key,
        "as_of_fy": None if request.as_of_fy is None else request.as_of_fy.label,
        "answer": ValueState.NOT_APPLICABLE.value,
        "known_attributes": dict(node.known_values(request.as_of_fy)),
        "label": None,
    }
