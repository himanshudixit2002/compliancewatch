from datetime import UTC, datetime

import httpx2
import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from notification.application.preferences import SetOptIn
from notification.application.send import SendNotification
from notification.domain.errors import InvalidAddressError, UnknownChannelError
from notification.domain.events import NotificationFailed, NotificationSent
from notification.domain.model import NotificationRequest, Outcome
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ConsentSource
from notification.infrastructure.memory import MemoryStore
from notification.infrastructure.whatsapp import (
    DisabledChannel,
    WhatsAppCloudChannel,
    template_payload,
)
from notification.testing import NIGHT_IST, NOON_IST, FakeChannel

PHONE = "919876543210"
NORMALISED = "+919876543210"
PARAMS = {"business_name": "Acme", "title": "File GSTR-3B", "due_date": "20 Oct", "steps": "file"}
TENANT = TenantId.new()


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
    def __init__(
        self,
        now: datetime = NOON_IST,
        *,
        store: MemoryStore | None = None,
        channel: FakeChannel | None = None,
    ) -> None:
        self.store = store or MemoryStore()
        self.channel = channel or FakeChannel(clock=lambda: now)
        self.use_case = SendNotification(
            self.store, {Channel.WHATSAPP: self.channel}, clock=lambda: now
        )

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
    work = setup.store.work_row(stored.id)
    assert work is not None
    assert (work.status, work.provider_message_id) == ("done", "fake-1")
    assert setup.store.work_index.tenant_for_provider_message("fake-1") == TENANT


def test_a_repeat_of_the_same_change_is_a_duplicate() -> None:
    setup = Setup()
    setup.opt_in()
    req = request()
    assert setup.use_case.run(req).outcome is Outcome.SENT
    again = setup.use_case.run(req)
    assert again.outcome is Outcome.DUPLICATE
    assert len(setup.channel.sent) == 1
    explicit = DedupeKey("b" * 64)
    assert setup.use_case.run(request(dedupe_key=explicit)).dedupe_key == explicit


def test_one_consent_whatever_form_the_number_takes() -> None:
    setup = Setup()
    setup.opt_in(recipient="+91 98765 43210")
    assert setup.use_case.run(request(recipient="919876543210")).outcome is Outcome.SENT
    with pytest.raises(InvalidAddressError):
        setup.use_case.run(request(recipient="not a number"))


def test_nobody_is_messaged_without_an_opt_in() -> None:
    setup = Setup()
    assert setup.use_case.run(request()).outcome is Outcome.NOT_OPTED_IN
    SetOptIn(setup.store).run(
        Channel.WHATSAPP, PHONE, opted_in=False, source=ConsentSource.WHATSAPP_KEYWORD
    )
    assert setup.use_case.run(request()).outcome is Outcome.NOT_OPTED_IN
    assert setup.channel.sent == []
    assert setup.store.events == []


def test_quiet_hours_defer_to_the_window_end() -> None:
    setup = Setup(now=NIGHT_IST)
    setup.opt_in()
    outcome = setup.use_case.run(request())
    assert outcome.outcome is Outcome.DEFERRED
    assert outcome.scheduled_for == datetime(2026, 9, 29, 2, 30, tzinfo=UTC)
    assert setup.channel.sent == []
    assert setup.store.notifications_of(TENANT) == []


def test_a_failed_delivery_publishes_failed_and_the_retry_can_still_send() -> None:
    setup = Setup()
    setup.opt_in()
    setup.channel.fail_next = 1
    req = request()
    outcome = setup.use_case.run(req, attempt=3)
    assert outcome.outcome is Outcome.FAILED
    (event,) = setup.store.events
    assert isinstance(event, NotificationFailed)
    assert (event.attempts, event.will_retry, event.error) == (3, False, "fake: down")
    assert setup.store.notifications_of(TENANT) == []
    assert setup.use_case.run(req, attempt=1).outcome is Outcome.SENT


def test_language_override_and_unknown_channel() -> None:
    setup = Setup()
    setup.opt_in("hi")
    assert setup.use_case.run(request(language="en")).language == "en"
    SetOptIn(setup.store).run(
        Channel.EMAIL, "a@b.c", opted_in=True, source=ConsentSource.WEB_ONBOARDING
    )
    with pytest.raises(UnknownChannelError):
        setup.use_case.run(request(channel=Channel.EMAIL, recipient="a@b.c"))


class RacingChannel(FakeChannel):
    """Delivers, but a concurrent send of the same key records its notification first."""

    def __init__(self, store: MemoryStore, taken: Notification) -> None:
        super().__init__(clock=lambda: NOON_IST)
        self._store = store
        self._taken = taken

    def send(self, message: RenderedMessage) -> DeliveryReceipt:
        receipt = super().send(message)
        with self._store(self._taken.tenant_id) as unit:
            unit.notifications.add_if_absent(self._taken)
        return receipt


def test_a_send_that_loses_the_race_to_record_publishes_nothing() -> None:
    req = request()
    store = MemoryStore()
    key = SendNotification(store, {}).run(req).dedupe_key  # not opted in: only the key
    taken = Notification.queue(
        tenant_id=TENANT,
        business_id=req.business_id,
        obligation_id=req.obligation_id,
        recipient_id=None,
        channel=Channel.WHATSAPP,
        address=NORMALISED,
        occasion=OccasionKind.MANUAL,
        template_key=req.template_key,
        language="en",
        params=PARAMS,
        dedupe_key=key,
        now=NOON_IST,
    )
    setup = Setup(store=store, channel=RacingChannel(store, taken))
    setup.opt_in()
    assert setup.use_case.run(req).outcome is Outcome.SENT
    assert store.events == []
    assert [n.id for n in store.notifications_of(TENANT)] == [taken.id]


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
