from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, RuleVersionId, TenantId
from domain_kernel.notifications import DeliveryReceipt, RenderedMessage
from notification.application.dispatch import Delivery, DeliveryOutcome, DispatchDue
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.application.send import SendNow
from notification.domain.events import NotificationFailed, NotificationSent
from notification.domain.ids import RecipientId
from notification.domain.model import NotificationRequest, Outcome
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import Occasion
from notification.domain.policy import BatchPolicy
from notification.domain.ports import AttemptResult, RuleVersionFacts
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, RecipientRole
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

    def send(self, message: RenderedMessage) -> DeliveryReceipt:
        race, self.race = self.race, None
        if race is not None:
            race()
        return super().send(message)


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

    def consent(self, channel: Channel, address: str, opted_in: bool) -> None:
        SetOptIn(self.store, clock=self.clock).run(
            channel, address, opted_in=opted_in, source=ConsentSource.API
        )

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
) -> ObligationNotice:
    return ObligationNotice(
        tenant_id=tenant,
        business_id=BUSINESS,
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


def test_a_notification_another_dispatcher_sent_meanwhile_is_a_duplicate_send() -> None:
    world = World(window=0)
    world.owner()
    world.enqueue.run(created())
    entries = world.store.work_index.claim(limit=10, now=world.clock.now)
    world.whatsapp.race = lambda: world.dispatch.dispatch(entries, world.clock.now)
    (delivery,) = world.dispatch.dispatch(entries, world.clock.now)
    assert delivery.outcome is DeliveryOutcome.SENT
    assert len(world.whatsapp.sent) == 2
    assert len(world.events(NotificationSent)) == 1, "the notification is recorded once"
    assert world.metrics.duplicates_sent == [WA]
    (again,) = world.dispatch.dispatch(entries, world.clock.now)
    assert again.outcome is DeliveryOutcome.SKIPPED


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
