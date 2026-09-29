"""Delivery receipts on the memory store: statuses find their notifications through the work
index, only move them forward, and an asynchronous failure falls back to the next address."""

from dataclasses import replace
from datetime import timedelta

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from domain_kernel.notifications import DeliveryReceipt
from notification.application.dispatch import DispatchDue
from notification.application.email_feedback import FeedbackKind, ReceiveEmailFeedback
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.receipts import InboundTime, Reconciled, ReconcileReceipts
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.domain.channels import OutboundMessage
from notification.domain.events import NotificationFailed
from notification.domain.ids import RecipientId
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import Occasion
from notification.domain.policy import BatchPolicy
from notification.domain.ports import ReceiptResult
from notification.domain.preferences import ConsentSource, Suppression, SuppressionReason
from notification.domain.receipts import (
    Receipt,
    ReceiptKind,
    from_whatsapp,
    whatsapp_error,
)
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.routing import ObligationNotice
from notification.infrastructure.memory import MemoryStore
from notification.infrastructure.ses_feedback import SnsFeedbackReader
from notification.testing import (
    NOON_IST,
    FakeChannel,
    FakeClock,
    FakeRuleVersionReader,
    FakeSns,
    RecordingMetrics,
    ses_report,
)

TENANT = TenantId.new()
BUSINESS = BusinessId.new()
WA, EMAIL = Channel.WHATSAPP, Channel.EMAIL
PHONE, MAIL = "+919876543210", "owner@example.com"
LATER = NOON_IST + timedelta(minutes=5)


class World:
    def __init__(self, *addresses: tuple[Channel, str]) -> None:
        self.clock = FakeClock()
        self.store = MemoryStore()
        self.metrics = RecordingMetrics()
        self.whatsapp = FakeChannel(clock=self.clock)
        self.email = FakeChannel(clock=self.clock)
        self.receipts = ReconcileReceipts(
            self.store, self.store.work_index, metrics=self.metrics, clock=self.clock
        )
        self.dispatch = DispatchDue(
            self.store,
            self.store.work_index,
            {WA: self.whatsapp, EMAIL: self.email},
            rules=FakeRuleVersionReader(),
            web_base_url="https://app.example",
            clock=self.clock,
        )
        RegisterRecipient(self.store, clock=self.clock).run(
            RecipientRegistration(
                tenant_id=TENANT,
                recipient_id=RecipientId.new(),
                role=RecipientRole.OWNER,
                addresses=addresses or ((WA, PHONE), (EMAIL, MAIL)),
                businesses=[BusinessLink(BUSINESS, "Acme Traders")],
            )
        )
        for channel, address in addresses or ((WA, PHONE), (EMAIL, MAIL)):
            SetOptIn(self.store, clock=self.clock).run(
                channel, address, opted_in=True, source=ConsentSource.API
            )
        self.receipts.run(WA, inbound=[InboundTime(PHONE, NOON_IST)])

    def send(self, *titles: str) -> list[Notification]:
        """Queue one change card per title and dispatch them together as one message."""
        enqueue = EnqueueNotifications(
            self.store, batch=BatchPolicy(window_seconds=0), clock=self.clock
        )
        for title in titles:
            rule = RuleVersionId.new()
            enqueue.run(
                ObligationNotice(
                    tenant_id=TENANT,
                    business_id=BUSINESS,
                    occasion=Occasion.change_card(ObligationId.new(), rule),
                    template_key="change_card",
                    params={"title": title, "rule_version_id": str(rule)},
                )
            )
        self.dispatch.run()
        return self.notifications()

    def notifications(self) -> list[Notification]:
        return self.store.notifications_of(TENANT)

    def status(self, kind: ReceiptKind, message_id: str = "fake-1", **changes: object) -> Receipt:
        values: dict[str, object] = {"provider_message_id": message_id, "kind": kind, "at": LATER}
        values.update(changes)
        return Receipt(**values)  # type: ignore[arg-type]


