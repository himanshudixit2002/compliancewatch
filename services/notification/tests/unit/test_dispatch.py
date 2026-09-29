from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, RuleVersionId, TenantId
from domain_kernel.notifications import DeliveryReceipt
from notification.application.dispatch import Delivery, DeliveryOutcome, DispatchDue
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.application.send import SendNow
from notification.domain.channels import OutboundMessage
from notification.domain.events import NotificationFailed, NotificationSent
from notification.domain.ids import RecipientId
from notification.domain.model import NotificationRequest, Outcome
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import Occasion
from notification.domain.policy import BatchPolicy
from notification.domain.ports import AttemptResult, RuleVersionFacts
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, DigestMode, RecipientRole
from notification.domain.routing import ObligationNotice
from notification.infrastructure.memory import MemoryStore
from notification.testing import (
    NIGHT_IST,
    NOON_IST,
    FakeChannel,
    FakeClock,
    FakeRuleVersionReader,
    RecordingMetrics,
)

TENANT = TenantId.new()
BUSINESS = BusinessId.new()
BETA = BusinessId.new()
RULE = RuleVersionId.new()
WA, EMAIL = Channel.WHATSAPP, Channel.EMAIL
PHONE, MAIL = "+919876543210", "owner@example.com"
WEB = "https://app.example"
FACTS = RuleVersionFacts(
    title="File FORM GSTR-3B every month",
    summary="A monthly filer furnishes FORM GSTR-3B.",
    effective_from=date(2026, 4, 1),
    steps=("Reconcile", "File"),
    source_ref="CGST Rules, 2017, rule 61(1)",
)
MORNING = datetime(2026, 9, 29, 2, 30, tzinfo=UTC)
"""08:00 IST after NIGHT_IST."""


class RacingChannel(FakeChannel):
    """Runs ``race`` once, in the middle of its next delivery: another dispatcher at work."""

    def __init__(self, clock: FakeClock) -> None:
        super().__init__(clock=clock)
        self.race: Callable[[], object] | None = None

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        race, self.race = self.race, None
        if race is not None:
            race()
        return super().deliver(message)


class RaisingChannel(FakeChannel):
    """Raises instead of answering for the addresses in ``broken``, as an adapter with a bug
    would."""

    def __init__(self, clock: FakeClock, broken: set[str]) -> None:
        super().__init__(clock=clock)
        self.broken = broken

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        if message.rendered.recipient in self.broken:
            raise ValueError("Header values may not contain linefeed or carriage return characters")
        return super().deliver(message)


