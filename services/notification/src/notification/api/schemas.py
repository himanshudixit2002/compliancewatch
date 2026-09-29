"""Request and response bodies of the notification API."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domain_kernel.channels import Channel
from notification.domain.model import Outcome, SendOutcome
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ChannelPreference, ConsentSource
from notification.domain.recipients import (
    MAX_ADDRESSES,
    MAX_BUSINESSES,
    MAX_LABEL_LENGTH,
    DigestMode,
    Recipient,
    RecipientRole,
)
from notification.domain.templates import MessageTemplate

E164 = r"^\+?[1-9][0-9]{7,14}$"
CLOCK_TIME_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
"""``HH:MM`` on a 24-hour clock, 00:00 to 23:59."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreferenceIn(Strict):
    opted_in: bool
    source: ConsentSource
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    quiet_hours_start: str | None = Field(default=None, pattern=CLOCK_TIME_PATTERN)
    quiet_hours_end: str | None = Field(default=None, pattern=CLOCK_TIME_PATTERN)


class PreferenceOut(BaseModel):
    channel: Channel
    recipient: str = Field(description="The address as the request gave it")
    address: str = Field(
        description="The address as it is stored: +<digits> for WhatsApp, lower case for email"
    )
    opted_in: bool
    source: ConsentSource
    language: str
    quiet_hours_start: str
    quiet_hours_end: str
    updated_at: datetime

    @classmethod
    def from_preference(cls, preference: ChannelPreference, *, recipient: str) -> "PreferenceOut":
        return cls(
            channel=preference.channel,
            recipient=recipient,
            address=preference.address,
            opted_in=preference.opted_in,
            source=preference.source,
            language=preference.language,
            quiet_hours_start=preference.quiet_hours.start.strftime("%H:%M"),
            quiet_hours_end=preference.quiet_hours.end.strftime("%H:%M"),
            updated_at=preference.updated_at,
        )


class SendIn(Strict):
    notification_id: UUID
    obligation_id: UUID
    business_id: UUID
    channel: Channel
    recipient: str = Field(min_length=3, max_length=254)
    template_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    params: dict[str, Any] = Field(default_factory=dict)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    attempt: int = Field(
        default=1,
        ge=1,
        le=10,
        deprecated=True,
        description="Ignored: the service retries a failed delivery itself",
    )


class SendOut(BaseModel):
    outcome: Outcome
    notification_id: UUID
    dedupe_key: str
    provider_message_id: str = ""
    error: str = ""
    scheduled_for: datetime | None = None
    language: str

    @classmethod
    def from_outcome(cls, result: SendOutcome) -> "SendOut":
        receipt = result.receipt
        return cls(
            outcome=result.outcome,
            notification_id=result.notification_id.value,
            dedupe_key=result.dedupe_key.value,
            provider_message_id="" if receipt is None else receipt.provider_message_id,
            error="" if receipt is None else receipt.error,
            scheduled_for=result.scheduled_for,
            language=result.language,
        )


class TemplateOut(BaseModel):
    key: str
    channel: Channel
    language: str
    status: str
    meta_name: str
    placeholders: list[str]
    body: str

    @classmethod
    def from_template(cls, template: MessageTemplate) -> "TemplateOut":
        return cls(
            key=template.key,
            channel=template.channel,
            language=template.language,
            status=template.status.value,
            meta_name=template.meta_name,
            placeholders=list(template.placeholders),
            body=template.body,
        )


class RecipientAddressIn(Strict):
    channel: Channel
    address: str = Field(
        min_length=3,
        max_length=254,
        description="A phone number with its country code for WhatsApp, a mailbox for email",
    )


class BusinessLinkIn(Strict):
    business_id: UUID
    label: str = Field(
        default="",
        max_length=MAX_LABEL_LENGTH,
        description="What the recipient calls the business, such as a CA firm's client name",
    )


class RecipientIn(Strict):
    user_id: UUID | None = Field(
        default=None, description="The person's user id when they sign in to the web app"
    )
    role: RecipientRole
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")
    digest_mode: DigestMode = DigestMode.OFF
    org_label: str = Field(
        default="",
        max_length=MAX_LABEL_LENGTH,
        description="The organisation the recipient speaks for, such as the CA firm's name",
    )
    addresses: list[RecipientAddressIn] = Field(
        default_factory=list,
        max_length=MAX_ADDRESSES,
        description="In the order they are tried; each still needs its opt-in",
    )
    businesses: list[BusinessLinkIn] = Field(default_factory=list, max_length=MAX_BUSINESSES)


class RecipientAddressOut(BaseModel):
    channel: Channel
    address: str = Field(description="Normalised: +<digits> for WhatsApp, lower case for email")
    position: int


