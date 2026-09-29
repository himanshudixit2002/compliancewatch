"""Which tenants the planner and solver layer is on for (``CW_QA_KAG_ENABLED`` and
``CW_QA_KAG_TENANTS``; owner ai-platform; removed when ADR-017 is Accepted)."""

from dataclasses import dataclass

from domain_kernel.ids import TenantId


@dataclass(frozen=True, slots=True)
class KagTargeting:
    """Off unless ``enabled``. On, an empty ``tenants`` means every tenant; otherwise only the
    tenants listed."""

    enabled: bool = False
    tenants: frozenset[TenantId] = frozenset()

    def is_on_for(self, tenant: TenantId) -> bool:
        return self.enabled and (not self.tenants or tenant in self.tenants)