class World:
    def __init__(self, now: datetime = NOON_IST, *, window: int = 300) -> None:
        self.clock = FakeClock(now)
        self.store = MemoryStore()
        self.whatsapp = RacingChannel(self.clock)
        self.email = FakeChannel(clock=self.clock)
        self.rules = FakeRuleVersionReader({RULE: FACTS})
        self.metrics = RecordingMetrics()
        batch = BatchPolicy(window_seconds=window)
        self.enqueue = EnqueueNotifications(
            self.store, batch=batch, metrics=self.metrics, clock=self.clock
        )
        self.dispatch = self.dispatcher({WA: self.whatsapp, EMAIL: self.email}, batch=batch)

    def dispatcher(
        self, channels: dict[Channel, FakeChannel], *, batch: BatchPolicy | None = None
    ) -> DispatchDue:
        return DispatchDue(
            self.store,
            self.store.work_index,
            channels,
            rules=self.rules,
            web_base_url=WEB,
            batch=batch or BatchPolicy(),
            metrics=self.metrics,
            clock=self.clock,
        )

    def owner(
        self, *addresses: tuple[Channel, str], tenant: TenantId = TENANT, language: str = "en"
    ) -> RecipientId:
        recipient_id = RecipientId.new()
        RegisterRecipient(self.store, clock=self.clock).run(
            RecipientRegistration(
                tenant_id=tenant,
                recipient_id=recipient_id,
                role=RecipientRole.OWNER,
                language=language,
                addresses=addresses or ((WA, PHONE), (EMAIL, MAIL)),
                businesses=[BusinessLink(BUSINESS, "Acme Traders")],
            )
        )
        for channel, address in addresses or ((WA, PHONE), (EMAIL, MAIL)):
            self.consent(channel, address, True)
        return recipient_id

    def digest_reader(
        self,
        role: RecipientRole,
        *addresses: tuple[Channel, str],
        org_label: str = "",
        digest_mode: DigestMode = DigestMode.OFF,
    ) -> RecipientId:
        """A recipient who hears by digest, following Acme Traders and Beta Foods."""
        recipient_id = RecipientId.new()
        RegisterRecipient(self.store, clock=self.clock).run(
            RecipientRegistration(
                tenant_id=TENANT,
                recipient_id=recipient_id,
                role=role,
                digest_mode=digest_mode,
                org_label=org_label,
                addresses=addresses,
                businesses=[
                    BusinessLink(BUSINESS, "Acme Traders"),
                    BusinessLink(BETA, "Beta Foods"),
                ],
            )
        )
        for channel, address in addresses:
            self.consent(channel, address, True)
        return recipient_id

    def consent(self, channel: Channel, address: str, opted_in: bool) -> None:
        """Record the consent; an opt-in on WhatsApp is a message the person sent us, so it
        opens the 24-hour window too."""
        SetOptIn(self.store, clock=self.clock).run(
            channel, address, opted_in=opted_in, source=ConsentSource.API
        )
        if opted_in and channel is WA:
            self.wrote(address)

    def wrote(self, address: str = PHONE) -> None:
        """The WhatsApp number wrote to us now."""
        with self.store.shared() as unit:
            unit.preferences.record_inbound(WA, address, self.clock.now)

    def notifications(self, tenant: TenantId = TENANT) -> list[Notification]:
        return self.store.notifications_of(tenant)

    def events(self, kind: type[object]) -> list[object]:
        return [event for event in self.store.events if isinstance(event, kind)]


def created(
    obligation: ObligationId | None = None,
    *,
    rule: RuleVersionId = RULE,
    tenant: TenantId = TENANT,
    title: str = "File GSTR-3B",
    business: BusinessId = BUSINESS,
) -> ObligationNotice:
    return ObligationNotice(
        tenant_id=tenant,
        business_id=business,
        occasion=Occasion.change_card(obligation or ObligationId.new(), rule),
        template_key="change_card",
        params={
            "title": title,
            "steps": [],
            "due_at": "2026-10-20T23:59:59+05:30",
            "rule_version_id": str(rule),
        },
    )


def closed(obligation: ObligationId, *, title: str | None = None) -> ObligationNotice:
    params: dict[str, object] = {
        "closed_at": "2026-10-02T09:12:50+05:30",
        "close_reason": "profile_changed",
        "rule_version_id": str(RULE),
    }
    if title is not None:
        params["title"] = title
    return ObligationNotice(
        tenant_id=TENANT,
        business_id=BUSINESS,
        occasion=Occasion.closure(obligation),
        template_key="obligation_closed",
        params=params,
    )


def outcomes(deliveries: Sequence[Delivery]) -> list[DeliveryOutcome]:
    return [delivery.outcome for delivery in deliveries]


def test_one_change_card_goes_alone_with_the_rule_facts_and_a_link() -> None:
    world = World()
    world.owner()
    obligation = ObligationId.new()
    world.enqueue.run(created(obligation))
    assert world.dispatch.run() == (), "nothing is due inside the batching window"
    world.clock.advance(300)
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    (message,) = world.whatsapp.sent
    assert message.body == (
        "What changed for Acme Traders: A monthly filer furnishes FORM GSTR-3B. It applies to you "
        "from 1 Apr 2026. What to do: Reconcile; File. Due date: 20 Oct 2026. Open "
        f"{WEB}/obligations/{obligation} for details. Reply HELP for help or STOP to opt out."
    )
    (sent,) = world.notifications()
    assert (sent.state, sent.attempts, sent.provider_message_id) == (
        DeliveryState.SENT,
        1,
        "fake-1",
    )
    assert sent.params["summary"] == "A monthly filer furnishes FORM GSTR-3B"
    assert sent.params["rule_version_id"] == str(RULE), "the event's facts are kept"
    work = world.store.work_row(sent.id)
    assert work is not None
    assert (work.status, work.provider_message_id) == ("done", "fake-1")
    (event,) = world.events(NotificationSent)
    assert isinstance(event, NotificationSent)
    assert event.notification_id == sent.id
    assert world.metrics.attempts == [(WA, AttemptResult.SENT)]
    assert world.metrics.lags == [(WA, 0.0)]
    assert world.rules.calls == [RULE]


