"""Read a tenant's decisions: one by id, or a business's newest first, a page at a time.

Both read in the tenant's unit of work, so row-level security scopes them to that tenant.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from applicability_engine.domain.errors import DecisionNotFoundError
from applicability_engine.domain.model import Decision, DecisionKey
from applicability_engine.domain.repository import UnitOfWorkFactory
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId

MAX_DECISIONS = 201
"""The most one read returns: the longest page and the row that tells there is another."""


@dataclass(frozen=True, slots=True)
class DecisionQuery:
    tenant_id: TenantId
    business_id: BusinessId
    limit: int
    rule_version_id: RuleVersionId | None = None
    after: DecisionKey | None = None


class ListDecisions:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: DecisionQuery) -> Sequence[Decision]:
        with self._unit_of_work(query.tenant_id) as uow:
            return tuple(
                uow.decisions.list_for_business(
                    query.business_id,
                    rule_version_id=query.rule_version_id,
                    after=query.after,
                    limit=min(max(query.limit, 1), MAX_DECISIONS),
                )
            )


class ReadDecision:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, decision_id: DecisionId) -> Decision:
        with self._unit_of_work(tenant_id) as uow:
            decision = uow.decisions.get(decision_id)
        if decision is None:
            raise DecisionNotFoundError(str(decision_id))
        return decision
