"""The WhatsApp Cloud API adapter: free text inside the 24-hour window, an approved template
outside it, and no call at all for a template Meta has not approved."""

import json
from dataclasses import replace
from datetime import timedelta

import httpx2
import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError
from domain_kernel.notifications import DeliveryStatus
from notification.domain.channels import OutboundMessage, outbound, session_open
from notification.domain.ids import DispatchId
from notification.domain.templates import TemplateStatus, find_template
from notification.infrastructure.whatsapp import (
    DisabledChannel,
    WhatsAppCloudChannel,
    template_payload,
)
from notification.testing import NOON_IST

PHONE = "+919876543210"
VALUES = {
    "business_name": "Acme Traders",
    "title": "File GSTR-3B",
    "due_date": "20 Oct 2026",
    "steps": "Reconcile\nFile",
}


def message(*, window: bool, approved: bool = False, language: str = "en") -> OutboundMessage:
    built = outbound(
        "obligation_due_soon",
        Channel.WHATSAPP,
        language,
        VALUES,
        recipient=PHONE,
        dedupe_key=DedupeKey("d" * 64),
        session_open=window,
        dispatch_id=DispatchId.new(),
    )
    if not approved:
        return built
    return replace(built, template=replace(built.template, status=TemplateStatus.APPROVED))


class Graph:
    """The Graph API as an httpx2 mock: records every call and answers with a message id."""

    def __init__(self, response: httpx2.Response | None = None) -> None:
        self.calls: list[httpx2.Request] = []
        self._response = response

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if request.headers["authorization"] != "Bearer tok":
            return httpx2.Response(401, json={"error": {"message": "bad token"}})
        return self._response or httpx2.Response(200, json={"messages": [{"id": "wamid.X"}]})

    def channel(self, token: str = "tok") -> WhatsAppCloudChannel:
        client = httpx2.Client(transport=httpx2.MockTransport(self))
        return WhatsAppCloudChannel("42", token, client=client, clock=lambda: NOON_IST)

    def body(self, index: int = 0) -> dict[str, object]:
        loaded: dict[str, object] = json.loads(self.calls[index].content)
        return loaded


def test_an_open_window_sends_the_rendered_text() -> None:
    graph = Graph()
    channel = graph.channel()
    receipt = channel.deliver(message(window=True))
    assert (receipt.status, receipt.provider_message_id) == (DeliveryStatus.SENT, "wamid.X")
    assert graph.calls[0].url.path == "/v21.0/42/messages"
    body = graph.body()
    assert (body["type"], body["to"]) == ("text", PHONE)
    text = body["text"]
    assert isinstance(text, dict)
    assert text["body"].startswith("Acme Traders: File GSTR-3B is due on 20 Oct 2026.")
    channel.close()


def test_a_closed_window_with_an_approved_template_sends_the_template() -> None:
    graph = Graph()
    receipt = graph.channel().deliver(message(window=False, approved=True, language="hi"))
    assert receipt.status is DeliveryStatus.SENT
    body = graph.body()
    assert body["type"] == "template"
    assert body["template"] == {
        "name": "cw_obligation_due_soon_hi",
        "language": {"code": "hi"},
        "components": [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": value}
                    for value in ("Acme Traders", "File GSTR-3B", "20 Oct 2026", "Reconcile File")
                ],
            }
        ],
    }, "the values in placeholder order, each on one line"


def test_a_closed_window_with_a_draft_template_fails_without_a_call() -> None:
    graph = Graph()
    draft = message(window=False)
    assert not draft.deliverable
    receipt = graph.channel().deliver(draft)
    assert receipt.status is DeliveryStatus.FAILED
    assert receipt.error == (
        "whatsapp: outside the 24-hour customer service window and template "
        "cw_obligation_due_soon_en is draft, not approved"
    )
    assert graph.calls == []


def test_graph_errors_and_transport_errors_are_failed_receipts() -> None:
    graph = Graph()
    bad = graph.channel(token="nope").deliver(message(window=True))
    assert bad.status is DeliveryStatus.FAILED
    assert bad.error.startswith("401")

    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    client = httpx2.Client(transport=httpx2.MockTransport(down))
    receipt = WhatsAppCloudChannel("42", "tok", client=client).deliver(message(window=True))
    assert receipt.status is DeliveryStatus.FAILED
    assert "transport" in receipt.error


def test_the_disabled_channel_fails_with_its_reason() -> None:
    receipt = DisabledChannel("off", clock=lambda: NOON_IST).deliver(message(window=True))
    assert (receipt.status, receipt.error) == (DeliveryStatus.FAILED, "off")


def test_the_window_is_24_hours_from_the_last_inbound_message() -> None:
    assert not session_open(None, NOON_IST)
    assert session_open(NOON_IST - timedelta(hours=23, minutes=59), NOON_IST)
    assert not session_open(NOON_IST - timedelta(hours=24), NOON_IST)
    email = outbound(
        "obligation_due_soon",
        Channel.EMAIL,
        "en",
        VALUES,
        recipient="owner@example.com",
        dedupe_key=DedupeKey("e" * 64),
        session_open=False,
        dispatch_id=DispatchId.new(),
    )
    assert email.deliverable, "email has no window"
    assert not email.needs_template


def test_template_payload_shape() -> None:
    payload = template_payload(PHONE, "cw_obligation_due_soon_en", "en", ["Acme", "GSTR-3B"])
    template = payload["template"]
    assert isinstance(template, dict)
    assert template["name"] == "cw_obligation_due_soon_en"
    assert template["components"][0]["parameters"][1] == {"type": "text", "text": "GSTR-3B"}


def test_an_approved_template_needs_its_meta_name() -> None:
    unnamed = find_template("opt_in_confirmed", Channel.WHATSAPP, "en")
    assert unnamed.meta_name == ""
    built = outbound(
        "opt_in_confirmed",
        Channel.WHATSAPP,
        "en",
        {},
        recipient=PHONE,
        dedupe_key=DedupeKey("f" * 64),
        session_open=False,
        dispatch_id=DispatchId.new(),
    )
    approved = replace(built, template=replace(unnamed, status=TemplateStatus.APPROVED))
    assert not approved.deliverable
    with pytest.raises(InvariantViolationError, match="dispatch_id"):
        OutboundMessage(built.rendered, built.template, (), False, "not an id")  # type: ignore[arg-type]