def test_the_batch_window_gives_one_batch_summary() -> None:
    world = World()
    world.owner()
    other_tenant = TenantId.new()
    world.owner((WA, "+919800000000"), tenant=other_tenant)
    world.enqueue.run(created(title="File GSTR-3B"))
    world.enqueue.run(created(tenant=other_tenant))
    world.clock.advance(100)
    world.enqueue.run(closed(ObligationId.new(), title="File CMP-08"))
    world.clock.advance(200)
    deliveries = world.dispatch.run()
    assert outcomes(deliveries) == [DeliveryOutcome.SENT, DeliveryOutcome.SENT]
    summary = next(m for m in world.whatsapp.sent if m.recipient == PHONE)
    assert summary.body == (
        "Updates for Acme Traders. Changes to your compliance calendar: 2. New - File GSTR-3B; "
        f"Closed - File CMP-08. Open {WEB}/obligations?business_id={BUSINESS} for details. "
        "Reply HELP for help or STOP to opt out."
    )
    first, second = world.notifications()
    assert first.state is second.state is DeliveryState.SENT
    assert first.dispatch_id == second.dispatch_id is not None
    assert first.provider_message_id == second.provider_message_id
    assert second.params["reason"] == "your business profile changed"
    assert len(world.events(NotificationSent)) == 3
    assert [n.state for n in world.notifications(other_tenant)] == [DeliveryState.SENT]


def test_quiet_hours_defer_to_eight_in_the_morning_ist() -> None:
    world = World(NIGHT_IST)
    world.owner()
    world.enqueue.run(created())
    world.clock.advance(300)
    (delivery,) = world.dispatch.run()
    assert (delivery.outcome, delivery.available_at) == (DeliveryOutcome.DEFERRED, MORNING)
    assert world.whatsapp.sent == []
    (held,) = world.notifications()
    assert (held.state, held.available_at, held.attempts) == (DeliveryState.QUEUED, MORNING, 0)
    world.clock.now = MORNING - timedelta(seconds=1)
    assert world.dispatch.run() == ()
    world.clock.now = MORNING
    assert outcomes(world.dispatch.run()) == [DeliveryOutcome.SENT]


def test_retries_run_at_60_and_300_seconds() -> None:
    world = World(window=0)
    world.owner()
    world.whatsapp.fail_next = 2
    world.enqueue.run(created())
    (first,) = world.dispatch.run()
    assert (first.outcome, first.available_at) == (
        DeliveryOutcome.RETRY,
        NOON_IST + timedelta(seconds=60),
    )
    world.clock.advance(59)
    assert world.dispatch.run() == ()
    world.clock.advance(1)
    (second,) = world.dispatch.run()
    assert second.available_at == world.clock.now + timedelta(seconds=300)
    world.clock.advance(300)
    (third,) = world.dispatch.run()
    assert third.outcome is DeliveryOutcome.SENT
    (sent,) = world.notifications()
    assert (sent.state, sent.attempts) == (DeliveryState.SENT, 3)
    failures = world.events(NotificationFailed)
    assert [(e.attempts, e.will_retry) for e in failures if isinstance(e, NotificationFailed)] == [
        (1, True),
        (2, True),
    ]
    assert [result for _, result in world.metrics.attempts] == [
        AttemptResult.RETRY,
        AttemptResult.RETRY,
        AttemptResult.SENT,
    ]


def fail_three_times(world: World) -> None:
    world.whatsapp.fail_next = 3
    world.enqueue.run(created())
    for wait in (0, 60, 300):
        world.clock.advance(wait)
        world.dispatch.run()