def test_delivered_and_read_apply_to_every_notification_the_message_carried() -> None:
    world = World()
    batch = world.send("File GSTR-3B", "File GSTR-1")
    assert {n.provider_message_id for n in batch} == {"fake-1"}
    delivered = world.receipts.run(WA, [world.status(ReceiptKind.DELIVERED)])
    assert delivered == Reconciled(applied=1)
    assert {n.state for n in world.notifications()} == {DeliveryState.DELIVERED}
    read = world.status(ReceiptKind.READ, at=LATER + timedelta(minutes=1))
    late = world.status(ReceiptKind.DELIVERED, at=LATER + timedelta(minutes=2))
    assert world.receipts.run(WA, [late, read]) == Reconciled(applied=1, unchanged=1)
    assert {n.state for n in world.notifications()} == {DeliveryState.READ}
    assert world.receipts.run(WA, [read]) == Reconciled(unchanged=1), "a redelivery"
    assert world.metrics.receipts[-1] == (WA, ReceiptKind.READ, ReceiptResult.UNCHANGED)
    assert world.store.events[-1].topic == "notification.sent", "delivery publishes nothing"


def test_an_asynchronous_failure_falls_back_to_the_next_address() -> None:
    world = World()
    (sent,) = world.send("File GSTR-3B")
    world.clock.advance(300)
    failure = world.status(ReceiptKind.FAILED, error=whatsapp_error(131026, "Undeliverable"))
    assert world.receipts.run(WA, [failure]) == Reconciled(applied=1)
    failed, fallback = world.notifications()
    assert (failed.id, failed.state, failed.error) == (
        sent.id,
        DeliveryState.FAILED,
        "whatsapp 131026: Undeliverable",
    )
    event = world.store.events[-1]
    assert isinstance(event, NotificationFailed)
    assert (event.will_retry, event.attempts) == (True, 1)
    assert (fallback.channel, fallback.address, fallback.fallback_of) == (EMAIL, MAIL, sent.id)
    assert (fallback.state, fallback.available_at) == (DeliveryState.QUEUED, world.clock.now)
    world.dispatch.run()
    (email,) = world.email.sent
    assert email.recipient == MAIL
    assert world.receipts.run(WA, [failure]) == Reconciled(unchanged=1)


def test_without_another_address_an_asynchronous_failure_is_final() -> None:
    world = World((WA, PHONE))
    world.send("File GSTR-3B")
    world.receipts.run(WA, [world.status(ReceiptKind.FAILED)])
    (failed,) = world.notifications()
    assert (failed.state, failed.error) == (DeliveryState.FAILED, "failed after it was sent")
    event = world.store.events[-1]
    assert isinstance(event, NotificationFailed)
    assert not event.will_retry


def test_an_unknown_message_id_is_counted_and_ignored() -> None:
    world = World()
    world.send("File GSTR-3B")
    reply = world.status(ReceiptKind.DELIVERED, "wamid.bot-reply")
    email_id = world.status(ReceiptKind.DELIVERED)
    assert world.receipts.run(WA, [reply]) == Reconciled(unknown=1)
    assert world.metrics.receipts == [(WA, ReceiptKind.DELIVERED, ReceiptResult.UNKNOWN)]
    assert world.receipts.run(EMAIL, [email_id]) == Reconciled(unchanged=1), "another channel"
    assert world.notifications()[0].state is DeliveryState.SENT


def test_inbound_times_open_the_window_by_normalised_address() -> None:
    world = World()
    recorded = world.receipts.run(
        WA,
        inbound=[
            InboundTime("919876543210", LATER),
            InboundTime("+91 98765 43210", NOON_IST - timedelta(hours=1)),
            InboundTime("call me maybe", LATER),
        ],
    )
    assert recorded == Reconciled(inbound=2)
    with world.store.shared() as unit:
        assert unit.preferences.last_inbound_at(WA, PHONE) == LATER, "an older time is ignored"
    assert world.receipts.run(WA) == Reconciled()


def test_whatsapp_statuses_and_errors() -> None:
    assert [from_whatsapp(status) for status in ("sent", "Delivered", "read", "failed")] == [
        ReceiptKind.SENT,
        ReceiptKind.DELIVERED,
        ReceiptKind.READ,
        ReceiptKind.FAILED,
    ]
    assert from_whatsapp("deleted") is None
    assert whatsapp_error(None) == "whatsapp: failed after it was sent"
    assert whatsapp_error(131047, "Re-engagement\n message") == (
        "whatsapp 131047: Re-engagement message"
    )
    assert Receipt("wamid.1", ReceiptKind.BOUNCED, LATER).is_failure
    assert not Receipt("wamid.1", ReceiptKind.READ, LATER).is_failure


