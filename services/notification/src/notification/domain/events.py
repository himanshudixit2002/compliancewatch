"""Events the notification service publishes; fields follow packages/contracts/events."""

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from domain_kernel._validation import (
    require_aware,
    require_bool,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationSent(DomainEvent):
    topic: ClassVar[str] = "notification.sent"
    schema_version: ClassVar[str] = "1.0.1"

    notification_id: NotificationId
    obligation_id: ObligationId
    business_id: BusinessId
    channel: Channel
    dedupe_key: str
    """The key's 64 hex characters; the contract carries text."""
    sent_at: datetime
    language: str
    provider_message_id: str = ""

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.notification_id, NotificationId, "notification_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.channel, Channel, "channel")
        DedupeKey(require_text(self.dedupe_key, "dedupe_key"))
        require_aware(self.sent_at, "sent_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationFailed(DomainEvent):
    topic: ClassVar[str] = "notification.failed"
    schema_version: ClassVar[str] = "1.0.1"

    notification_id: NotificationId
    obligation_id: ObligationId
    business_id: BusinessId
    channel: Channel
    dedupe_key: str
    error: str
    attempts: int
    will_retry: bool
    failed_at: datetime

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.notification_id, NotificationId, "notification_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.channel, Channel, "channel")
        DedupeKey(require_text(self.dedupe_key, "dedupe_key"))
        require_int(self.attempts, "attempts", minimum=1)
        require_bool(self.will_retry, "will_retry")
        require_aware(self.failed_at, "failed_at")
