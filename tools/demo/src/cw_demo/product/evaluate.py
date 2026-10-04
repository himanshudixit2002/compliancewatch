"""``cw-product evaluate``: have the engine decide every published rule for every seeded
registration.

Nothing triggers the applicability engine on its own yet. Until it consumes profile.updated and
rule.published itself (later packages), this is how decisions are made, and it stays afterwards
as an operator tool. For each GSTIN registration of the synthetic tenants (found by its GSTIN
among the tenant's businesses) and each rule version published and in force today in India, it
calls the engine's ``POST /v1/applicability-engine/businesses/{registration}/decisions`` on the
internal listener for the tenant. The engine reads the registration's profile snapshot and the
rule version, stores the decision and writes applicability.decided to its outbox; the worker's
relay publishes it, and the obligation service's consumer makes the obligations.

The Idempotency-Key the engine requires is derived from the tenant, the registration, the version
and the day in India, so a second run on the same day answers with the same decisions instead of
storing new ones. ``fresh`` sends new keys, for a new decision after the profile changed.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Final
from uuid import UUID, uuid4, uuid5

from cw_demo.product.client import Product, as_tenant, ok
from cw_demo.product.tenants import TENANTS, SyntheticBusiness, SyntheticTenant

RULEBOOK: Final = "/v1/rulebook"
ENGINE: Final = "/v1/applicability-engine"
IST: Final = timezone(timedelta(hours=5, minutes=30))
PAGE: Final = 500
KEY_NAMESPACE: Final = UUID("6f3c0d2e-41a5-4c8e-9a71-0c5d1b2e3f40")
"""The namespace of the derived Idempotency-Keys; any fixed UUID would do."""
IDEMPOTENCY_HEADER: Final = "Idempotency-Key"
REPLAYED_HEADER: Final = "Idempotent-Replayed"


@dataclass(frozen=True, slots=True)
class SeededRegistration:
    tenant: SyntheticTenant
    business: SyntheticBusiness
    entity_id: str
    registration_id: str


@dataclass(frozen=True, slots=True)
class Decision:
    tenant: str
    business: str
    registration_id: str
    rule_key: str
    rule_version_id: str
    version: int
    result: str
    needs_review: bool
    decision_id: str
    replayed: bool
    """The engine answered with the decision it made earlier today for the same key."""


def today_in_india(now: datetime) -> date:
    return now.astimezone(IST).date()


def published_in_force(product: Product, as_of: date) -> list[dict[str, Any]]:
    """Every rule version published and in force on ``as_of``, by rule key."""
    found: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        params: dict[str, str | int] = {"as_of": as_of.isoformat(), "limit": PAGE}
        if after is not None:
            params["after"] = after
        page: list[dict[str, Any]] = ok(
            product.internal.get(f"{RULEBOOK}/rule-versions", params=params)
        )
        found.extend(version for version in page if version["status"] == "published")
        if len(page) < PAGE:
            return found
        after = str(page[-1]["rule_key"])


def registrations(product: Product, tenant: SyntheticTenant) -> list[SeededRegistration]:
    """The tenant's seeded registrations, found by their GSTINs among its businesses; empty
    before the seed has run."""
    headers = as_tenant(tenant.tenant_id)
    listed = ok(product.internal.get("/v1/businesses", params={"limit": 100}, headers=headers))
    wanted = {business.gstin: business for business in tenant.businesses}
    found: list[SeededRegistration] = []
    for summary in listed["items"]:
        if not wanted.keys() & set(summary["gstins"]):
            continue
        business = ok(product.internal.get(f"/v1/businesses/{summary['id']}", headers=headers))
        for registration in business["registrations"]:
            match = wanted.get(str(registration["key"]))
            if match is not None:
                found.append(
                    SeededRegistration(tenant, match, str(business["id"]), str(registration["id"]))
                )
    order = [business.key for business in tenant.businesses]
    return sorted(found, key=lambda seeded: order.index(seeded.business.key))


def idempotency_key(registration: SeededRegistration, version_id: str, day: date) -> str:
    """The same key for the same tenant, registration, version and day."""
    name = f"{registration.tenant.tenant_id}:{registration.registration_id}:{version_id}:{day}"
    return str(uuid5(KEY_NAMESPACE, name))


def evaluate(
    product: Product,
    tenants: Sequence[SyntheticTenant] = TENANTS,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    fresh: bool = False,
) -> list[Decision]:
    day = today_in_india(now())
    versions = published_in_force(product, day)
    decisions: list[Decision] = []
    for tenant in tenants:
        for registration in registrations(product, tenant):
            for version in versions:
                version_id = str(version["rule_version_id"])
                key = str(uuid4()) if fresh else idempotency_key(registration, version_id, day)
                answer = product.internal.post(
                    f"{ENGINE}/businesses/{registration.registration_id}/decisions",
                    json={"rule_version_id": version_id},
                    headers=as_tenant(tenant.tenant_id, **{IDEMPOTENCY_HEADER: key}),
                )
                body = ok(answer, 201)
                decisions.append(
                    Decision(
                        tenant=tenant.key,
                        business=registration.business.key,
                        registration_id=registration.registration_id,
                        rule_key=str(version["rule_key"]),
                        rule_version_id=version_id,
                        version=int(version["version"]),
                        result=str(body["result"]),
                        needs_review=bool(body["needs_review"]),
                        decision_id=str(body["decision_id"]),
                        replayed=answer.headers.get(REPLAYED_HEADER) == "true",
                    )
                )
    return decisions
