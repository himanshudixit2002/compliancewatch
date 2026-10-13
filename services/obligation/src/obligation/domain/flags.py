"""The feature flags the obligation use cases ask about, behind a protocol so that neither the
domain nor the application imports the flag client. The names are entries of
``packages/flags/registry.json``; the infrastructure answers them through OpenFeature."""

from typing import Final, Protocol

from domain_kernel.ids import TenantId

ERROR_REPORTS: Final = "obligation.error_reports"
"""Lets a tenant's members report an error in an obligation. Off by default; on per tenant first
(``CW_FLAG_OBLIGATION_ERROR_REPORTS`` with ``CW_FLAG_OBLIGATION_ERROR_REPORTS__TENANTS``)."""


class FeatureFlags(Protocol):
    def enabled(self, name: str, tenant_id: TenantId) -> bool:
        """Whether the bool flag ``name`` is on for ``tenant_id``."""
        ...