class SmtpLikeChannel(FakeChannel):
    """Names the dispatch id as the provider's message id, as the SMTP channel does."""

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        receipt = super().deliver(message)
        return replace(receipt, provider_message_id=str(message.dispatch_id))


class MailWorld(World):
    def __init__(self) -> None:
        super().__init__((EMAIL, MAIL))
        self.email = SmtpLikeChannel(clock=self.clock)
        self.dispatch = DispatchDue(
            self.store,
            self.store.work_index,
            {WA: self.whatsapp, EMAIL: self.email},
            rules=FakeRuleVersionReader(),
            web_base_url="https://app.example",
            clock=self.clock,
        )
        self.sns = SNS
        self.feedback = ReceiveEmailFeedback(
            SnsFeedbackReader(SNS.certificates, clock=self.clock), self.receipts
        )

    def report(self, notification_type: str, *, matched: bool = True, **options: str) -> str:
        (sent,) = [n for n in self.notifications() if n.dispatch_id is not None]
        dispatch = str(sent.dispatch_id) if matched else ""
        return SNS.notification(
            ses_report(notification_type, MAIL.upper(), dispatch_id=dispatch, **options)
        )

    def suppression(self) -> Suppression | None:
        with self.store.shared() as unit:
            return unit.suppressions.get(EMAIL, MAIL)


SNS = FakeSns()


def test_an_ses_permanent_bounce_suppresses_the_mailbox_and_fails_the_email() -> None:
    world = MailWorld()
    world.send("File GSTR-3B")
    outcome = world.feedback.run(world.report("Bounce"))
    assert outcome.kind is FeedbackKind.REPORT
    assert outcome.reconciled == Reconciled(applied=1, suppressed=1)
    (failed,) = world.notifications()
    assert (failed.state, failed.error) == (
        DeliveryState.FAILED,
        "email bounced: Permanent/General",
    )
    event = world.store.events[-1]
    assert isinstance(event, NotificationFailed)
    assert not event.will_retry, "no address after the email one"
    suppression = world.suppression()
    assert suppression is not None
    assert (suppression.reason, suppression.detail) == (
        SuppressionReason.BOUNCE,
        "Permanent/General",
    )
    assert world.send("File GSTR-1") == [failed], "nothing is queued to a suppressed mailbox"


def test_a_complaint_after_delivery_suppresses_and_keeps_the_record() -> None:
    world = MailWorld()
    world.send("File GSTR-3B")
    delivered = world.feedback.run(world.report("Delivery"))
    assert delivered.reconciled == Reconciled(applied=1)
    complained = world.feedback.run(world.report("Complaint"))
    assert complained.reconciled == Reconciled(unchanged=1, suppressed=1)
    assert world.notifications()[0].state is DeliveryState.DELIVERED
    suppression = world.suppression()
    assert suppression is not None
    assert suppression.reason is SuppressionReason.COMPLAINT


def test_a_report_without_the_original_headers_still_closes_the_mailbox() -> None:
    world = MailWorld()
    world.send("File GSTR-3B")
    outcome = world.feedback.run(world.report("Bounce", matched=False))
    assert outcome.reconciled == Reconciled(suppressed=1)
    assert world.notifications()[0].state is DeliveryState.SENT
    assert world.suppression() is not None


def test_a_transient_bounce_fails_the_email_but_leaves_the_mailbox_open() -> None:
    world = MailWorld()
    world.send("File GSTR-3B")
    outcome = world.feedback.run(world.report("Bounce", bounce_type="Transient"))
    assert outcome.reconciled == Reconciled(applied=1)
    assert world.notifications()[0].error == "email failed: Transient/General"
    assert world.suppression() is None


def test_a_subscription_confirmation_and_an_ignored_report_change_nothing() -> None:
    world = MailWorld()
    confirmation = world.feedback.run(SNS.confirmation())
    assert confirmation.kind is FeedbackKind.SUBSCRIPTION_CONFIRMATION
    ignored = world.feedback.run(SNS.notification({"eventType": "Open"}))
    assert (ignored.kind, ignored.reconciled) == (FeedbackKind.IGNORED, Reconciled())
