from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from notification.application.dispatch import DispatchDue
from notification.application.preferences import SetOptIn
from notification.application.send import SendNow
from notification.domain.errors import (
    InvalidAddressError,
    MissingPlaceholderError,
    UnknownChannelError,
    UnknownTemplateError,
)
from notification.domain.events import NotificationFailed, NotificationSent
from notification.domain.model import NotificationRequest, Outcome
from notification.domain.notification import DeliveryState
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ConsentSource, Suppression, SuppressionReason
from notification.domain.repository import WorkEntry
from notification.infrastructure.memory import MemoryStore
from notification.infrastructure.whatsapp import (
    DisabledChannel,
    WhatsAppCloudChannel,
    template_payload,
)
from notification.testing import (
    NIGHT_IST,
    NOON_IST,
    FakeChannel,
    FakeClock,
    FakeRuleVersionReader,
)

PHONE = "919876543210"
NORMALISED = "+919876543210"
PARAMS = {"business_name": "Acme", "title": "File GSTR-3B", "due_date": "20 Oct", "steps": "file"}
TENANT = TenantId.new()
WEB = "https://app.example"


def request(**changes: object) -> NotificationRequest:
    values: dict[str, object] = {
        "notification_id": NotificationId.new(),
        "tenant_id": TENANT,
        "obligation_id": ObligationId.new(),
        "business_id": BusinessId.new(),
        "channel": Channel.WHATSAPP,
        "recipient": PHONE,
        "template_key": "obligation_due_soon",
        "params": PARAMS,
    }
    values.update(changes)
    return NotificationRequest(**values)  # type: ignore[arg-type]


class Setup:
    def __init__(self, now: datetime = NOON_IST) -> None:
        self.clock = FakeClock(now)
        self.store = MemoryStore()
        self.channel = FakeChannel(clock=self.clock)
        self.dispatch = DispatchDue(
            self.store,
            self.store.work_index,
            {Channel.WHATSAPP: self.channel},
            rules=FakeRuleVersionReader(),
            web_base_url=WEB,
            clock=self.clock,
        )
        self.use_case = SendNow(self.store, self.dispatch, clock=self.clock)

    def opt_in(self, language: str = "en", recipient: str = PHONE) -> None:
        SetOptIn(self.store, clock=lambda: NOON_IST).run(
            Channel.WHATSAPP, recipient, opted_in=True, source=ConsentSource.API, language=language
        )


def test_sends_once_records_the_notification_and_publishes_sent() -> None:
    setup = Setup()
    setup.opt_in("hi")
    req = request()
    first = setup.use_case.run(req)
    assert first.outcome is Outcome.SENT
    assert first.language == "hi"
    assert first.receipt is not None
    assert first.receipt.provider_message_id == "fake-1"
    assert setup.channel.sent[0].language == "hi"
    assert setup.channel.sent[0].recipient == NORMALISED
    (event,) = setup.store.events
    assert isinstance(event, NotificationSent)
    assert event.dedupe_key == first.dedupe_key.value
    assert event.language == "hi"
    assert event.notification_id == req.notification_id
    (stored,) = setup.store.notifications_of(TENANT)
    assert (stored.id, stored.state, stored.occasion) == (
        req.notification_id,
        DeliveryState.SENT,
        OccasionKind.MANUAL,
    )
    assert (stored.address, stored.provider_message_id, stored.attempts) == (
        NORMALISED,
        "fake-1",
        1,
    )
    assert dict(stored.params) == PARAMS, "a manual send keeps the values it was given"
    work = setup.store.work_row(stored.id)
    assert work is not None
    assert (work.status, work.provider_message_id) == ("done", "fake-1")
    assert setup.store.work_index.tenant_for_provider_message("fake-1") == TENANT
    assert setup.store.work_index.claim(limit=10, now=NOON_IST + timedelta(hours=1)) == []


