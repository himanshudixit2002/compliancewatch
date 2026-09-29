"""The memory store behaves like the Postgres one where the use cases can tell: units commit or
roll back whole, tenants see only their own notifications, keys are unique across tenants, and
work is claimed once per lease. tests/integration/test_notification_schema.py proves the same
on Postgres."""

from datetime import timedelta

import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.ids import BusinessId, ObligationId, TenantId
from notification.domain.events import NotificationSent
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import (
    ChannelPreference,
    ConsentSource,
    Suppression,
    SuppressionReason,
)
from notification.domain.repository import PageAfter, WorkEntry
from notification.infrastructure.memory import MemoryStore
from notification.testing import NOON_IST

TENANT = TenantId.new()
OTHER = TenantId.new()
BUSINESS = BusinessId.new()
RECIPIENT = RecipientId.new()
PHONE = "+919876543210"
LEASE = timedelta(seconds=60)


def key(n: int) -> DedupeKey:
    return DedupeKey(f"{n:064x}")


def item(n: int, *, tenant: TenantId = TENANT, minutes: int = 0, **changes: object) -> Notification:
    values: dict[str, object] = {
        "tenant_id": tenant,
        "business_id": BUSINESS,
        "obligation_id": ObligationId.new(),
        "recipient_id": RECIPIENT,
        "channel": Channel.WHATSAPP,
        "address": PHONE,
        "occasion": OccasionKind.REMINDER,
        "template_key": "obligation_due_soon",
        "language": "en",
        "params": {"title": f"obligation {n}"},
        "dedupe_key": key(n),
        "now": NOON_IST + timedelta(minutes=minutes),
    }
    values.update(changes)
    return Notification.queue(**values)  # type: ignore[arg-type]


def add(store: MemoryStore, *items: Notification) -> None:
    for notification in items:
        with store(notification.tenant_id) as unit:
            assert unit.notifications.add_if_absent(notification)
            unit.work.add(WorkEntry.of(notification))


def test_a_unit_that_raises_leaves_nothing_behind() -> None:
    store = MemoryStore()
    first = item(1)
    sent, events = first.sent(DispatchId.new(), "wamid.1", NOON_IST)

    def fail_after_writing() -> None:
        with store(TENANT) as unit:
            unit.notifications.add_if_absent(sent)
            for event in events:
                unit.events.publish(event)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        fail_after_writing()
    assert store.notifications_of(TENANT) == []
    assert store.events == []
    with store(TENANT) as unit:
        unit.notifications.add_if_absent(sent)
        for event in events:
            unit.events.publish(event)
    assert [type(e) for e in store.events] == [NotificationSent]


def test_keys_and_ids_are_unique_across_tenants_and_tenants_see_their_own() -> None:
    store = MemoryStore()
    mine = item(1)
    add(store, mine)
    with store(OTHER) as unit:
        assert not unit.notifications.add_if_absent(item(1, tenant=OTHER)), "same key"
        assert unit.notifications.get(mine.id) is None
        assert unit.notifications.by_dedupe_key(key(1)) is None
        with pytest.raises(ValueError, match="another tenant"):
            unit.notifications.add_if_absent(item(2))
        with pytest.raises(ValueError, match="another tenant"):
            unit.work.add(WorkEntry.of(mine))
    with store(TENANT) as unit:
        assert not unit.notifications.add_if_absent(item(9, notification_id=mine.id)), "same id"
        assert unit.notifications.by_dedupe_key(key(1)) == mine
        with pytest.raises(ValueError, match="duplicate"):
            unit.work.add(WorkEntry.of(mine))
        with pytest.raises(ValueError, match="no notification"):
            unit.work.add(WorkEntry.of(item(3)))


def test_save_writes_over_the_tenants_own_notification_only() -> None:
    store = MemoryStore()
    mine = item(1)
    add(store, mine)
    deferred, _ = mine.defer(NOON_IST + LEASE, NOON_IST)
    with store(OTHER) as unit:
        unit.notifications.save(deferred)
    with store(TENANT) as unit:
        assert unit.notifications.get(mine.id) == mine
        unit.notifications.save(deferred)
        assert unit.notifications.get(mine.id) == deferred


def test_due_for_dispatch_and_provider_message_reads() -> None:
    store = MemoryStore()
    early, late, other_channel = item(1), item(2, minutes=10), item(3, channel=Channel.EMAIL)
    add(store, late, early, other_channel)
    dispatch = DispatchId.new()
    with store(TENANT) as unit:
        due = unit.notifications.due_for(RECIPIENT, Channel.WHATSAPP, NOON_IST + LEASE)
        assert [n.id for n in due] == [early.id]
        everything = unit.notifications.due_for(
            RECIPIENT, Channel.WHATSAPP, NOON_IST + timedelta(hours=1)
        )
        assert [n.id for n in everything] == [early.id, late.id]
        for pending in everything:
            sent, _ = pending.sent(dispatch, "wamid.9", NOON_IST)
            unit.notifications.save(sent)
        assert unit.notifications.due_for(RECIPIENT, Channel.WHATSAPP, NOON_IST + LEASE) == []
        assert [n.id for n in unit.notifications.by_dispatch(dispatch)] == [early.id, late.id]
        assert [n.id for n in unit.notifications.by_provider_message("wamid.9")] == [
            early.id,
            late.id,
        ]
        assert unit.notifications.by_provider_message("") == []