def test_the_third_failure_falls_back_to_email() -> None:
    world = World(window=0)
    recipient = world.owner()
    fail_three_times(world)
    failed, fallback = world.notifications()
    assert (failed.state, failed.attempts, failed.error) == (DeliveryState.FAILED, 3, "fake: down")
    last = world.events(NotificationFailed)[-1]
    assert isinstance(last, NotificationFailed)
    assert (last.attempts, last.will_retry) == (3, True)
    assert (fallback.channel, fallback.address, fallback.fallback_of) == (EMAIL, MAIL, failed.id)
    assert (fallback.recipient_id, fallback.state) == (recipient, DeliveryState.QUEUED)
    assert fallback.available_at == world.clock.now
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    (email,) = world.email.sent
    assert email.subject == "What changed for Acme Traders: applies from 1 Apr 2026"
    assert world.notifications()[1].state is DeliveryState.SENT


def test_without_another_address_the_third_failure_is_final() -> None:
    world = World(window=0)
    world.owner((WA, PHONE))
    fail_three_times(world)
    (failed,) = world.notifications()
    assert failed.state is DeliveryState.FAILED
    last = world.events(NotificationFailed)[-1]
    assert isinstance(last, NotificationFailed)
    assert (last.attempts, last.will_retry) == (3, False)
    assert world.metrics.attempts[-1] == (WA, AttemptResult.FAILED)
    work = world.store.work_row(failed.id)
    assert work is not None
    assert work.status == "done"


def test_a_fallback_does_not_fall_back_again() -> None:
    world = World(window=0)
    world.owner()
    fail_three_times(world)
    world.email.fail_next = 3
    for wait in (0, 60, 300):
        world.clock.advance(wait)
        world.dispatch.run()
    assert [n.state for n in world.notifications()] == [DeliveryState.FAILED] * 2
    last = world.events(NotificationFailed)[-1]
    assert isinstance(last, NotificationFailed)
    assert (last.channel, last.will_retry) == (EMAIL, False)


def test_an_opt_out_between_enqueue_and_dispatch_suppresses_the_item() -> None:
    world = World()
    world.owner()
    world.enqueue.run(created())
    world.consent(WA, PHONE, False)
    world.clock.advance(300)
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SUPPRESSED
    (suppressed,) = world.notifications()
    assert (suppressed.state, suppressed.error) == (DeliveryState.SUPPRESSED, "opted out")
    assert world.whatsapp.sent == world.email.sent == []
    assert world.store.events == []
    assert world.metrics.attempts == [(WA, AttemptResult.SUPPRESSED)]
    assert world.dispatch.run() == ()


def test_a_rulebook_outage_reschedules_without_spending_an_attempt() -> None:
    world = World(window=0)
    world.owner()
    world.enqueue.run(created())
    world.rules.down = True
    (delivery,) = world.dispatch.run()
    later = NOON_IST + timedelta(seconds=60)
    assert (delivery.outcome, delivery.available_at) == (DeliveryOutcome.RESCHEDULED, later)
    (waiting,) = world.notifications()
    assert (waiting.state, waiting.attempts, waiting.available_at) == (
        DeliveryState.QUEUED,
        0,
        later,
    )
    assert world.store.events == []
    world.rules.down = False
    world.clock.advance(60)
    assert outcomes(world.dispatch.run()) == [DeliveryOutcome.SENT]
    assert world.notifications()[0].attempts == 1


def test_a_change_card_without_the_rule_facts_goes_as_obligation_created() -> None:
    world = World(window=0)
    world.owner()
    world.enqueue.run(created(rule=RuleVersionId.new()))
    world.dispatch.run()
    (message,) = world.whatsapp.sent
    assert message.body == (
        "Acme Traders: a new obligation applies to you. File GSTR-3B, due 20 Oct 2026. "
        "Reply HELP for help or STOP to opt out."
    )


def test_a_closure_without_a_title_takes_the_earlier_notifications() -> None:
    world = World(window=0)
    world.owner(language="hi")
    obligation = ObligationId.new()
    world.enqueue.run(created(obligation))
    world.dispatch.run()
    world.enqueue.run(closed(obligation))
    world.dispatch.run()
    closure = world.whatsapp.sent[-1]
    assert closure.body.startswith(
        "सूचना: Acme Traders के लिए File GSTR-3B 2 अक्टूबर 2026 को बंद किया गया, क्योंकि आपकी "
        "व्यवसाय प्रोफ़ाइल बदल गई।"
    )