def test_a_repeat_of_the_same_change_is_a_duplicate() -> None:
    setup = Setup()
    setup.opt_in()
    req = request()
    assert setup.use_case.run(req).outcome is Outcome.SENT
    again = setup.use_case.run(req)
    assert again.outcome is Outcome.DUPLICATE
    same_id = setup.use_case.run(request(notification_id=req.notification_id))
    assert same_id.outcome is Outcome.DUPLICATE, "an id already used is not queued twice"
    assert len(setup.channel.sent) == 1
    explicit = DedupeKey("b" * 64)
    assert setup.use_case.run(request(dedupe_key=explicit)).dedupe_key == explicit


def test_one_consent_whatever_form_the_number_takes() -> None:
    setup = Setup()
    setup.opt_in(recipient="+91 98765 43210")
    assert setup.use_case.run(request(recipient="919876543210")).outcome is Outcome.SENT
    with pytest.raises(InvalidAddressError):
        setup.use_case.run(request(recipient="not a number"))


def test_nobody_is_messaged_without_an_opt_in_or_at_a_suppressed_address() -> None:
    setup = Setup()
    assert setup.use_case.run(request()).outcome is Outcome.NOT_OPTED_IN
    SetOptIn(setup.store).run(
        Channel.WHATSAPP, PHONE, opted_in=False, source=ConsentSource.WHATSAPP_KEYWORD
    )
    assert setup.use_case.run(request()).outcome is Outcome.NOT_OPTED_IN
    setup.opt_in()
    with setup.store.shared() as unit:
        unit.suppressions.add(
            Suppression(Channel.WHATSAPP, NORMALISED, SuppressionReason.MANUAL, NOON_IST)
        )
    assert setup.use_case.run(request()).outcome is Outcome.NOT_OPTED_IN
    assert setup.channel.sent == []
    assert setup.store.events == []
    assert setup.store.notifications_of(TENANT) == []


def test_quiet_hours_queue_the_send_for_their_end() -> None:
    setup = Setup(now=NIGHT_IST)
    setup.opt_in()
    req = request()
    outcome = setup.use_case.run(req)
    morning = datetime(2026, 9, 29, 2, 30, tzinfo=UTC)
    assert outcome.outcome is Outcome.DEFERRED
    assert outcome.scheduled_for == morning
    assert setup.channel.sent == []
    (queued,) = setup.store.notifications_of(TENANT)
    assert (queued.state, queued.available_at) == (DeliveryState.QUEUED, morning)
    assert setup.use_case.run(req).outcome is Outcome.DUPLICATE
    setup.clock.now = morning
    (delivery,) = setup.dispatch.run()
    assert delivery.notification_ids == (req.notification_id,)
    assert len(setup.channel.sent) == 1, "the dispatcher sends it when quiet hours end"


def test_a_failed_delivery_stays_queued_and_the_service_retries_it() -> None:
    setup = Setup()
    setup.opt_in()
    setup.channel.fail_next = 1
    req = request()
    outcome = setup.use_case.run(req)
    assert outcome.outcome is Outcome.FAILED
    assert outcome.receipt is not None
    assert outcome.receipt.error == "fake: down"
    assert outcome.scheduled_for is None
    (event,) = setup.store.events
    assert isinstance(event, NotificationFailed)
    assert (event.attempts, event.will_retry, event.error) == (1, True, "fake: down")
    (queued,) = setup.store.notifications_of(TENANT)
    assert (queued.state, queued.attempts) == (DeliveryState.QUEUED, 1)
    assert queued.available_at == NOON_IST + timedelta(seconds=60)
    assert setup.use_case.run(req).outcome is Outcome.DUPLICATE, "the caller does not retry"
    setup.clock.advance(60)
    setup.dispatch.run()
    (sent,) = setup.store.notifications_of(TENANT)
    assert (sent.state, sent.attempts) == (DeliveryState.SENT, 2)


