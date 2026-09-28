"""A request to notify, and what became of it."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from domain_kernel._validation import freeze_mapping, require_instance, require_text
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from domain_kernel.notifications import DeliveryReceipt


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    notification_id: NotificationId
    tenant_id: TenantId
    obligation_id: ObligationId
    business_id: BusinessId
    channel: Channel
    recipient: str
    template_key: str
    params: Mapping[str, object] = field(default_factory=dict, hash=False)
    dedupe_key: DedupeKey | None = None
    language: str | None = None
    """Overrides the recipient's preferred language when set."""

    def __post_init__(self) -> None:
        require_instance(self.notification_id, NotificationId, "notification_id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.channel, Channel, "channel")
        require_text(self.recipient, "recipient")
        require_text(self.template_key, "template_key")
        object.__setattr__(self, "params", freeze_mapping(self.params, "params"))
        if self.dedupe_key is not None:
            require_instance(self.dedupe_key, DedupeKey, "dedupe_key")


class Outcome(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    DEFERRED = "deferred"
    """Quiet hours: held until ``scheduled_for``."""
    NOT_OPTED_IN = "not_opted_in"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class SendOutcome:
    outcome: Outcome
    notification_id: NotificationId
    dedupe_key: DedupeKey
    receipt: DeliveryReceipt | None = None
    scheduled_for: datetime | None = None
    language: str = "en"


class SentLog(Protocol):
    """What has gone out, by dedupe key: the guard against sending one change twice."""

    def seen(self, dedupe_key: DedupeKey) -> bool: ...

    def record(self, dedupe_key: DedupeKey, at: datetime) -> None: ...


class EventSink(Protocol):
    def publish(self, event: DomainEvent) -> None: ...