def test_a_message_that_cannot_be_rendered_fails_without_retries() -> None:
    world = World(window=0)
    world.owner((WA, PHONE))
    notice = created()
    world.enqueue.run(
        ObligationNotice(
            tenant_id=TENANT,
            business_id=BUSINESS,
            occasion=notice.occasion,
            template_key="no_such_template",
            params=notice.params,
        )
    )
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.FAILED
    (failed,) = world.notifications()
    assert (failed.state, failed.attempts) == (DeliveryState.FAILED, 1)
    assert failed.error.startswith("not rendered: no template 'no_such_template'")


def test_a_channel_without_an_adapter_is_a_failed_attempt() -> None:
    world = World(window=0)
    world.owner((WA, PHONE))
    world.enqueue.run(created())
    (delivery,) = world.dispatcher({}).run()
    assert delivery.outcome is DeliveryOutcome.RETRY
    assert delivery.receipt is not None
    assert delivery.receipt.error == "no channel adapter for whatsapp"


def test_an_adapter_that_raises_fails_its_attempt_and_the_run_goes_on() -> None:
    world = World(window=0)
    world.owner((EMAIL, MAIL))
    world.owner((EMAIL, "staff@example.com"))
    email = RaisingChannel(world.clock, {MAIL})
    world.enqueue.run(created())
    deliveries = world.dispatcher({WA: world.whatsapp, EMAIL: email}).run()
    assert sorted(outcomes(deliveries)) == [DeliveryOutcome.RETRY, DeliveryOutcome.SENT]
    assert [message.recipient for message in email.sent] == ["staff@example.com"]
    failed = next(n for n in world.notifications() if n.address == MAIL)
    assert (failed.is_pending, failed.attempts) == (True, 1)
    assert failed.error == "email: the channel adapter raised ValueError"
    assert failed.available_at == NOON_IST + timedelta(seconds=60), "the retry policy's backoff"


def test_a_delivery_that_outlasts_its_whole_lease_is_counted_as_a_duplicate_send() -> None:
    world = World(window=0)
    world.owner((WA, PHONE))
    world.enqueue.run(created())
    other = FakeChannel(clock=world.clock)
    second = world.dispatcher({WA: other})

    def stall() -> None:
        world.clock.advance(61)  # the channel call hangs past the lease
        assert outcomes(second.run()) == [DeliveryOutcome.SENT]

    world.whatsapp.race = stall
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    assert (len(world.whatsapp.sent), len(other.sent)) == (1, 1)
    assert len(world.events(NotificationSent)) == 1, "the notification is recorded once"
    assert world.metrics.duplicates_sent == [WA]


class SlowChannel(FakeChannel):
    """Takes ``seconds`` of the clock for every delivery, and runs ``during[n]`` in the middle
    of the n-th, counted from 1."""

    def __init__(self, clock: FakeClock, seconds: float) -> None:
        super().__init__(clock=clock)
        self.clock = clock
        self.seconds = seconds
        self.during: dict[int, Callable[[], object]] = {}
        self.calls = 0

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        self.calls += 1
        self.clock.advance(self.seconds)
        hook = self.during.pop(self.calls, None)
        if hook is not None:
            hook()
        return super().deliver(message)


def test_a_claim_that_outlasts_its_lease_sends_each_message_once() -> None:
    """Five messages of 25 seconds each outlast their claim's 60-second lease. A second
    dispatcher claims, 75 seconds in, the two the first has not reached; the first renews the
    lease of each message just before sending it, so it leaves those two alone."""
    world = World(window=0)
    phones = [f"+9198765000{n:02d}" for n in range(5)]
    for phone in phones:
        world.owner((WA, phone))
    world.enqueue.run(created())
    slow = SlowChannel(world.clock, seconds=25)
    fast = FakeChannel(clock=world.clock)
    second = world.dispatcher({WA: fast})
    slow.during[3] = lambda: outcomes(second.run())
    first = world.dispatcher({WA: slow}).run()
    assert outcomes(first) == [DeliveryOutcome.SENT] * 3 + [DeliveryOutcome.SKIPPED] * 2
    assert (len(slow.sent), len(fast.sent)) == (3, 2)
    assert sorted(message.recipient for message in [*slow.sent, *fast.sent]) == phones
    assert world.metrics.duplicates_sent == []
    assert len(world.events(NotificationSent)) == 5
    assert all(n.state is DeliveryState.SENT for n in world.notifications())


