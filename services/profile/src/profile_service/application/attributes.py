"""Store attribute values, answer the next question, assemble snapshots, roll the financial year.

``SetAttributes`` applies a batch of changes to one node: the ontology decides what is valid,
the node bumps its version, ``profile.updated`` goes to the outbox, a ``not_applicable`` answer
opens a review task and records an eval case. ``NextQuestion`` returns one attribute to ask.
``BuildSnapshot`` merges the lineage for the applicability engine. ``ConfirmFinancialYear``
opens a confirmation task for every entity whose per-year values are missing for the new year
(the April task of ADR-016); ``financial_year_in_india`` names the year a moment falls in.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from domain_kernel._validation import require_aware
from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId, UserId
from domain_kernel.ontology import Ontology
from domain_kernel.profiles import ProfileSnapshot
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


@dataclass(frozen=True, slots=True)
class SetResult:
    node: ProfileNode
    changed: tuple[str, ...]
    review_tasks: tuple[BusinessId, ...]


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
            outcome = node.apply(changes, ontology=self._ontology, source=source, at=now, by=by)
            if outcome.event is None:
                return SetResult(node, (), ())
            uow.profiles.save(outcome.node)
            uow.events.publish(outcome.event)
            tasks = tuple(open_review(uow, tenant_id, request, now) for request in outcome.reviews)
            for request in outcome.reviews:
                uow.eval_cases.record(_eval_case(outcome.node, request, now))
            return SetResult(outcome.node, outcome.event.changed_attributes, tasks)


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

    Idempotent: a task still open for the same entity, attribute and year is not opened again.
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
            existing = {task.dedupe_key for task in uow.profiles.open_review_tasks()}
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
