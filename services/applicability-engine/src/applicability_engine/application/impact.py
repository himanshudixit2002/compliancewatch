"""The impact of a change on the caller's tenant (``domain.impact``): a page of its clients with
each business's latest decision of the version, the counts by result, and the version's fan-out.

It reads the engine's own tables only, in two short transactions: the decisions and the
directory in one unit of work of the tenant, under its row-level security, then the fan-out run,
which belongs to no tenant. Nothing is called over HTTP: the engine cannot say whether a version
it never decided exists, so such a version has no decision and no fan-out.
"""

from applicability_engine.domain.impact import (
    MAX_ENTITIES,
    ChangeImpact,
    ImpactQuery,
    every_result,
    grouped,
)
from applicability_engine.domain.repository import FanOutUnitOfWorkFactory, UnitOfWorkFactory


class ReadChangeImpact:
    def __init__(self, unit_of_work: UnitOfWorkFactory, fanouts: FanOutUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work
        self._fanouts = fanouts

    def run(self, query: ImpactQuery) -> ChangeImpact:
        limit = min(query.limit, MAX_ENTITIES)
        with self._unit_of_work(query.tenant_id) as uow:
            entries = uow.impact.latest_by_entity(
                query.rule_version_id, result=query.result, after=query.after, limit=limit
            )
            counts = uow.impact.result_counts(query.rule_version_id)
        with self._fanouts() as fanouts:
            run = fanouts.runs.get(query.rule_version_id)
        return ChangeImpact(
            rule_version_id=query.rule_version_id,
            groups=grouped(entries),
            counts=every_result(counts),
            fan_out=run,
        )
