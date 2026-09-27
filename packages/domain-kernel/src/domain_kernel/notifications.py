"""A rendered message and the receipt a channel returns."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    """Ready to send. Email needs a subject; the dedupe key stops repeats."""

    channel: Channel
    recipient: str
    body: str
    dedupe_key: DedupeKey
    subject: str = ""
    language: str = "en"

    def __post_init__(self) -> None:
        require_instance(self.channel, Channel, "channel")
        require_text(self.recipient, "recipient")
        require_text(self.body, "body", strip=False)
        require_instance(self.dedupe_key, DedupeKey, "dedupe_key")
        require_instance(self.subject, str, "subject")
        if self.channel is Channel.EMAIL and not self.subject.strip():
            raise InvariantViolationError("email messages need a subject")
        require_text(self.language, "language")


class DeliveryStatus(StrEnum):
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Outcome of one send. A failure carries the error; a success carries none."""

    status: DeliveryStatus
    at: datetime
    provider_message_id: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        require_instance(self.status, DeliveryStatus, "status")
        require_aware(self.at, "at")
        require_instance(self.provider_message_id, str, "provider_message_id")
        error = require_instance(self.error, str, "error")
        if self.status is DeliveryStatus.FAILED and not error.strip():
            raise InvariantViolationError("a failed receipt needs an error")
        if self.status is DeliveryStatus.SENT and error:
            raise InvariantViolationError("a sent receipt carries no error")