def test_latest_params_page_strip_and_purge() -> None:
    store = MemoryStore()
    obligation = ObligationId.new()
    older = item(1, obligation_id=obligation, params={"title": "old"})
    newer = item(2, obligation_id=obligation, params={"title": "new"}, minutes=5)
    empty = item(3, obligation_id=obligation, params={}, minutes=9)
    elsewhere = item(4, business_id=BusinessId.new(), minutes=7)
    theirs = item(5, tenant=OTHER, minutes=8)
    add(store, older, newer, empty, elsewhere, theirs)
    with store(TENANT) as unit:
        notifications = unit.notifications
        assert notifications.latest_params(obligation) == {"title": "new"}
        assert notifications.latest_params(ObligationId.new()) is None
        first = notifications.page(BUSINESS, limit=2)
        assert [n.id for n in first] == [empty.id, newer.id]
        after = PageAfter(first[-1].created_at, first[-1].id)
        assert [n.id for n in notifications.page(BUSINESS, limit=2, after=after)] == [older.id]
        assert notifications.page(BUSINESS, state=DeliveryState.SENT, limit=10) == []
        assert notifications.strip_params(NOON_IST + timedelta(minutes=6)) == 0, "pending"
        for pending in (older, newer):
            sent, _ = pending.sent(DispatchId.new(), "wamid.1", NOON_IST + timedelta(minutes=10))
            notifications.save(sent)
        assert notifications.strip_params(NOON_IST + timedelta(minutes=6)) == 2
        assert notifications.latest_params(obligation) is None
        assert notifications.purge(NOON_IST + timedelta(minutes=6)) == 2
        assert [n.id for n in notifications.page(BUSINESS, limit=10)] == [empty.id]
    assert store.work_row(older.id) is None, "the work entry goes with its notification"
    assert [n.id for n in store.notifications_of(OTHER)] == [theirs.id]


def test_work_is_claimed_once_per_lease_then_completed_or_rescheduled() -> None:
    store = MemoryStore()
    first, second, later = item(1), item(2, minutes=1), item(3, minutes=30)
    add(store, later, second, first)
    work = store.work_index
    now = NOON_IST + timedelta(minutes=2)
    assert [e.id for e in work.claim(limit=1, now=now, lease=LEASE)] == [first.id]
    assert [e.id for e in work.claim(limit=10, now=now, lease=LEASE)] == [second.id]
    assert work.claim(limit=10, now=now, lease=LEASE) == [], "both are leased"
    with store(TENANT) as unit:
        unit.work.complete(first.id, provider_message_id="wamid.1")
        unit.work.reschedule(second.id, now + timedelta(minutes=5))
        unit.work.complete(item(9).id)  # an unknown entry is ignored
        unit.work.reschedule(item(9).id, now)
    after_lease = now + LEASE
    assert work.claim(limit=10, now=after_lease, lease=LEASE) == []
    moved = work.claim(limit=10, now=now + timedelta(minutes=5), lease=LEASE)
    assert [e.id for e in moved] == [second.id]
    assert moved[0].available_at == now + timedelta(minutes=5)
    expired = work.claim(limit=10, now=now + timedelta(minutes=40), lease=LEASE)
    assert [e.id for e in expired] == [second.id, later.id], "a lapsed lease is due again"
    assert work.tenant_for_provider_message("wamid.1") == TENANT
    assert work.tenant_for_provider_message("wamid.x") is None
    assert work.tenant_for_provider_message("") is None
    assert work.tenants() == [TENANT]
    with pytest.raises(ValueError, match="limit"):
        work.claim(limit=0, now=now, lease=LEASE)


def test_an_entry_added_with_a_lease_is_not_claimed_before_it_ends() -> None:
    store = MemoryStore()
    leased = item(1)
    with store(TENANT) as unit:
        assert unit.notifications.add_if_absent(leased)
        unit.work.add(WorkEntry.of(leased), lease_until=NOON_IST + LEASE)
    assert store.work_index.claim(limit=10, now=NOON_IST, lease=LEASE) == []
    claimed = store.work_index.claim(limit=10, now=NOON_IST + LEASE, lease=LEASE)
    assert [entry.id for entry in claimed] == [leased.id]


def test_consents_inbound_times_and_suppressions() -> None:
    store = MemoryStore()
    preference = ChannelPreference(Channel.WHATSAPP, PHONE, True, ConsentSource.API, NOON_IST)
    with store.shared() as unit:
        assert unit.preferences.get(Channel.WHATSAPP, PHONE) is None
        unit.preferences.save(preference)
        unit.preferences.record_inbound(Channel.WHATSAPP, PHONE, NOON_IST)
        unit.preferences.record_inbound(Channel.WHATSAPP, PHONE, NOON_IST - LEASE)
        unit.suppressions.add(
            Suppression(Channel.EMAIL, "a@b.c", SuppressionReason.BOUNCE, NOON_IST, "Permanent")
        )
    with store(TENANT) as unit:
        assert unit.preferences.get(Channel.WHATSAPP, PHONE) == preference
        assert unit.preferences.last_inbound_at(Channel.WHATSAPP, PHONE) == NOON_IST
        assert unit.preferences.last_inbound_at(Channel.EMAIL, "a@b.c") is None
        found = unit.suppressions.get(Channel.EMAIL, "a@b.c")
        assert found is not None
        assert found.reason is SuppressionReason.BOUNCE
        assert unit.suppressions.remove(Channel.EMAIL, "a@b.c")
        assert not unit.suppressions.remove(Channel.EMAIL, "a@b.c")
    assert store.ping()
