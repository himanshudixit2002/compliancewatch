from datetime import UTC, datetime, timedelta

import pytest

from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from notification.application.enqueue import Enqueued, EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.domain.ids import RecipientId
from notification.domain.notification import DeliveryState
from notification.domain.occasions import Occasion, OccasionKind, dedupe_key
from notification.domain.policy import BatchPolicy, DigestPolicy
from notification.domain.ports import QueueResult
from notification.domain.preferences import ConsentSource, Suppression, SuppressionReason
from notification.domain.recipients import BusinessLink, DigestMode, RecipientRole
from notification.domain.repository import WorkKind
from notification.domain.routing import ObligationNotice
from notification.infrastructure.memory import MemoryStore
from notification.testing import NOON_IST, FakeClock, RecordingMetrics

TENANT = TenantId.new()
BUSINESS = BusinessId.new()
WA, EMAIL = Channel.WHATSAPP, Channel.EMAIL
WINDOW = timedelta(seconds=300)


class Setup:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.store = MemoryStore()
        self.metrics = RecordingMetrics()
        self.enqueue = EnqueueNotifications(
            self.store,
            batch=BatchPolicy(window_seconds=300),
            metrics=self.metrics,
            clock=self.clock,
        )

    def recipient(
        self,
        *addresses: tuple[Channel, str],
        businesses: tuple[BusinessId, ...] = (BUSINESS,),
        opt_in: bool = True,
        tenant: TenantId = TENANT,
        role: RecipientRole = RecipientRole.OWNER,
        digest_mode: DigestMode = DigestMode.OFF,
    ) -> RecipientId:
        recipient_id = RecipientId.new()
        RegisterRecipient(self.store, clock=self.clock).run(
            RecipientRegistration(
                tenant_id=tenant,
                recipient_id=recipient_id,
                role=role,
                digest_mode=digest_mode,
                language="hi",
                addresses=addresses,
                businesses=[BusinessLink(business) for business in businesses],
            )
        )
        if opt_in:
            for channel, address in addresses:
                self.opt_in(channel, address)
        return recipient_id

    def opt_in(self, channel: Channel, address: str, *, opted_in: bool = True) -> None:
        SetOptIn(self.store, clock=self.clock).run(
            channel, address, opted_in=opted_in, source=ConsentSource.API
        )


def created(
    business: BusinessId = BUSINESS, obligation: ObligationId | None = None
) -> ObligationNotice:
    rule_version = RuleVersionId.new()
    return ObligationNotice(
        tenant_id=TENANT,
        business_id=business,
        occasion=Occasion.change_card(obligation or ObligationId.new(), rule_version),
        template_key="change_card",
        params={"title": "File GSTR-3B", "rule_version_id": str(rule_version)},
    )


def test_fans_out_to_the_first_open_address_of_each_recipient_of_the_business() -> None:
    setup = Setup()
    owner = setup.recipient((WA, "+91 98765 43210"), (EMAIL, "owner@example.com"))
    staff = setup.recipient((EMAIL, "Staff@Example.com"))
    setup.recipient((WA, "+91 90000 00000"), businesses=(BusinessId.new(),))
    notice = created()
    assert setup.enqueue.run(notice) == Enqueued(queued=2)
    by_recipient = {n.recipient_id: n for n in setup.store.notifications_of(TENANT)}
    assert set(by_recipient) == {owner, staff}
    first = by_recipient[owner]
    assert (first.channel, first.address, first.language) == (WA, "+919876543210", "hi")
    assert (first.state, first.occasion, first.template_key) == (
        DeliveryState.QUEUED,
        OccasionKind.CHANGE_CARD,
        "change_card",
    )
    assert first.available_at == NOON_IST + WINDOW, "due at the end of the batching window"
    assert first.dedupe_key == dedupe_key(notice.occasion, BUSINESS, owner, WA)
    assert dict(first.params) == dict(notice.params)
    assert by_recipient[staff].address == "staff@example.com"
    for notification in by_recipient.values():
        work = setup.store.work_row(notification.id)
        assert work is not None
        assert (work.status, work.entry.available_at) == ("pending", NOON_IST + WINDOW)
    assert sorted(setup.metrics.enqueues) == [(EMAIL, QueueResult.QUEUED), (WA, QueueResult.QUEUED)]


def test_skips_what_is_not_opted_in_or_suppressed_and_falls_to_the_next_address() -> None:
    setup = Setup()
    silent = setup.recipient((WA, "+919876543210"), opt_in=False)
    setup.opt_in(WA, "+919876543210", opted_in=False)
    both = setup.recipient((WA, "+919811111111"), (EMAIL, "both@example.com"), opt_in=False)
    setup.opt_in(EMAIL, "both@example.com")
    suppressed = setup.recipient((EMAIL, "gone@example.com"))
    with setup.store.shared() as unit:
        unit.suppressions.add(
            Suppression(EMAIL, "gone@example.com", SuppressionReason.BOUNCE, NOON_IST)
        )
    assert setup.enqueue.run(created()) == Enqueued(queued=1, unreachable=2)
    (only,) = setup.store.notifications_of(TENANT)
    assert (only.recipient_id, only.channel) == (both, EMAIL), "WhatsApp never opted in"
    assert silent != suppressed


