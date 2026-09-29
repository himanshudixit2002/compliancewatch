"""The WhatsApp Business Cloud API as a ``ChannelAdapter``.

``POST https://graph.facebook.com/<version>/<phone_number_id>/messages`` with a bearer token.
Inside the 24-hour customer service window (the person wrote to us within the last day) the
rendered message goes as free text (``text_payload``). Outside it WhatsApp accepts only a
template Meta has approved: the same call with a ``template`` object naming its ``meta_name``
and language and listing its values in order (``template_payload``). A message outside the
window whose template is not approved gets a failed receipt without an HTTP call, since Meta
would refuse it. The adapter is behind ``CW_WHATSAPP_ENABLED``; with the flag off the
composition root wires ``DisabledChannel``.
"""

from collections.abc import Callable
from datetime import datetime

import httpx2

from domain_kernel.events import utc_now
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus
from notification.domain.channels import OutboundMessage
from py_common.logging import get_logger

log = get_logger(__name__)

GRAPH_URL = "https://graph.facebook.com"


class WhatsAppCloudChannel:
    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        *,
        api_version: str = "v21.0",
        client: httpx2.Client | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._url = f"{GRAPH_URL}/{api_version}/{phone_number_id}/messages"
        self._client = client or httpx2.Client(timeout=30.0)
        self._headers = {"authorization": f"Bearer {access_token}"}
        self._clock = clock

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        if not message.deliverable:
            return DeliveryReceipt(
                DeliveryStatus.FAILED, self._clock(), error=message.undeliverable_reason()
            )
        rendered = message.rendered
        if message.session_open:
            body = text_payload(rendered.recipient, rendered.body)
        else:
            body = template_payload(
                rendered.recipient,
                message.template.meta_name,
                message.template.language,
                list(message.ordered_params),
            )
        try:
            response = self._client.post(self._url, json=body, headers=self._headers)
        except httpx2.TransportError as exc:
            return DeliveryReceipt(DeliveryStatus.FAILED, self._clock(), error=f"transport: {exc}")
        if not response.is_success:
            return DeliveryReceipt(
                DeliveryStatus.FAILED,
                self._clock(),
                error=f"{response.status_code}: {response.text[:300]}",
            )
        return DeliveryReceipt(
            DeliveryStatus.SENT, self._clock(), provider_message_id=_message_id(response)
        )

    def close(self) -> None:
        self._client.close()


def _message_id(response: httpx2.Response) -> str:
    """The id Meta gave the message it took, or '' when the answer does not carry one where the
    Graph API puts it. A success is a send either way: retrying it would send the message twice,
    and only the statuses Meta reports for it later go unmatched."""
    try:
        data = response.json()
    except ValueError:
        data = None
    messages = data.get("messages") if isinstance(data, dict) else None
    first = messages[0] if isinstance(messages, list) and messages else None
    message_id = first.get("id") if isinstance(first, dict) else None
    if not isinstance(message_id, str) or not message_id:
        log.warning("notification.whatsapp_message_id_missing", status=response.status_code)
        return ""
    return message_id


def text_payload(to: str, body: str) -> dict[str, object]:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }


def template_payload(
    to: str, meta_name: str, language: str, parameters: list[str]
) -> dict[str, object]:
    """The business-initiated form: an approved template with its body parameters in order."""
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": meta_name,
            "language": {"code": language},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": value} for value in parameters],
                }
            ],
        },
    }


class DisabledChannel:
    """What is wired while the flag is off: every send fails with a clear reason."""

    def __init__(self, reason: str, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._reason = reason
        self._clock = clock

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        return DeliveryReceipt(DeliveryStatus.FAILED, self._clock(), error=self._reason)
