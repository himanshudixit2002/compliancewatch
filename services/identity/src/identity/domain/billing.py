"""Billing behind an interface: plans, subscriptions, the ledger and the provider that charges.

The provider is Razorpay in the skeleton; the domain never sees its shapes. Pricing is an open
question in the roadmap, so the plans here are placeholders with zero prices that the
maintainer replaces once pricing is decided. Card data never touches this code: the provider
hosts checkout and calls back with signed webhooks.

A plan's ``limits`` are what one unit of its quantity allows: ``registrations`` (GSTIN
registrations the tenant may hold) and ``seats`` (active users); None is no limit. The values
are placeholders too, decided by the maintainer with the pricing (G34).

The ledger (``BillingRepository``) keeps a tenant's provider customer, its subscriptions, the
starts it asked the provider for (``StartAttempt``, one per Idempotency-Key) and every verified
webhook it received, append-only, in the unit of work's transaction.

A subscription past due (the provider retries the charge, or has given up: Razorpay's ``halted``)
keeps its plan for a grace period after it turned past due (``CW_PLAN_PAST_DUE_GRACE_DAYS``,
14 days, a placeholder the maintainer decides), then gives the free allowance. A cancelled
subscription is final: no later webhook makes it active again.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId

REGISTRATIONS: Final = "registrations"
"""GSTIN registrations a tenant may hold across its businesses."""
SEATS: Final = "seats"
"""Active users a tenant may have."""
LIMIT_KEYS: Final[tuple[str, ...]] = (REGISTRATIONS, SEATS)
MAX_QUANTITY: Final = 1000
"""The most units of a plan one subscription may have; ``CW_PLAN_MAX_QUANTITY`` may lower it."""
DEFAULT_PAST_DUE_GRACE: Final = timedelta(days=14)
"""How long a past-due subscription keeps its plan (placeholder, decided by the maintainer)."""


def clamp_quantity(value: int, maximum: int = MAX_QUANTITY) -> int:
    """``value`` within 1..``maximum``: what a request or a webhook may ask for."""
    return max(1, min(value, maximum))


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
    limits: Mapping[str, int | None] = field(default_factory=dict)
    """Per unit of quantity, by ``LIMIT_KEYS``; a key left out or None is no limit."""

    def __post_init__(self) -> None:
        require_text(self.key, "key")
        require_text(self.name, "name")
        require_int(self.amount_paise, "amount_paise", minimum=0)
        require_instance(self.period, BillingPeriod, "period")
        for key, value in self.limits.items():
            if key not in LIMIT_KEYS:
                raise InvariantViolationError(f"plan {self.key}: unknown limit {key!r}")
            if value is not None:
                require_int(value, f"limits.{key}", minimum=0)

    def limit(self, key: str, quantity: int) -> int | None:
        """What ``quantity`` units of the plan allow of ``key``; None is no limit."""
        per_unit = self.limits.get(key)
        return None if per_unit is None else per_unit * quantity


PLANS: Mapping[str, Plan] = {
    plan.key: plan
    for plan in (
        Plan(
            "owner_monthly",
            "Owner-operator, per business",
            0,
            BillingPeriod.MONTHLY,
            "Placeholder: pricing per business per month is not decided (roadmap open question).",
            # Placeholder limits, decided by the maintainer with the pricing.
            {REGISTRATIONS: 5, SEATS: 3},
        ),
        Plan(
            "ca_seat_monthly",
            "CA firm, per seat",
            0,
            BillingPeriod.MONTHLY,
            "Placeholder: pricing per CA seat is not decided.",
            # Placeholder limits, decided by the maintainer with the pricing.
            {REGISTRATIONS: 25, SEATS: 1},
        ),
    )
}


class SubscriptionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


PAID_STATUSES: Final = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE})
"""The statuses whose plan a tenant may be entitled to: active, and past due within the grace
(``Subscription.entitled``); created (checkout not finished) and cancelled ones give the free
allowance."""


class BillingProviderRefusedError(RuntimeError):
    """The provider refused a call, or it was never sent: nothing was created there, so the
    start may be tried again under the same Idempotency-Key. Any other failure of a provider
    call (a timeout, a 5xx) may have created something, and the key stays taken."""


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
    quantity: int = 1
    updated_at: datetime | None = None
    """When the ledger last changed it; None until it is stored."""
    last_event_at: datetime | None = None
    """When the newest webhook applied to it happened (the provider's time); an older one that
    arrives later is ignored. None until a webhook applied."""
    past_due_since: datetime | None = None
    """When it turned past due; None while it is not past due."""

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_text(self.plan_key, "plan_key")
        require_text(self.provider_subscription_id, "provider_subscription_id")
        require_instance(self.status, SubscriptionStatus, "status")
        require_aware(self.started_at, "started_at")
        require_quantity(self.quantity)
        for name in ("updated_at", "last_event_at", "past_due_since"):
            value = getattr(self, name)
            if value is not None:
                require_aware(value, name)

    @property
    def paid(self) -> bool:
        """Whether its status can entitle the tenant to the plan (``PAID_STATUSES``)."""
        return self.status in PAID_STATUSES

    def entitled(self, now: datetime, past_due_grace: timedelta = DEFAULT_PAST_DUE_GRACE) -> bool:
        """Whether the tenant is entitled to the plan at ``now``: active, or past due for less
        than ``past_due_grace``."""
        if self.status is SubscriptionStatus.ACTIVE:
            return True
        if self.status is not SubscriptionStatus.PAST_DUE:
            return False
        since = self.past_due_since or self.updated_at or self.started_at
        return now - since < past_due_grace


def require_quantity(value: object) -> int:
    return require_int(value, "quantity", minimum=1)


@dataclass(frozen=True, slots=True)
class BillingEvent:
    """A provider webhook mapped to the domain: what happened to which subscription, and the
    tenant, plan and quantity the provider echoes back from the subscription's notes (None when
    the payload does not name them)."""

    kind: str
    provider_subscription_id: str
    status: SubscriptionStatus | None
    occurred_at: datetime
    raw_event: str
    tenant_id: TenantId | None = None
    plan_key: str | None = None
    quantity: int | None = None
    customer_id: str | None = None
    """The provider's customer the subscription belongs to, when the payload names it."""


