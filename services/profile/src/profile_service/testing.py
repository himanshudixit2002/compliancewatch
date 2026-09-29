"""Builders for tests of this service and of services that read profile snapshots."""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime

from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import TenantId

TENANT = TenantId.new()
OTHER_TENANT = TenantId.new()
PAN = Pan("ABCDE1234F")
GSTIN_KARNATAKA = Gstin("29ABCDE1234F1Z5")
GSTIN_DELHI = Gstin("07ABCDE1234F1Z9")
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


@dataclass(frozen=True, slots=True)
class FixedFlags:
    """Feature flags for tests: the flags in ``on`` are on, for the tenants in ``tenants`` or,
    when that is empty, for every tenant; every other flag is off."""

    on: Collection[str] = ()
    tenants: Collection[TenantId] = field(default=())

    def enabled(self, name: str, tenant_id: TenantId) -> bool:
        return name in self.on and (not self.tenants or tenant_id in self.tenants)