class ClaimingChannel(FakeChannel):
    """Tries to claim work while it delivers, as a dispatcher loop running meanwhile would."""

    def __init__(self, store: MemoryStore, clock: FakeClock) -> None:
        super().__init__(clock=clock)
        self._store = store
        self.claimed: list[WorkEntry] = []

    def send(self, message: RenderedMessage) -> DeliveryReceipt:
        self.claimed.extend(self._store.work_index.claim(limit=10, now=NOON_IST))
        return super().send(message)


def test_the_send_is_leased_so_the_dispatcher_loop_leaves_it_alone() -> None:
    setup = Setup()
    setup.opt_in()
    channel = ClaimingChannel(setup.store, setup.clock)
    dispatch = DispatchDue(
        setup.store,
        setup.store.work_index,
        {Channel.WHATSAPP: channel},
        rules=FakeRuleVersionReader(),
        web_base_url=WEB,
        clock=setup.clock,
    )
    outcome = SendNow(setup.store, dispatch, clock=setup.clock).run(request())
    assert outcome.outcome is Outcome.SENT
    assert channel.claimed == [], "no claim while the send holds its lease"


def test_nothing_is_stored_for_an_unknown_channel_template_or_value() -> None:
    setup = Setup()
    setup.opt_in("hi")
    assert setup.use_case.run(request(language="en")).language == "en"
    SetOptIn(setup.store).run(
        Channel.EMAIL, "a@b.c", opted_in=True, source=ConsentSource.WEB_ONBOARDING
    )
    with pytest.raises(UnknownChannelError):
        setup.use_case.run(request(channel=Channel.EMAIL, recipient="a@b.c"))
    with pytest.raises(UnknownTemplateError):
        setup.use_case.run(request(template_key="nope"))
    with pytest.raises(MissingPlaceholderError):
        setup.use_case.run(request(params={"title": "x"}))
    assert len(setup.store.notifications_of(TENANT)) == 1


def test_disabled_channel_fails_with_its_reason() -> None:
    message = RenderedMessage(Channel.WHATSAPP, PHONE, "hi", DedupeKey("c" * 64))
    receipt = DisabledChannel("off", clock=lambda: NOON_IST).send(message)
    assert (receipt.status, receipt.error) == (DeliveryStatus.FAILED, "off")


def test_whatsapp_cloud_channel_posts_and_reads_the_message_id() -> None:
    calls: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        calls.append(req)
        if req.headers["authorization"] != "Bearer tok":
            return httpx2.Response(401, json={"error": {"message": "bad token"}})
        return httpx2.Response(200, json={"messages": [{"id": "wamid.X"}]})

    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    channel = WhatsAppCloudChannel("42", "tok", client=client, clock=lambda: NOON_IST)
    message = RenderedMessage(Channel.WHATSAPP, PHONE, "hello", DedupeKey("d" * 64))
    receipt = channel.send(message)
    assert (receipt.status, receipt.provider_message_id) == (DeliveryStatus.SENT, "wamid.X")
    assert calls[0].url.path == "/v21.0/42/messages"
    bad = WhatsAppCloudChannel("42", "nope", client=client, clock=lambda: NOON_IST).send(message)
    assert bad.status is DeliveryStatus.FAILED
    assert bad.error.startswith("401")
    channel.close()


def test_whatsapp_cloud_channel_transport_errors_are_failed_receipts() -> None:
    def handler(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    receipt = WhatsAppCloudChannel("42", "tok", client=client).send(
        RenderedMessage(Channel.WHATSAPP, PHONE, "x", DedupeKey("e" * 64))
    )
    assert receipt.status is DeliveryStatus.FAILED
    assert "transport" in receipt.error


def test_template_payload_shape() -> None:
    payload = template_payload(PHONE, "cw_obligation_due_soon_en", "en", ["Acme", "GSTR-3B"])
    template = payload["template"]
    assert isinstance(template, dict)
    assert template["name"] == "cw_obligation_due_soon_en"
    assert template["components"][0]["parameters"][1] == {"type": "text", "text": "GSTR-3B"}
