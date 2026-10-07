"""The tenant's data export: every row the engine keeps of one tenant, as JSON-safe mappings.

Identity assembles a tenant's export by asking each service for its part; this is the engine's.
Two sections, each always present:

- ``decisions``: every decision of the tenant, the superseded ones and the manual ones and the
  reviewers' included, since decisions are append-only and each one is a record of what the
  engine said and why, with the outcome of every predicate;
- ``review_items``: the tenant's review items, open and resolved, with who settled each and the
  note.

Both are read in one unit of work of the tenant, so row-level security keeps them to it in
Postgres and the memory store filters by tenant, a keyset page of ``page_size`` rows at a time,
oldest first then by id. The rows the engine keeps across tenants (the business directory, read
by the fan-out over every tenant, the fan-out runs and the global hold, both rule-level) are not
the tenant's data and are left out, as are the idempotency keys and the outbox. Identity writes
the audit entry of the export; nothing here does.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from applicability_engine import SERVICE_NAME
from applicability_engine.domain.model import Decision, DecisionKey
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.domain.review import ReviewItem, ReviewItemKey
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from domain_kernel.predicates import specification_to_mapping

EXPORT_PAGE_SIZE: Final = 500
"""How many rows one read of a section returns."""
DECISIONS: Final = "decisions"
REVIEW_ITEMS: Final = "review_items"
SECTIONS: Final = (DECISIONS, REVIEW_ITEMS)
"""The sections of the engine's part of an export, in the order it lists them."""


@dataclass(frozen=True, slots=True)
class TenantDataExport:
    """The engine's part of a tenant's export: each section's rows, oldest first."""

    service: str
    tenant_id: TenantId
    generated_at: datetime
    sections: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)


class ExportTenantData:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Callable[[], datetime] = utc_now,
        *,
        page_size: int = EXPORT_PAGE_SIZE,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._page_size = page_size

    def run(self, tenant_id: TenantId) -> TenantDataExport:
        decisions: list[Decision] = []
        items: list[ReviewItem] = []
        with self._unit_of_work(tenant_id) as uow:
            after_decision: DecisionKey | None = None
            while True:
                page = uow.decisions.export_decisions(after=after_decision, limit=self._page_size)
                decisions.extend(page)
                if len(page) < self._page_size:
                    break
                after_decision = DecisionKey.of(page[-1])
            after_item: ReviewItemKey | None = None
            while True:
                found = uow.reviews.list(status=None, after=after_item, limit=self._page_size)
                items.extend(found)
                if len(found) < self._page_size:
                    break
                after_item = ReviewItemKey.of(found[-1])
        return TenantDataExport(
            service=SERVICE_NAME,
            tenant_id=tenant_id,
            generated_at=self._clock().astimezone(UTC),
            sections={
                DECISIONS: [decision_row(decision) for decision in decisions],
                REVIEW_ITEMS: [review_item_row(item) for item in items],
            },
        )


def _instant(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def decision_row(decision: Decision) -> dict[str, Any]:
    """A decision as the export lists it: the domain's fields, each predicate in the kernel's
    specification mapping with its outcome, confidence and reason."""
    return {
        "decision_id": str(decision.decision_id),
        "tenant_id": str(decision.tenant_id),
        "business_id": str(decision.business_id),
        "rule_version_id": str(decision.rule_version_id),
        "result": decision.result.value,
        "confidence": decision.confidence.value,
        "needs_review": decision.needs_review,
        "evaluated": [
            {
                "predicate": specification_to_mapping(item.predicate),
                "outcome": item.outcome.value,
                "confidence": item.confidence.value,
                "reason": item.reason,
            }
            for item in decision.evaluated
        ],
        "profile_version": decision.profile_version,
        "decided_at": _instant(decision.decided_at),
        "trigger": decision.trigger.value,
        "trigger_ref": decision.trigger_ref,
        "as_of_fy": None if decision.as_of_fy is None else decision.as_of_fy.label,
    }


def review_item_row(item: ReviewItem) -> dict[str, Any]:
    """A review item as the export lists it: the domain's fields."""
    return {
        "item_id": str(item.item_id),
        "tenant_id": str(item.tenant_id),
        "business_id": str(item.business_id),
        "rule_version_id": str(item.rule_version_id),
        "decision_id": str(item.decision_id),
        "reason": item.reason.value,
        "opened_at": _instant(item.opened_at),
        "status": item.status.value,
        "resolution": None if item.resolution is None else item.resolution.value,
        "resolved_by": None if item.resolved_by is None else str(item.resolved_by),
        "resolved_at": _instant(item.resolved_at),
        "note": item.note,
        "resolution_decision_id": None
        if item.resolution_decision_id is None
        else str(item.resolution_decision_id),
    }