def test_a_redelivered_event_makes_one_row() -> None:
    setup = Setup()
    setup.recipient((WA, "+919876543210"))
    notice = created()
    assert setup.enqueue.run(notice).queued == 1
    setup.clock.advance(30)
    assert setup.enqueue.run(notice) == Enqueued(duplicates=1)
    assert len(setup.store.notifications_of(TENANT)) == 1
    assert setup.metrics.enqueues[-1] == (WA, QueueResult.DUPLICATE)


def test_a_notification_joins_the_batch_still_waiting_for_the_same_person_and_business() -> None:
    setup = Setup()
    other = BusinessId.new()
    setup.recipient((WA, "+919876543210"), businesses=(BUSINESS, other))
    setup.enqueue.run(created())
    setup.clock.advance(120)
    setup.enqueue.run(created())
    setup.enqueue.run(created(other))
    ours = [n for n in setup.store.notifications_of(TENANT) if n.business_id == BUSINESS]
    (theirs,) = [n for n in setup.store.notifications_of(TENANT) if n.business_id == other]
    assert [n.available_at for n in ours] == [NOON_IST + WINDOW] * 2
    assert theirs.available_at == NOON_IST + timedelta(seconds=120) + WINDOW, "another business"
    setup.clock.advance(300)
    setup.enqueue.run(created())
    latest = max(setup.store.notifications_of(TENANT), key=lambda n: n.created_at)
    assert latest.available_at == setup.clock.now + WINDOW, "the first batch is already due"


def test_an_audience_keeps_the_recipients_the_notice_is_for() -> None:
    setup = Setup()
    owner = setup.recipient((WA, "+919800000001"))
    setup.recipient((WA, "+919800000002"), role=RecipientRole.CA_ADMIN)
    with setup.store(TENANT) as unit:
        queued = setup.enqueue.run_in(
            unit, created(), audience=lambda recipient: recipient.role is RecipientRole.OWNER
        )
    assert queued == Enqueued(queued=1)
    assert [n.recipient_id for n in setup.store.notifications_of(TENANT)] == [owner]


def test_run_in_works_in_the_callers_unit_of_its_tenant() -> None:
    setup = Setup()
    setup.recipient((WA, "+919876543210"))
    with setup.store(TENANT) as unit:
        assert setup.enqueue.run_in(unit, created()).queued == 1
        assert len(unit.notifications.due_for(RecipientId.new(), WA, NOON_IST)) == 0
    assert len(setup.store.notifications_of(TENANT)) == 1
    with setup.store(TenantId.new()) as unit, pytest.raises(InvariantViolationError):
        setup.enqueue.run_in(unit, created())


def test_a_window_of_zero_makes_the_notification_due_at_once() -> None:
    setup = Setup()
    setup.recipient((WA, "+919876543210"))
    EnqueueNotifications(setup.store, batch=BatchPolicy(window_seconds=0), clock=setup.clock).run(
        created()
    )
    (queued,) = setup.store.notifications_of(TENANT)
    assert queued.available_at == NOON_IST


NINE_IST_TOMORROW = datetime(2026, 9, 29, 3, 30, tzinfo=UTC)


def test_a_digest_recipient_gets_its_notification_held_for_the_next_nine_ist() -> None:
    setup = Setup()
    daily = setup.recipient((WA, "+919876543210"), digest_mode=DigestMode.DAILY)
    firm = setup.recipient((EMAIL, "ca@example.com"), role=RecipientRole.CA_STAFF)
    owner = setup.recipient((WA, "+919811111111"))
    assert setup.enqueue.run(created()) == Enqueued(queued=3)
    by_recipient = {n.recipient_id: n for n in setup.store.notifications_of(TENANT)}
    for held in (by_recipient[daily], by_recipient[firm]):
        assert (held.state, held.available_at) == (DeliveryState.DIGEST_PENDING, NINE_IST_TOMORROW)
        work = setup.store.work_row(held.id)
        assert work is not None
        assert (work.entry.kind, work.entry.available_at) == (
            WorkKind.DIGEST_ITEM,
            NINE_IST_TOMORROW,
        )
    assert (by_recipient[owner].state, by_recipient[owner].available_at) == (
        DeliveryState.QUEUED,
        NOON_IST + WINDOW,
    )


def test_the_digest_time_is_the_policys() -> None:
    setup = Setup()
    setup.recipient((WA, "+919876543210"), digest_mode=DigestMode.DAILY)
    EnqueueNotifications(setup.store, digest=DigestPolicy.parse("18:00"), clock=setup.clock).run(
        created()
    )
    (held,) = setup.store.notifications_of(TENANT)
    assert held.available_at == datetime(2026, 9, 28, 12, 30, tzinfo=UTC), "18:00 IST today"
