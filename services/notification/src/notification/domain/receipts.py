"""What a provider tells us about a message after it took it: a delivery receipt.

A channel accepting a message is only the start. WhatsApp later reports whether it was
delivered to the phone and read, or failed after all; email providers report a delivery, a
bounce or a complaint. Each report becomes a ``Receipt`` of one ``ReceiptKind`` for the
provider's message id, and ``Notification.apply_receipt`` moves the notification on:

- ``sent``, ``delivered`` and ``read`` only ever move forward (sent, then delivered, then read);
  a report that arrives late or twice changes nothing;
- ``failed``, ``bounced`` and ``complained`` fail a notification that was sent and not yet
  delivered.

``from_whatsapp`` maps the statuses of the WhatsApp Cloud API webhook; a status it does not know
maps to None and is ignored. ``whatsapp_error`` keeps the code and title Meta gave a failure,
never the message.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain_kernel._validation import require_aware, require_instance, require_text


class ReceiptKind(StrEnum):
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    BOUNCED = "bounced"
    """The mailbox does not exist or refuses mail for good."""
    COMPLAINED = "complained"
    """The person marked the message as spam."""


FAILURE_KINDS = frozenset({ReceiptKind.FAILED, ReceiptKind.BOUNCED, ReceiptKind.COMPLAINED})

_WHATSAPP_STATUSES = {
    "sent": ReceiptKind.SENT,
    "delivered": ReceiptKind.DELIVERED,
    "read": ReceiptKind.READ,
    "failed": ReceiptKind.FAILED,
}


def from_whatsapp(status: str) -> ReceiptKind | None:
    """The kind of a WhatsApp status (``sent``, ``delivered``, ``read``, ``failed``); None for
    one the service does not act on, such as ``deleted``."""
    return _WHATSAPP_STATUSES.get(status.strip().lower())


def whatsapp_error(code: int | None, title: str = "") -> str:
    """The error a failed WhatsApp status records, such as 'whatsapp 131047: Re-engagement
    message'."""
    label = "whatsapp" if code is None else f"whatsapp {code}"
    title = " ".join(title.split())
    return f"{label}: {title}" if title else f"{label}: failed after it was sent"


@dataclass(frozen=True, slots=True)
class Receipt:
    """One report about the message the provider knows by ``provider_message_id``."""

    provider_message_id: str
    kind: ReceiptKind
    at: datetime
    error: str = ""
    """Why it failed, for the failure kinds; '' otherwise."""

    def __post_init__(self) -> None:
        require_text(self.provider_message_id, "provider_message_id")
        require_instance(self.kind, ReceiptKind, "kind")
        require_aware(self.at, "at")
        require_instance(self.error, str, "error")

    @property
    def is_failure(self) -> bool:
        return self.kind in FAILURE_KINDS