@dataclass(frozen=True, slots=True)
class StoredBillingEvent:
    """A verified webhook as the ledger keeps it: ``raw_event`` is a projection of the payload on
    an allowlist of fields (ids, kind, status, plan, quantity, times, amounts and currency;
    ``application.billing.projected_payload``), masked for personal identifiers, never the body
    itself; ``body_sha256`` is the digest of the body as received, which makes a redelivery of
    the same body a duplicate."""

    id: UUID
    tenant_id: TenantId
    provider_subscription_id: str
    kind: str
    status: SubscriptionStatus | None
    occurred_at: datetime
    received_at: datetime
    body_sha256: str
    raw_event: Mapping[str, object]

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_aware(self.occurred_at, "occurred_at")
        require_aware(self.received_at, "received_at")
        if len(self.body_sha256) != 64:
            raise InvariantViolationError("body_sha256 is a SHA-256 in 64 hex digits")


@dataclass(frozen=True, slots=True)
class StartAttempt:
    """A subscription start the tenant asked for under one Idempotency-Key, recorded before the
    provider is called. ``provider_subscription_id`` is None until the provider has answered;
    a start found without it is still running, or failed where the provider may have created
    the subscription, and is never sent to the provider again."""

    tenant_id: TenantId
    key: str
    plan_key: str
    quantity: int
    created_at: datetime
    provider_subscription_id: str | None = None
    checkout_url: str = ""
    recorded_at: datetime | None = None
    """When the provider's answer was recorded."""

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_text(self.key, "key")
        require_text(self.plan_key, "plan_key")
        require_quantity(self.quantity)
        require_aware(self.created_at, "created_at")


class BillingRepository(Protocol):
    """The billing ledger of the unit of work's tenant."""

    def customer(self) -> Customer | None:
        """The tenant's provider customer, None before its first subscription."""
        ...

    def add_customer(self, customer: Customer, *, provider: str, at: datetime) -> bool:
        """Store the tenant's customer; False, and nothing stored, when it has one already."""
        ...

    def subscription(self, provider_subscription_id: str) -> Subscription | None:
        """The tenant's subscription with this provider id; None for another tenant's."""
        ...

    def subscriptions(self) -> list[Subscription]:
        """The tenant's subscriptions, newest first."""
        ...

    def add_subscription(self, subscription: Subscription) -> bool:
        """Insert ``subscription``; False, and nothing written, when a subscription with its
        provider id exists already, the tenant's own or another tenant's."""
        ...

    def update_subscription(self, subscription: Subscription) -> None:
        """Store the changed status, quantity and times of the tenant's own ``subscription``;
        a row of another tenant is never touched."""
        ...

    def start_attempt(self, key: str) -> StartAttempt | None:
        """The tenant's start under this Idempotency-Key, if any."""
        ...

    def claim_start(self, attempt: StartAttempt) -> bool:
        """Record ``attempt``; False, and nothing written, when its key is taken already."""
        ...

    def record_started(
        self, key: str, *, provider_subscription_id: str, checkout_url: str, at: datetime
    ) -> None:
        """Note the provider's subscription on the start under ``key``."""
        ...

    def release_start(self, key: str) -> None:
        """Forget the start under ``key``, when the provider created nothing for it."""
        ...

    def append_event(self, event: StoredBillingEvent) -> bool:
        """Append ``event``; False, and nothing stored, when the tenant already has an event
        with the same ``body_sha256`` (a redelivery)."""
        ...

    def events(self) -> list[StoredBillingEvent]:
        """The tenant's stored webhooks, oldest first (an export)."""
        ...


def current_subscription(
    subscriptions: list[Subscription],
    *,
    now: datetime,
    past_due_grace: timedelta = DEFAULT_PAST_DUE_GRACE,
) -> Subscription | None:
    """The subscription that decides a tenant's plan at ``now``: the newest one it is entitled
    to (``Subscription.entitled``), else None."""
    paid = [s for s in subscriptions if s.entitled(now, past_due_grace)]
    return max(paid, key=lambda s: (s.started_at, s.provider_subscription_id), default=None)


class BillingProvider(Protocol):
    @property
    def name(self) -> str:
        """The provider's name as the ledger records it: ``memory``, ``razorpay``."""
        ...

    def create_customer(self, tenant_id: TenantId, *, email: str, name: str) -> Customer: ...

    def create_subscription(
        self, customer: Customer, plan: Plan, quantity: int = 1
    ) -> Subscription: ...

    def verify_webhook(self, body: bytes, signature: str) -> bool: ...

    def parse_event(self, body: bytes) -> BillingEvent: ...
