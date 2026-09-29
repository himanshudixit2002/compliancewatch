"""Tenant targeting of the planner and solver layer."""

from uuid import UUID

from domain_kernel.ids import TenantId
from qa.domain.flags import KagTargeting

ACME = TenantId(UUID(int=1))
OTHER = TenantId(UUID(int=2))


def test_off_is_off_for_everyone() -> None:
    assert not KagTargeting().is_on_for(ACME)
    assert not KagTargeting(enabled=False, tenants=frozenset({ACME})).is_on_for(ACME)


def test_on_without_tenants_is_on_for_everyone() -> None:
    targeting = KagTargeting(enabled=True)
    assert targeting.is_on_for(ACME)
    assert targeting.is_on_for(OTHER)


def test_on_with_tenants_is_on_only_for_them() -> None:
    targeting = KagTargeting(enabled=True, tenants=frozenset({ACME}))
    assert targeting.is_on_for(ACME)
    assert not targeting.is_on_for(OTHER)
