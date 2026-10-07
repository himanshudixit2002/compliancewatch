"""What a tenant's plan entitles it to, and the seat check of an invitation.

``ReadEntitlements`` reads the tenant's subscriptions from the billing ledger and answers
``entitlements_for`` its current one (``identity.domain.entitlements``), with ``enforced`` from
the flag ``identity.plan_limits`` for the tenant. ``SeatCheck`` is the check ``InviteUser``
runs inside its unit of work: with the flag on and the tenant's active users at its seat limit,
``SeatLimitReachedError`` (402). The internal tenant, the regulatory team, has no limits.

A past-due subscription counts only for ``past_due_grace`` after it turned past due
(``CW_PLAN_PAST_DUE_GRACE_DAYS``, 14 days, a placeholder the maintainer decides); after that the
tenant has the free allowance until the provider charges again.
"""

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.domain.billing import DEFAULT_PAST_DUE_GRACE, Plan, current_subscription
from identity.domain.entitlements import (
    Entitlements,
    Limits,
    entitlements_for,
    internal_entitlements,
)
from identity.domain.errors import SeatLimitReachedError
from identity.domain.flags import PLAN_LIMITS, FeatureFlags
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import TenantKind, UserStatus


def tenant_entitlements(
    uow: UnitOfWork,
    tenant_id: TenantId,
    plans: Mapping[str, Plan],
    free_allowance: Limits,
    flags: FeatureFlags,
    *,
    now: datetime,
    past_due_grace: timedelta = DEFAULT_PAST_DUE_GRACE,
) -> Entitlements:
    """The entitlements of the unit of work's tenant at ``now``; the internal tenant's are
    unlimited."""
    tenant = uow.tenants.get(tenant_id)
    if tenant is not None and tenant.kind is TenantKind.INTERNAL:
        return internal_entitlements()
    return entitlements_for(
        current_subscription(uow.billing.subscriptions(), now=now, past_due_grace=past_due_grace),
        plans,
        free_allowance,
        enforced=flags.enabled(PLAN_LIMITS, tenant_id),
    )


class ReadEntitlements:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        plans: Mapping[str, Plan],
        free_allowance: Limits,
        flags: FeatureFlags,
        *,
        clock: Callable[[], datetime] = utc_now,
        past_due_grace: timedelta = DEFAULT_PAST_DUE_GRACE,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._plans = plans
        self._free = free_allowance
        self._flags = flags
        self._clock = clock
        self._grace = past_due_grace

    def run(self, tenant_id: TenantId) -> Entitlements:
        with self._unit_of_work(tenant_id) as uow:
            return tenant_entitlements(
                uow,
                tenant_id,
                self._plans,
                self._free,
                self._flags,
                now=self._clock(),
                past_due_grace=self._grace,
            )


class SeatCheck:
    """Whether a tenant has a seat left for one more user, when its limits are enforced."""

    def __init__(
        self,
        plans: Mapping[str, Plan],
        free_allowance: Limits,
        flags: FeatureFlags,
        *,
        clock: Callable[[], datetime] = utc_now,
        past_due_grace: timedelta = DEFAULT_PAST_DUE_GRACE,
    ) -> None:
        self._plans = plans
        self._free = free_allowance
        self._flags = flags
        self._clock = clock
        self._grace = past_due_grace

    def __call__(self, uow: UnitOfWork, tenant_id: TenantId) -> None:
        entitlements = tenant_entitlements(
            uow,
            tenant_id,
            self._plans,
            self._free,
            self._flags,
            now=self._clock(),
            past_due_grace=self._grace,
        )
        limit = entitlements.limits.seats
        if not entitlements.enforced or limit is None:
            return
        used = sum(1 for user in uow.users.list() if user.status is UserStatus.ACTIVE)
        if used >= limit:
            raise SeatLimitReachedError(limit=limit, used=used)
