"""What a tenant's plan entitles it to, and the seat check of an invitation.

``ReadEntitlements`` reads the tenant's subscriptions from the billing ledger and answers
``entitlements_for`` its current one (``identity.domain.entitlements``), with ``enforced`` from
the flag ``identity.plan_limits`` for the tenant. ``check_seat(uow, ...)`` is the check
``InviteUser`` runs inside its unit of work: with the flag on and the tenant's active users at
its seat limit, ``SeatLimitReachedError`` (402). The internal tenant, the regulatory team, has
no limits.
"""

from collections.abc import Mapping

from domain_kernel.ids import TenantId
from identity.domain.billing import Plan, current_subscription
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
) -> Entitlements:
    """The entitlements of the unit of work's tenant; the internal tenant's are unlimited."""
    tenant = uow.tenants.get(tenant_id)
    if tenant is not None and tenant.kind is TenantKind.INTERNAL:
        return internal_entitlements()
    return entitlements_for(
        current_subscription(uow.billing.subscriptions()),
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
    ) -> None:
        self._unit_of_work = unit_of_work
        self._plans = plans
        self._free = free_allowance
        self._flags = flags

    def run(self, tenant_id: TenantId) -> Entitlements:
        with self._unit_of_work(tenant_id) as uow:
            return tenant_entitlements(uow, tenant_id, self._plans, self._free, self._flags)


class SeatCheck:
    """Whether a tenant has a seat left for one more user, when its limits are enforced."""

    def __init__(
        self, plans: Mapping[str, Plan], free_allowance: Limits, flags: FeatureFlags
    ) -> None:
        self._plans = plans
        self._free = free_allowance
        self._flags = flags

    def __call__(self, uow: UnitOfWork, tenant_id: TenantId) -> None:
        entitlements = tenant_entitlements(uow, tenant_id, self._plans, self._free, self._flags)
        limit = entitlements.limits.seats
        if not entitlements.enforced or limit is None:
            return
        used = sum(1 for user in uow.users.list() if user.status is UserStatus.ACTIVE)
        if used >= limit:
            raise SeatLimitReachedError(limit=limit, used=used)
