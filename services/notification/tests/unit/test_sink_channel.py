"""The sink channel: it records instead of sending, and decides as the real adapters do, so the
24-hour window, quiet hours, dedupe and fallbacks hold on it. Refused outside local and test."""

import json
import stat
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from domain_kernel.notifications import DeliveryStatus
from notification.application.dispatch import DeliveryOutcome, DispatchDue
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.composition import default_channels
from notification.domain.channels import OutboundMessage, outbound
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import DeliveryState
from notification.domain.occasions import Occasion
from notification.domain.policy import BatchPolicy
from notification.domain.ports import RuleVersionFacts
from notification.domain.preferences import ConsentSource, QuietHours
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.routing import ObligationNotice
from notification.infrastructure.memory import MemoryStore
from notification.infrastructure.sink import MESSAGE_ID_PREFIX, SinkChannel
from notification.testing import (
    NIGHT_IST,
    NOON_IST,
    FakeClock,
    FakeRuleVersionReader,
    notification_settings,
)

PHONE = "+910000000001"
MAIL = "owner@demo-traders.invalid"
NO_QUIET_HOURS = QuietHours.parse("00:00", "00:00")
"""What a person who hears at any hour chooses: the two ends equal."""
VALUES = {
    "business_name": "Demo Traders (synthetic)",
    "title": "File GSTR-3B",
    "due_date": "20 Oct 2026",
    "steps": "Reconcile; File",
}
TENANT = TenantId.new()
BUSINESS = BusinessId.new()
RULE = RuleVersionId.new()
FACTS = RuleVersionFacts(
    title="File FORM GSTR-3B every month",
    summary="A synthetic summary for the test.",
    effective_from=date(2026, 4, 1),
    steps=("Reconcile", "File"),
    source_ref="a synthetic source reference",
)


def message(channel: Channel, *, window: bool) -> OutboundMessage:
    return outbound(
        "obligation_due_soon",
        channel,
        "en",
        VALUES,
        recipient=PHONE if channel is Channel.WHATSAPP else MAIL,
        dedupe_key=DedupeKey("d" * 64),
        session_open=window,
        dispatch_id=DispatchId.new(),
    )


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_message_inside_the_window_is_recorded_as_sent(tmp_path: Path) -> None:
    path = tmp_path / "product" / "sink.jsonl"
    sink = SinkChannel(path, clock=lambda: NOON_IST)
    sent = message(Channel.WHATSAPP, window=True)
    receipt = sink.deliver(sent)
    assert receipt.status is DeliveryStatus.SENT
    assert receipt.provider_message_id == f"{MESSAGE_ID_PREFIX}{sent.dispatch_id}"
    (line,) = lines(path)
    assert line["outcome"] == "sent"
    assert (line["channel"], line["recipient"], line["template"]) == (
        "whatsapp",
        PHONE,
        "obligation_due_soon",
    )
    assert (line["template_status"], line["session_open"]) == ("draft", True)
    assert line["provider_message_id"] == receipt.provider_message_id
    assert line["body"] == sent.rendered.body
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_draft_template_outside_the_window_is_refused_as_meta_would(tmp_path: Path) -> None:
    path = tmp_path / "sink.jsonl"
    refused = message(Channel.WHATSAPP, window=False)
    receipt = SinkChannel(path, clock=lambda: NOON_IST).deliver(refused)
    assert receipt.status is DeliveryStatus.FAILED
    assert receipt.error == refused.undeliverable_reason()
    (line,) = lines(path)
    assert (line["outcome"], line["provider_message_id"]) == ("refused", "")
    assert "24-hour customer service window" in line["error"]


def test_an_email_takes_the_rendered_text_of_a_draft(tmp_path: Path) -> None:
    path = tmp_path / "sink.jsonl"
    receipt = SinkChannel(path).deliver(message(Channel.EMAIL, window=False))
    assert receipt.status is DeliveryStatus.SENT
    (line,) = lines(path)
    assert (line["channel"], line["template_status"], line["outcome"]) == ("email", "draft", "sent")
    assert line["subject"]