class BusinessLinkOut(BaseModel):
    business_id: UUID
    label: str


class RecipientOut(BaseModel):
    id: UUID
    user_id: UUID | None
    role: RecipientRole
    language: str
    digest_mode: DigestMode
    by_digest: bool = Field(
        description="Notifications wait for the daily digest: chosen, or a CA firm's recipient"
    )
    org_label: str
    addresses: list[RecipientAddressOut]
    businesses: list[BusinessLinkOut]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_recipient(cls, recipient: Recipient) -> "RecipientOut":
        return cls(
            id=recipient.id.value,
            user_id=None if recipient.user_id is None else recipient.user_id.value,
            role=recipient.role,
            language=recipient.language,
            digest_mode=recipient.digest_mode,
            by_digest=recipient.by_digest,
            org_label=recipient.org_label,
            addresses=[
                RecipientAddressOut(
                    channel=address.channel, address=address.address, position=address.position
                )
                for address in recipient.addresses
            ],
            businesses=[
                BusinessLinkOut(business_id=link.business_id.value, label=link.label)
                for link in recipient.businesses
            ],
            created_at=recipient.created_at,
            updated_at=recipient.updated_at,
        )


class NotificationOut(BaseModel):
    """One notification: to whom, about what, and how far it got."""

    id: UUID
    business_id: UUID
    obligation_id: UUID
    recipient_id: UUID | None = Field(description="None for a send addressed straight to a number")
    channel: Channel
    address: str = Field(description="Normalised: +<digits> for WhatsApp, lower case for email")
    occasion: OccasionKind
    template_key: str
    language: str
    params: dict[str, Any] = Field(
        description="The values the message was filled with; emptied 30 days after it ended"
    )
    state: DeliveryState
    attempts: int
    available_at: datetime = Field(description="When it may go out, or when it is tried again")
    dispatch_id: UUID | None
    provider_message_id: str
    error: str
    fallback_of: UUID | None = Field(description="The notification this one falls back from")
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    failed_at: datetime | None

    @classmethod
    def from_notification(cls, notification: Notification) -> "NotificationOut":
        return cls(
            id=notification.id.value,
            business_id=notification.business_id.value,
            obligation_id=notification.obligation_id.value,
            recipient_id=None
            if notification.recipient_id is None
            else notification.recipient_id.value,
            channel=notification.channel,
            address=notification.address,
            occasion=notification.occasion,
            template_key=notification.template_key,
            language=notification.language,
            params=_plain(notification.params),
            state=notification.state,
            attempts=notification.attempts,
            available_at=notification.available_at,
            dispatch_id=None
            if notification.dispatch_id is None
            else notification.dispatch_id.value,
            provider_message_id=notification.provider_message_id,
            error=notification.error,
            fallback_of=None
            if notification.fallback_of is None
            else notification.fallback_of.value,
            created_at=notification.created_at,
            updated_at=notification.updated_at,
            sent_at=notification.sent_at,
            delivered_at=notification.delivered_at,
            read_at=notification.read_at,
            failed_at=notification.failed_at,
        )


class NotificationKeyset(Strict):
    """Where a page of a business's notifications starts: after this one, newest first."""

    created_at: AwareDatetime
    id: UUID


MAX_RECEIPTS = 1000
"""Items one forward may carry; a webhook delivery holds far fewer."""


class WhatsAppStatusIn(Strict):
    provider_message_id: str = Field(min_length=1, max_length=256, description="Meta's wamid")
    status: str = Field(
        min_length=1,
        max_length=32,
        description="sent, delivered, read or failed; any other status is ignored",
    )
    at: AwareDatetime = Field(description="When Meta says it happened, with its offset")
    error_code: int | None = Field(default=None, description="Meta's error code of a failure")
    error_title: str = Field(default="", max_length=500)


class InboundIn(Strict):
    address: str = Field(
        min_length=3, max_length=254, description="The number that wrote to the business"
    )
    at: AwareDatetime = Field(description="When its message was sent, with its offset")


class WhatsAppReceiptsIn(Strict):
    statuses: list[WhatsAppStatusIn] = Field(default_factory=list, max_length=MAX_RECEIPTS)
    inbound: list[InboundIn] = Field(default_factory=list, max_length=MAX_RECEIPTS)


class ReceiptsOut(BaseModel):
    applied: int = Field(description="Receipts that moved a notification on")
    unchanged: int = Field(description="Late or repeated receipts that changed nothing")
    unknown: int = Field(description="Receipts for messages no notification carries")
    ignored: int = Field(description="Statuses the service does not act on")
    inbound: int = Field(description="Inbound times recorded")


def _plain(value: object) -> Any:
    """Template values as JSON: read-only mappings and tuples become dicts and lists."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value
