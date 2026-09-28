"""Billing behind an interface: plans, subscriptions and the provider that charges.

The provider is Razorpay in the skeleton; the domain never sees its shapes. Pricing is an open
question in the roadmap, so the plans here are placeholders with zero prices that the
maintainer replaces once pricing is decided. Card data never touches this code: the provider
hosts checkout and calls back with signed webhooks.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.ids import TenantId


class BillingPeriod(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


@dataclass(frozen=True, slots=True)
class Plan:
    key: str
    name: str
    amount_paise: int
    period: BillingPeriod
    description: str = ""

    def __post_init__(self) -> None:
        require_text(self.key, "key")
        require_text(self.name, "name")
        require_int(self.amount_paise, "amount_paise", minimum=0)
        require_instance(self.period, BillingPeriod, "period")


PLANS: Mapping[str, Plan] = {
    plan.key: plan
    for plan in (
        Plan(
            "owner_monthly",
            "Owner-operator, per business",
            0,
            BillingPeriod.MONTHLY,
            "Placeholder: pricing per business per month is not decided (roadmap open question).",
        ),
        Plan(
            "ca_seat_monthly",
            "CA firm, per seat",
            0,
            BillingPeriod.MONTHLY,
            "Placeholder: pricing per CA seat is not decided.",
        ),
    )
}


class SubscriptionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Customer:
    tenant_id: TenantId
    provider_customer_id: str
    email: str
    name: str


@dataclass(frozen=True, slots=True)
class Subscription:
    tenant_id: TenantId
    plan_key: str
    provider_subscription_id: str
    status: SubscriptionStatus
    started_at: datetime
    checkout_url: str = ""

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_text(self.plan_key, "plan_key")
        require_text(self.provider_subscription_id, "provider_subscription_id")
        require_instance(self.status, SubscriptionStatus, "status")
        require_aware(self.started_at, "started_at")


@dataclass(frozen=True, slots=True)
class BillingEvent:
    """A provider webhook mapped to the domain: what happened to which subscription."""

    kind: str
    provider_subscription_id: str
    status: SubscriptionStatus | None
    occurred_at: datetime
    raw_event: str


class BillingProvider(Protocol):
    def create_customer(self, tenant_id: TenantId, *, email: str, name: str) -> Customer: ...

    def create_subscription(self, customer: Customer, plan: Plan) -> Subscription: ...

    def verify_webhook(self, body: bytes, signature: str) -> bool: ...

    def parse_event(self, body: bytes) -> BillingEvent: ...
