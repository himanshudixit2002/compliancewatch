"""The feature flags the profile use cases ask about, behind a protocol so that neither the domain
nor the application imports the flag client. The names are entries of
``packages/flags/registry.json``; the infrastructure answers them through OpenFeature."""

from typing import Final, Protocol

from domain_kernel.ids import TenantId

GSTIN_CATEGORY_PREFILL: Final = "profile.gstin_category_prefill"
"""Write ``business_category`` from the GSTIN lookup's nature of business. Off by default until
an analyst has reviewed the mapping; turned on per tenant first."""


class FeatureFlags(Protocol):
    def enabled(self, name: str, tenant_id: TenantId) -> bool:
        """Whether the bool flag ``name`` is on for ``tenant_id``."""
        ...
