"""Identity's ``FeatureFlags`` on py-common's OpenFeature client.

``configure_flags(settings)`` in the composition root installs the provider (environment
variables by default, Unleash with ``CW_FLAGS_PROVIDER=unleash``); this adapter only asks it.
The tenant id is the targeting key, so a flag can be on for some tenants first.
"""

from domain_kernel.ids import TenantId
from py_common.flags import flag_enabled


class OpenFeatureFlags:
    def enabled(self, name: str, tenant_id: TenantId) -> bool:
        return flag_enabled(name, tenant_id.value)


class StaticFlags:
    """Flags fixed in the process: the names in ``on`` are on for every tenant (tests)."""

    def __init__(self, *on: str) -> None:
        self._on = frozenset(on)

    def enabled(self, name: str, tenant_id: TenantId) -> bool:
        return name in self._on