def test_sends_addressed_straight_to_a_number_are_never_gathered() -> None:
    world = World(NIGHT_IST)
    world.consent(WA, PHONE, True)
    send = SendNow(world.store, world.dispatch, clock=world.clock)
    for _ in range(2):
        outcome = send.run(
            NotificationRequest(
                notification_id=NotificationId.new(),
                tenant_id=TENANT,
                obligation_id=ObligationId.new(),
                business_id=BUSINESS,
                channel=WA,
                recipient=PHONE,
                template_key="obligation_due_soon",
                params={"business_name": "Acme", "title": "T", "due_date": "D", "steps": "S"},
            )
        )
        assert outcome.outcome is Outcome.DEFERRED
    world.clock.now = MORNING
    assert outcomes(world.dispatch.run()) == [DeliveryOutcome.SENT, DeliveryOutcome.SENT]
    assert len(world.whatsapp.sent) == 2


def test_work_entries_of_a_notification_that_is_gone_are_completed() -> None:
    world = World(window=0)
    world.owner()
    world.enqueue.run(created())
    (entry,) = world.store.work_index.claim(limit=1, now=world.clock.now)
    with world.store(TENANT) as unit:
        unit.notifications.purge(NOON_IST + timedelta(days=1))
    (delivery,) = world.dispatch.dispatch([entry], world.clock.now)
    assert delivery.outcome is DeliveryOutcome.SKIPPED


NINE_IST = datetime(2026, 9, 29, 3, 30, tzinfo=UTC)
"""09:00 IST the day after NOON_IST: the next digest."""


def test_a_daily_digest_gathers_the_days_notifications_across_businesses() -> None:
    world = World()
    reader = world.digest_reader(RecipientRole.OWNER, (WA, PHONE), digest_mode=DigestMode.DAILY)
    world.enqueue.run(created(title="File GSTR-3B"))
    world.clock.advance(3600)
    world.enqueue.run(created(title="File FSSAI returns", business=BETA))
    world.clock.now = NINE_IST - timedelta(seconds=1)
    assert world.dispatch.run() == (), "held for the digest"
    world.clock.now = NINE_IST
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    (message,) = world.whatsapp.sent
    assert message.body == (
        "Your ComplianceWatch digest for today. Updates: 2. Acme Traders: New - File GSTR-3B; "
        f"Beta Foods: New - File FSSAI returns. Open {WEB}/obligations for details. "
        "Reply HELP for help or STOP to opt out."
    )
    first, second = world.notifications()
    assert first.recipient_id == second.recipient_id == reader
    assert first.state is second.state is DeliveryState.SENT
    assert first.dispatch_id == second.dispatch_id is not None
    assert len(world.events(NotificationSent)) == 2
    assert world.metrics.lags == [(WA, 0.0), (WA, 0.0)], "the wait for the digest is no delay"


def test_a_ca_firm_gets_one_client_digest_even_for_one_notification() -> None:
    world = World()
    world.digest_reader(RecipientRole.CA_ADMIN, (WA, PHONE), org_label="Rao & Co")
    world.enqueue.run(created())
    world.clock.now = NINE_IST
    world.dispatch.run()
    (message,) = world.whatsapp.sent
    assert message.body == (
        "Client digest for Rao & Co. Updates: 1. Clients: 1. Acme Traders: New - File GSTR-3B. "
        f"Open {WEB}/obligations?business_id={BUSINESS} for details. "
        "Reply HELP for help or STOP to opt out."
    )


def test_a_notification_after_the_digest_went_waits_for_the_next_one() -> None:
    world = World()
    world.digest_reader(RecipientRole.CA_STAFF, (WA, PHONE))
    world.enqueue.run(created())
    world.clock.now = NINE_IST
    assert outcomes(world.dispatch.run()) == [DeliveryOutcome.SENT]
    world.clock.advance(30)
    world.enqueue.run(created(title="File GSTR-1", rule=RuleVersionId.new()))
    assert world.dispatch.run() == ()
    world.clock.now = NINE_IST + timedelta(days=1)
    world.wrote()
    assert outcomes(world.dispatch.run()) == [DeliveryOutcome.SENT]
    assert world.whatsapp.sent[1].body.startswith(
        "Client digest for your firm. Updates: 1. Clients: 1. Acme Traders: New - File GSTR-1."
    )