def test_a_sink_that_cannot_write_fails_the_attempt(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    sink = SinkChannel(blocker / "sink.jsonl")
    receipt = sink.deliver(message(Channel.EMAIL, window=False))
    assert (receipt.status, receipt.error) == (
        DeliveryStatus.FAILED,
        "sink: the message could not be recorded",
    )
    assert sink.deliver(message(Channel.WHATSAPP, window=False)).status is DeliveryStatus.FAILED


def test_the_settings_choose_the_sink_for_both_channels(tmp_path: Path) -> None:
    path = tmp_path / "sink.jsonl"
    chosen = default_channels(
        notification_settings(notification_channels="sink", notification_sink_path=str(path))
    )
    assert set(chosen) == {Channel.WHATSAPP, Channel.EMAIL}
    for adapter in chosen.values():
        assert isinstance(adapter, SinkChannel)
        assert adapter.path == path
    real = default_channels(notification_settings())
    assert not any(isinstance(adapter, SinkChannel) for adapter in real.values())


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_the_sink_is_refused_outside_local_and_test(env: str) -> None:
    with pytest.raises(ValidationError, match="only local and test take it"):
        notification_settings(notification_channels="sink", env=env, auth_mode="token")
    assert notification_settings(env=env, auth_mode="token").notification_channels == "real"


class Owner:
    """A synthetic owner on the memory store: WhatsApp first and email second, both opted in
    with no quiet hours of their own unless ``quiet`` keeps the service's."""

    def __init__(self, store: MemoryStore, clock: FakeClock, *, quiet: bool = False) -> None:
        RegisterRecipient(store, clock=clock).run(
            RecipientRegistration(
                tenant_id=TENANT,
                recipient_id=RecipientId.new(),
                role=RecipientRole.OWNER,
                addresses=[(Channel.WHATSAPP, PHONE), (Channel.EMAIL, MAIL)],
                businesses=[BusinessLink(BUSINESS, "Demo Traders Bengaluru (synthetic)")],
            )
        )
        for channel, address in ((Channel.WHATSAPP, PHONE), (Channel.EMAIL, MAIL)):
            SetOptIn(store, clock=clock).run(
                channel,
                address,
                opted_in=True,
                source=ConsentSource.WEB_ONBOARDING,
                quiet_hours=None if quiet else NO_QUIET_HOURS,
            )


def change_card() -> ObligationNotice:
    return ObligationNotice(
        tenant_id=TENANT,
        business_id=BUSINESS,
        occasion=Occasion.change_card(ObligationId.new(), RULE),
        template_key="change_card",
        params={
            "title": "File GSTR-3B (2026-10)",
            "steps": [],
            "due_at": "2026-11-20T23:59:59+05:30",
            "rule_version_id": str(RULE),
        },
    )


def chain(path: Path, clock: FakeClock) -> tuple[MemoryStore, EnqueueNotifications, DispatchDue]:
    store = MemoryStore()
    sink = SinkChannel(path, clock=clock)
    batch = BatchPolicy(window_seconds=0)
    enqueue = EnqueueNotifications(store, batch=batch, clock=clock)
    dispatch = DispatchDue(
        store,
        store.work_index,
        {Channel.WHATSAPP: sink, Channel.EMAIL: sink},
        rules=FakeRuleVersionReader({RULE: FACTS}),
        web_base_url="http://localhost:3000",
        batch=batch,
        clock=clock,
    )
    return store, enqueue, dispatch


def test_a_change_card_outside_the_window_falls_back_to_email_through_the_sink(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sink.jsonl"
    clock = FakeClock(NOON_IST)
    store, enqueue, dispatch = chain(path, clock)
    Owner(store, clock)
    notice = change_card()
    assert enqueue.run(notice).queued == 1
    assert enqueue.run(notice).duplicates == 1, "a redelivered event queues nothing twice"
    first = dispatch.run()
    assert [delivery.outcome for delivery in first] == [DeliveryOutcome.FAILED]
    second = dispatch.run()
    assert [delivery.outcome for delivery in second] == [DeliveryOutcome.SENT]
    by_channel = {n.channel: n for n in store.notifications_of(TENANT)}
    assert by_channel[Channel.WHATSAPP].state is DeliveryState.FAILED
    email = by_channel[Channel.EMAIL]
    assert (email.state, email.template_key) == (DeliveryState.SENT, "change_card")
    assert email.provider_message_id.startswith(MESSAGE_ID_PREFIX)
    assert [(line["channel"], line["outcome"]) for line in lines(path)] == [
        ("whatsapp", "refused"),
        ("email", "sent"),
    ]


def test_quiet_hours_hold_a_message_before_it_reaches_the_sink(tmp_path: Path) -> None:
    path = tmp_path / "sink.jsonl"
    clock = FakeClock(NIGHT_IST)
    store, enqueue, dispatch = chain(path, clock)
    Owner(store, clock, quiet=True)
    enqueue.run(change_card())
    assert [delivery.outcome for delivery in dispatch.run()] == [DeliveryOutcome.DEFERRED]
    assert not path.exists()
