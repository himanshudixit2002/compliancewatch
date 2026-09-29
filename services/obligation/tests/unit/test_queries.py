"""Listing a business's obligations on the memory store: the window, the order, the filters,
the cap and tenant isolation."""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from typing import Any

from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.application.changes import CloseObligation
from obligation.application.materialise import IST, MaterialiseObligations, MaterialiseRequest
from obligation.application.queries import MAX_OBLIGATIONS, ListObligations, ObligationQuery
from obligation.domain.model import DueWindow, Obligation
from obligation.domain.repository import UnitOfWork
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import BUSINESS, DECISION, OTHER_TENANT, TENANT, clock, rule

AS_OF = date(2026, 9, 28)
ON_THE_20TH = rule()
ON_THE_11TH = rule(recurrence=Recurrence.monthly(11))
UNDATED = rule(recurrence=None)


def materialise(
    store: MemoryStore, the_rule: RuleVersionSnapshot, business: BusinessId = BUSINESS
) -> None:
    MaterialiseObligations(store, window=3, clock=clock).run(
        MaterialiseRequest(TENANT, business, DECISION, the_rule, AS_OF)
    )


def seeded() -> MemoryStore:
    store = MemoryStore()
    for the_rule in (ON_THE_20TH, UNDATED, ON_THE_11TH):
        materialise(store, the_rule)
    materialise(store, ON_THE_20TH, BusinessId.new())
    return store


def due_days(found: Sequence[Obligation]) -> list[date | None]:
    return [None if o.due_at is None else o.due_at.astimezone(IST).date() for o in found]


def listing(store: MemoryStore, **fields: Any) -> tuple[Obligation, ...]:
    values: dict[str, Any] = {"tenant_id": TENANT, "business_id": BUSINESS, **fields}
    return ListObligations(store).run(ObligationQuery(**values))


def test_every_obligation_of_the_business_comes_due_date_first_undated_last() -> None:
    found = listing(seeded())
    assert due_days(found) == [
        date(2026, 10, 11),
        date(2026, 10, 20),
        date(2026, 11, 11),
        date(2026, 11, 20),
        date(2026, 12, 11),
        date(2026, 12, 20),
        None,
    ]
    assert {o.business_id for o in found} == {BUSINESS}


def test_the_window_includes_both_end_days_in_india_and_drops_undated_ones() -> None:
    store = seeded()
    window = DueWindow(date(2026, 10, 20), date(2026, 11, 11))
    assert due_days(listing(store, window=window)) == [date(2026, 10, 20), date(2026, 11, 11)]
    narrower = DueWindow(date(2026, 10, 21), date(2026, 11, 10))
    assert listing(store, window=narrower) == ()
    open_ended = DueWindow(due_from=date(2026, 12, 1))
    assert due_days(listing(store, window=open_ended)) == [date(2026, 12, 11), date(2026, 12, 20)]
    until = DueWindow(due_to=date(2026, 10, 11))
    assert due_days(listing(store, window=until)) == [date(2026, 10, 11)]


def test_a_rule_version_filter_and_closed_obligations() -> None:
    store = seeded()
    only = listing(store, rule_version_id=ON_THE_11TH.rule_version_id)
    assert due_days(only) == [date(2026, 10, 11), date(2026, 11, 11), date(2026, 12, 11)]
    CloseObligation(store, clock=clock).run(TENANT, only[0].id, ClosureReason.COMPLETED)
    again = listing(store, rule_version_id=ON_THE_11TH.rule_version_id)
    assert [o.status for o in again] == [
        ObligationStatus.DONE,
        ObligationStatus.OPEN,
        ObligationStatus.OPEN,
    ], "every status is listed"
    assert listing(store, rule_version_id=RuleVersionId.new()) == ()


def test_other_tenants_see_nothing() -> None:
    store = seeded()
    assert listing(store, tenant_id=OTHER_TENANT) == ()
    assert listing(store, business_id=BusinessId.new()) == ()


def test_the_limit_is_kept_between_one_and_the_cap() -> None:
    store = seeded()
    assert due_days(listing(store, limit=2)) == [date(2026, 10, 11), date(2026, 10, 20)]
    assert len(listing(store, limit=0)) == 1

    limits: list[int] = []

    class Recording:
        def list_for_business(self, business_id: BusinessId, **kwargs: Any) -> list[Obligation]:
            limits.append(kwargs["limit"])
            return []

    class Unit:
        obligations = Recording()

    @contextmanager
    def unit_of_work(tenant_id: TenantId) -> Iterator[Any]:
        yield Unit()

    def factory(tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return unit_of_work(tenant_id)

    ListObligations(factory).run(ObligationQuery(TENANT, BUSINESS, limit=10_000))
    assert limits == [MAX_OBLIGATIONS] == [500]