def test_a_digest_and_a_notification_of_the_same_person_go_as_two_messages() -> None:
    world = World()
    world.clock.now = NINE_IST - timedelta(seconds=300)
    reader = world.digest_reader(RecipientRole.OWNER, (WA, PHONE), digest_mode=DigestMode.DAILY)
    world.enqueue.run(created(title="Held for the digest"))
    RegisterRecipient(world.store, clock=world.clock).run(
        RecipientRegistration(
            tenant_id=TENANT,
            recipient_id=reader,
            role=RecipientRole.OWNER,
            addresses=[(WA, PHONE)],
            businesses=[BusinessLink(BUSINESS, "Acme Traders")],
        )
    )
    world.enqueue.run(created(title="Sent on its own", rule=RuleVersionId.new()))
    world.clock.now = NINE_IST
    assert outcomes(world.dispatch.run()) == [DeliveryOutcome.SENT, DeliveryOutcome.SENT]
    bodies = sorted(message.body for message in world.whatsapp.sent)
    assert bodies[0].startswith("Acme Traders: a new obligation applies to you. Sent on its own")
    assert bodies[1].startswith(
        "Your ComplianceWatch digest for today. Updates: 1. "
        "Acme Traders: New - Held for the digest."
    )


def test_a_failed_digest_falls_back_to_a_digest_on_email() -> None:
    world = World()
    world.digest_reader(RecipientRole.CA_ADMIN, (WA, PHONE), (EMAIL, MAIL), org_label="Rao & Co")
    world.enqueue.run(created())
    world.enqueue.run(created(title="File FSSAI returns", business=BETA))
    world.whatsapp.fail_next = 3
    world.clock.now = NINE_IST
    for wait in (0, 60, 300):
        world.clock.advance(wait)
        world.dispatch.run()
    notifications = world.notifications()
    assert [n.state for n in notifications[:2]] == [DeliveryState.FAILED] * 2
    fallbacks = notifications[2:]
    assert {(n.channel, n.state) for n in fallbacks} == {(EMAIL, DeliveryState.DIGEST_PENDING)}
    assert {n.available_at for n in fallbacks} == {world.clock.now}, "due at once"
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    (email,) = world.email.sent
    assert email.subject == "Client digest for Rao & Co"
    lines = email.body.split("\n")
    assert "Acme Traders: New - File GSTR-3B" in lines
    assert "Beta Foods: New - File FSSAI returns" in lines


def test_inside_the_window_whatsapp_takes_the_text_under_the_dispatch_id() -> None:
    world = World(window=0)
    world.owner()
    world.enqueue.run(created())
    world.dispatch.run()
    (message,) = world.whatsapp.delivered
    assert message.session_open
    assert message.template.meta_name == "cw_change_card_en"
    assert message.ordered_params[0] == "Acme Traders"
    (sent,) = world.notifications()
    assert sent.dispatch_id == message.dispatch_id


def test_outside_the_window_a_draft_template_falls_back_to_email_at_once() -> None:
    world = World(window=0)
    world.owner()
    world.clock.advance(25 * 3600)
    world.enqueue.run(created())
    (delivery,) = world.dispatch.run()
    assert delivery.outcome is DeliveryOutcome.FAILED, "no retries: each would fail the same way"
    assert world.whatsapp.sent == []
    by_channel = {n.channel: n for n in world.notifications()}
    assert len(by_channel) == 2, "both are made at the same instant, so order them by channel"
    failed, fallback = by_channel[WA], by_channel[EMAIL]
    assert (failed.state, failed.attempts) == (DeliveryState.FAILED, 1)
    assert failed.error == (
        "whatsapp: outside the 24-hour customer service window and template cw_change_card_en "
        "is draft, not approved"
    )
    (event,) = world.events(NotificationFailed)
    assert isinstance(event, NotificationFailed)
    assert event.will_retry
    assert (fallback.channel, fallback.available_at) == (EMAIL, world.clock.now)
    assert outcomes(world.dispatch.run()) == [DeliveryOutcome.SENT]
    assert len(world.email.sent) == 1
