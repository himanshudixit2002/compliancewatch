"""The feature flags the identity use cases ask about, behind a protocol so that neither the
domain nor the application imports the flag client. The names are entries of
``packages/flags/registry.json``; the infrastructure answers them through OpenFeature."""

from typing import Final, Protocol

from domain_kernel.ids import TenantId

PLAN_LIMITS: Final = "identity.plan_limits"
"""Refuse what goes over a tenant's plan limits: an invitation past its seats here, a GSTIN
registration past its registrations at profile (402). Off by default; on per tenant first
(``CW_PLAN_LIMITS_ENFORCED`` with ``CW_PLAN_LIMITS_TENANTS``)."""


class FeatureFlags(Protocol):
    def enabled(self, name: str, tenant_id: TenantId) -> bool:
        """Whether the bool flag ``name`` is on for ``tenant_id``."""
        ...
