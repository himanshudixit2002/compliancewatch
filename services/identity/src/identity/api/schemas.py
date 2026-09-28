"""Request and response bodies of the identity API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from identity.application.consents import ConsentSummary
from identity.domain.billing import PLANS, Plan, Subscription
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource


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


class ConsentSummaryOut(BaseModel):
    subject: str
    states: list[ConsentStateOut]
    history: list[ConsentOut]

    @classmethod
    def from_summary(cls, summary: ConsentSummary) -> "ConsentSummaryOut":
        return cls(
            subject=summary.subject,
            states=[
                ConsentStateOut(
                    purpose=s.purpose,
                    granted=s.granted,
                    notice_version=s.notice_version,
                    since=s.since,
                    source=s.source,
                )
                for s in summary.states
            ],
            history=[ConsentOut.from_record(r) for r in summary.history],
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
