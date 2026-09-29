"""Request and response bodies of the notification API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain_kernel.channels import Channel
from notification.domain.model import Outcome, SendOutcome
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
    attempt: int = Field(default=1, ge=1, le=10)


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
