"""What a tenant's plan entitles it to: how many GSTIN registrations and seats it may have.

``entitlements_for(subscription, plans, free)`` is the plan of the tenant's current subscription
(``billing.current_subscription``: the newest active or past-due one) times its quantity, or the
free allowance when there is none or its plan is no longer offered. The internal tenant has no
limits (``internal_entitlements``). ``enforced`` says whether the
services refuse what goes over the limits (the flag ``identity.plan_limits`` for the tenant);
off, the limits are only reported.

The free allowance (``CW_PLAN_FREE_REGISTRATIONS`` and ``CW_PLAN_FREE_SEATS``, one each) and the
plans' limits are placeholders the maintainer decides with the pricing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from domain_kernel._validation import require_bool, require_int, require_text
from identity.domain.billing import REGISTRATIONS, SEATS, Plan, Subscription

FREE_PLAN: Final = "free"
"""The plan key and status of a tenant without a paid subscription."""
INTERNAL_PLAN: Final = "internal"
"""The plan key and status of the internal tenant, the regulatory team: no limits."""


@dataclass(frozen=True, slots=True)
class Limits:
    """How many of each a tenant may have; None is no limit."""

    registrations: int | None
    seats: int | None

    def __post_init__(self) -> None:
        for name in (REGISTRATIONS, SEATS):
            value = getattr(self, name)
            if value is not None:
                require_int(value, name, minimum=0)


@dataclass(frozen=True, slots=True)
class Entitlements:
    plan_key: str
    status: str
    """The subscription's status, or ``free``."""
    limits: Limits
    enforced: bool

    def __post_init__(self) -> None:
        require_text(self.plan_key, "plan_key")
        require_text(self.status, "status")
        require_bool(self.enforced, "enforced")


def entitlements_for(
    subscription: Subscription | None,
    plans: Mapping[str, Plan],
    free_allowance: Limits,
    *,
    enforced: bool = False,
) -> Entitlements:
    """The tenant's entitlements from its current subscription, or the free allowance."""
    plan = None if subscription is None else plans.get(subscription.plan_key)
    if subscription is None or plan is None or not subscription.paid:
        return Entitlements(FREE_PLAN, FREE_PLAN, free_allowance, enforced)
    limits = Limits(
        registrations=plan.limit(REGISTRATIONS, subscription.quantity),
        seats=plan.limit(SEATS, subscription.quantity),
    )
    return Entitlements(plan.key, subscription.status.value, limits, enforced)


def internal_entitlements() -> Entitlements:
    """The regulatory team's tenant: nothing is limited or enforced."""
    return Entitlements(INTERNAL_PLAN, INTERNAL_PLAN, Limits(None, None), enforced=False)
