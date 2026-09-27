"""The WhatsApp Business Cloud API as a ``NotificationChannel``.

``POST https://graph.facebook.com/<version>/<phone_number_id>/messages`` with a bearer token.
A rendered message is sent as free text; a template send (needed outside the 24-hour customer
service window) is the same call with a ``template`` object and is prepared here but only
used when the template's ``meta_name`` is set and approved. The adapter is behind
``CW_WHATSAPP_ENABLED``; with the flag off the composition root wires ``DisabledChannel``.
"""

from collections.abc import Callable
from datetime import datetime

import httpx2

from domain_kernel.events import utc_now
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage

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

    def send(self, message: RenderedMessage) -> DeliveryReceipt:
        body = text_payload(message.recipient, message.body)
        try:
            response = self._client.post(self._url, json=body, headers=self._headers)
        except httpx2.TransportError as exc:
            return DeliveryReceipt(DeliveryStatus.FAILED, self._clock(), error=f"transport: {exc}")
        if response.status_code >= 400:
            return DeliveryReceipt(
                DeliveryStatus.FAILED,
                self._clock(),
                error=f"{response.status_code}: {response.text[:300]}",
            )
        data = response.json()
        messages = data.get("messages") or [{}]
        return DeliveryReceipt(
            DeliveryStatus.SENT, self._clock(), provider_message_id=str(messages[0].get("id", ""))
        )

    def close(self) -> None:
        self._client.close()


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

    def send(self, message: RenderedMessage) -> DeliveryReceipt:
        return DeliveryReceipt(DeliveryStatus.FAILED, self._clock(), error=self._reason)
