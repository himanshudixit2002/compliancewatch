"""The retention sweep on the memory store: two years for the record, 30 days for the values,
one unit of work per tenant the work index knows."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.ids import BusinessId, ObligationId, TenantId
from notification.application.retention import PurgeExpired, Swept
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import Notification
from notification.domain.occasions import OccasionKind
from notification.domain.policy import RetentionPolicy
from notification.domain.repository import SharedUnitOfWork, UnitOfWork, WorkEntry
from notification.infrastructure.memory import MemoryStore
from notification.testing import NOON_IST

NOW = NOON_IST
YEARS_AGO = NOW - timedelta(days=731)
WEEKS_AGO = NOW - timedelta(days=45)
DAYS_AGO = NOW - timedelta(days=10)


def notification(tenant: TenantId, at: datetime, n: int) -> Notification:
    return Notification.queue(
        tenant_id=tenant,
        business_id=BusinessId.new(),
        obligation_id=ObligationId.new(),
        recipient_id=RecipientId.new(),
        channel=Channel.WHATSAPP,
        address="+919876543210",
        occasion=OccasionKind.REMINDER,
        template_key="obligation_due_soon",
        language="en",
        params={"title": f"obligation {n}"},
        dedupe_key=DedupeKey(f"{n:064x}"),
        now=at,
    )


def add(store: MemoryStore, *notifications: Notification, sent: bool = True) -> None:
    for item in notifications:
        with store(item.tenant_id) as unit:
            unit.notifications.add_if_absent(item)
            unit.work.add(WorkEntry.of(item))
            if sent:
                done, _ = item.sent(DispatchId.new(), f"wamid.{item.id}", item.created_at)
                unit.notifications.save(done)
                unit.work.complete(item.id, provider_message_id=done.provider_message_id)


class CountingStore:
    """The memory store's units, counted by tenant."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.opened: list[TenantId] = []

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    def shared(self) -> AbstractContextManager[SharedUnitOfWork]:  # pragma: no cover - unused
        return self.store.shared()

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        self.opened.append(tenant_id)
        with self.store(tenant_id) as unit:
            yield unit


def test_old_records_go_and_values_past_thirty_days_are_emptied_in_every_tenant() -> None:
    store = MemoryStore()
    first, second = TenantId.new(), TenantId.new()
    ancient = notification(first, YEARS_AGO, 1)
    older = notification(first, WEEKS_AGO, 2)
    recent = notification(first, DAYS_AGO, 3)
    theirs = notification(second, YEARS_AGO, 4)
    waiting = notification(second, WEEKS_AGO, 5)
    add(store, ancient, older, recent, theirs)
    add(store, waiting, sent=False)
    units = CountingStore(store)
    swept = PurgeExpired(units, store.work_index, clock=lambda: NOW).run()
    assert swept == Swept(tenants=2, purged=2, stripped=1)
    assert sorted(units.opened, key=str) == sorted([first, second], key=str), "one unit each"
    kept = {n.id: n for tenant in (first, second) for n in store.notifications_of(tenant)}
    assert set(kept) == {older.id, recent.id, waiting.id}
    assert kept[older.id].params == {}, "sent more than 30 days ago: the record stays"
    assert kept[recent.id].params == {"title": "obligation 3"}
    assert kept[waiting.id].params == {"title": "obligation 5"}, "still pending: values kept"
    assert store.work_row(ancient.id) is None, "the work entry goes with its notification"
    again = PurgeExpired(store, store.work_index, clock=lambda: NOW).run()
    assert again == Swept(tenants=2)


def test_the_policy_sets_the_periods_and_no_tenant_means_nothing_to_do() -> None:
    store = MemoryStore()
    assert PurgeExpired(store, store.work_index, clock=lambda: NOW).run() == Swept()
    tenant = TenantId.new()
    add(store, notification(tenant, DAYS_AGO, 1))
    short = RetentionPolicy(keep_days=5, params_days=1)
    swept = PurgeExpired(store, store.work_index, policy=short, clock=lambda: NOW).run()
    assert swept == Swept(tenants=1, purged=1)
    assert store.notifications_of(tenant) == []
