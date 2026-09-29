"""Request and response bodies of the identity API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from identity.application.channel_consents import ChannelConsentSummary
from identity.application.consents import ConsentSummary
from identity.domain.billing import PLANS, Plan, Subscription
from identity.domain.channel_consent import (
    MESSAGE_ID_MAX_LENGTH,
    ChannelConsentRecord,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource, ConsentState

E164_PATTERN = r"^\+?[1-9][0-9]{7,14}$"
"""A phone number in E.164 form, the plus optional: the pattern of notification's schema."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsentIn(Strict):
    subject: str = Field(min_length=1, max_length=254, description="User id or E.164 number")
    purpose: ConsentPurpose
    granted: bool = True
    source: ConsentSource
    notice_version: str = Field(default="", max_length=40, description="Required when granting")
    evidence: str = Field(default="", max_length=2000)
    recorded_by: UUID | None = None


class ConsentOut(BaseModel):
    id: UUID
    subject: str
    purpose: ConsentPurpose
    granted: bool
    source: ConsentSource
    notice_version: str
    evidence: str
    recorded_by: UUID | None
    recorded_at: datetime

    @classmethod
    def from_record(cls, record: ConsentRecord) -> "ConsentOut":
        return cls(
            id=record.id.value,
            subject=record.subject,
            purpose=record.purpose,
            granted=record.granted,
            source=record.source,
            notice_version=record.notice_version,
            evidence=record.evidence,
            recorded_by=None if record.recorded_by is None else record.recorded_by.value,
            recorded_at=record.recorded_at,
        )


class ConsentStateOut(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    notice_version: str
    since: datetime
    source: ConsentSource

    @classmethod
    def from_state(cls, state: ConsentState) -> "ConsentStateOut":
        return cls(
            purpose=state.purpose,
            granted=state.granted,
            notice_version=state.notice_version,
            since=state.since,
            source=state.source,
        )


class ConsentSummaryOut(BaseModel):
    subject: str
    states: list[ConsentStateOut]
    history: list[ConsentOut]

    @classmethod
    def from_summary(cls, summary: ConsentSummary) -> "ConsentSummaryOut":
        return cls(
            subject=summary.subject,
            states=[ConsentStateOut.from_state(state) for state in summary.states],
            history=[ConsentOut.from_record(r) for r in summary.history],
        )


class ChannelConsentIn(Strict):
    channel: ConsentChannel
    subject: str = Field(
        pattern=E164_PATTERN, description="E.164 number; WhatsApp reports it without the plus"
    )
    purpose: ConsentPurpose = Field(description="whatsapp_reminders is the one WhatsApp purpose")
    granted: bool = True
    source: ConsentSource = Field(description="whatsapp_keyword is the one WhatsApp source")
    notice_version: str = Field(default="", max_length=40, description="Required when granting")
    evidence: str = Field(default="", max_length=2000, description="The keyword and the message")
    message_id: str = Field(
        default="",
        max_length=MESSAGE_ID_MAX_LENGTH,
        description="The channel's message id; the same id again returns the first record",
    )


class ChannelConsentOut(BaseModel):
    id: UUID
    channel: ConsentChannel
    subject: str
    purpose: ConsentPurpose
    granted: bool
    source: ConsentSource
    notice_version: str
    evidence: str
    message_id: str
    recorded_at: datetime

    @classmethod
    def from_record(cls, record: ChannelConsentRecord) -> "ChannelConsentOut":
        return cls(
            id=record.id.value,
            channel=record.channel,
            subject=record.subject,
            purpose=record.purpose,
            granted=record.granted,
            source=record.source,
            notice_version=record.notice_version,
            evidence=record.evidence,
            message_id=record.message_id,
            recorded_at=record.recorded_at,
        )


class ChannelConsentSummaryOut(BaseModel):
    channel: ConsentChannel
    subject: str
    states: list[ConsentStateOut]
    history: list[ChannelConsentOut]

    @classmethod
    def from_summary(cls, summary: ChannelConsentSummary) -> "ChannelConsentSummaryOut":
        return cls(
            channel=summary.channel,
            subject=summary.subject,
            states=[ConsentStateOut.from_state(state) for state in summary.states],
            history=[ChannelConsentOut.from_record(record) for record in summary.history],
        )


class PlanOut(BaseModel):
    key: str
    name: str
    amount_paise: int
    period: str
    description: str

    @classmethod
    def from_plan(cls, plan: Plan) -> "PlanOut":
        return cls(
            key=plan.key,
            name=plan.name,
            amount_paise=plan.amount_paise,
            period=plan.period.value,
            description=plan.description,
        )


class SubscriptionIn(Strict):
    plan_key: str = Field(pattern="^(" + "|".join(PLANS) + ")$")
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=200)


class SubscriptionOut(BaseModel):
    plan_key: str
    provider_subscription_id: str
    status: str
    started_at: datetime
    checkout_url: str

    @classmethod
    def from_subscription(cls, subscription: Subscription) -> "SubscriptionOut":
        return cls(
            plan_key=subscription.plan_key,
            provider_subscription_id=subscription.provider_subscription_id,
            status=subscription.status.value,
            started_at=subscription.started_at,
            checkout_url=subscription.checkout_url,
        )


class WebhookOut(BaseModel):
    kind: str
    provider_subscription_id: str
    status: str | None
