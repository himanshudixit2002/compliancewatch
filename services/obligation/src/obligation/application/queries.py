"""Read a business's obligations for the Q&A service and the product UI.

``ListObligations`` returns every obligation of one business in any status, optionally only the
ones due inside a window of days in India and of one rule version, due date first. It reads in
the tenant's unit of work, so row-level security scopes it to that tenant; at most
``MAX_OBLIGATIONS`` come back.
"""

from dataclasses import dataclass, field

from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from obligation.application.materialise import IST
from obligation.domain.model import DueWindow, Obligation
from obligation.domain.repository import UnitOfWorkFactory

MAX_OBLIGATIONS = 500


@dataclass(frozen=True, slots=True)
class ObligationQuery:
    tenant_id: TenantId
    business_id: BusinessId
    window: DueWindow = field(default_factory=DueWindow)
    rule_version_id: RuleVersionId | None = None
    limit: int = MAX_OBLIGATIONS


class ListObligations:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: ObligationQuery) -> tuple[Obligation, ...]:
        due_after, due_before = query.window.bounds(IST)
        with self._unit_of_work(query.tenant_id) as uow:
            return tuple(
                uow.obligations.list_for_business(
                    query.business_id,
                    due_after=due_after,
                    due_before=due_before,
                    rule_version_id=query.rule_version_id,
                    limit=min(max(query.limit, 1), MAX_OBLIGATIONS),
                )
            )
