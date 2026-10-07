"""What the tenant's plan allows, as the profile asks the identity service for it.

``EntitlementsReader.registration_limit(tenant)`` is how many GSTIN registrations the tenant may
hold, or None for no limit: no plan limits are enforced for it (the flag
``identity.plan_limits`` is off at profile, or identity answers ``enforced`` false), the plan has
none, or identity cannot be reached now (the reader fails open). A reader that finds identity
misconfigured raises ``EntitlementsMisconfiguredError`` (503) instead. The flag's name lives with
the other flags (``domain.flags``).
"""

from typing import Protocol

from domain_kernel.ids import TenantId


class EntitlementsReader(Protocol):
    def registration_limit(self, tenant_id: TenantId) -> int | None: ...
