"""Request and response bodies of the notification API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain_kernel.channels import Channel
from notification.domain.model import Outcome, SendOutcome
from notification.domain.preferences import ChannelPreference, ConsentSource
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
    recipient: str
    opted_in: bool
    source: ConsentSource
    language: str
    quiet_hours_start: str
    quiet_hours_end: str
    updated_at: datetime

    @classmethod
    def from_preference(cls, preference: ChannelPreference) -> "PreferenceOut":
        return cls(
            channel=preference.channel,
            recipient=preference.recipient,
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
