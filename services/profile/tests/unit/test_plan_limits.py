"""The plan's registration limit: the use cases refuse a new GSTIN past it (402), the identity
client reads it with a cache and fails open, and the flag decides whether it is asked at all."""

from collections.abc import Callable, Generator
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient

import ontology as ontology_package
from domain_kernel.identifiers import Gstin
from domain_kernel.ids import TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.application.businesses import AddRegistration, CreateBusiness
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import EntitlementsMisconfiguredError, PlanLimitReachedError
from profile_service.domain.flags import PLAN_LIMITS
from profile_service.infrastructure.entitlements import (
    ENTITLEMENTS_PATH,
    FlaggedEntitlements,
    HttpEntitlements,
    UnlimitedEntitlements,
)
from profile_service.infrastructure.lookup import DEMO_LOOKUPS, StaticLookupProvider
from profile_service.infrastructure.memory import MemoryStore
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_DELHI, GSTIN_KARNATAKA, TENANT, FixedFlags, clock
from py_common.auth import ServiceTokenUnavailableError

GSTIN_OTHER = Gstin("29BBBBB2222B1Z5")
BASE = "http://identity.test"


class Limit:
    """A reader that answers a fixed limit and counts how often it was asked."""

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.asked = 0

    def registration_limit(self, tenant_id: TenantId) -> int | None:
        self.asked += 1
        return self.limit


def use_cases(limit: Limit) -> tuple[MemoryStore, CreateBusiness, AddRegistration, RegisterNodes]:
    store = MemoryStore()
    ontology = ontology_package.load()
    prefill = PrefillFromGstin(
        store, StaticLookupProvider(DEMO_LOOKUPS), ontology, FixedFlags(), clock=clock
    )
    return (
        store,
        CreateBusiness(store, ontology, prefill, clock=clock, entitlements=limit),
        AddRegistration(store, prefill, clock=clock, entitlements=limit),
        RegisterNodes(store, clock=clock, entitlements=limit),
    )


def registrations(store: MemoryStore) -> int:
    with store(TENANT) as uow:
        return uow.profiles.count(AttributeLevel.REGISTRATION)


def test_a_new_registration_past_the_limit_is_refused_and_a_known_one_is_found() -> None:
    limit = Limit(1)
    store, create, add, register = use_cases(limit)
    created = create.run(TENANT, name="Example Traders", gstin=GSTIN_KARNATAKA)
    with pytest.raises(PlanLimitReachedError) as refused:
        add.run(TENANT, created.business.id, GSTIN_DELHI)
    assert (refused.value.limit, refused.value.used) == (1, 1)
    assert str(GSTIN_DELHI) not in str(refused.value)
    with pytest.raises(PlanLimitReachedError):
        create.run(TENANT, name="Example Stores", gstin=GSTIN_OTHER)
    with pytest.raises(PlanLimitReachedError):
        register.registration(TENANT, GSTIN_OTHER, "Example Stores")
    again = create.run(TENANT, name="Example Traders", gstin=GSTIN_KARNATAKA)
    assert not again.created
    assert registrations(store) == 1
    limit.limit = 2
    add.run(TENANT, created.business.id, GSTIN_DELHI)
    assert registrations(store) == 2


def test_no_limit_and_a_pan_alone_never_count() -> None:
    limit = Limit(None)
    store, create, add, _ = use_cases(limit)
    created = create.run(TENANT, name="Example Traders", gstin=GSTIN_KARNATAKA)
    add.run(TENANT, created.business.id, GSTIN_DELHI)
    assert registrations(store) == 2
    zero = Limit(0)
    _, create_none, _, _ = use_cases(zero)
    create_none.run(TENANT, name="Example Traders", pan=GSTIN_KARNATAKA.pan)
    assert zero.asked == 0, "a business without a GSTIN creates no registration"


def entitlements(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    auth: httpx2.Auth | None = None,
    now: list[float] | None = None,
) -> HttpEntitlements:
    clock_now = now if now is not None else [0.0]
    client = httpx2.Client(base_url=BASE, transport=httpx2.MockTransport(handler))
    return HttpEntitlements(BASE, client=client, auth=auth, monotonic=lambda: clock_now[0])


def answer(registrations: int | None) -> dict[str, Any]:
    return {
        "plan_key": "free",
        "status": "free",
        "limits": {"registrations": registrations, "seats": 1},
        "enforced": True,
    }


def test_the_client_reads_the_limit_and_keeps_it_for_a_minute() -> None:
    seen: list[httpx2.Request] = []
    now = [0.0]

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=answer(3))

    reader = entitlements(handler, now=now)
    assert reader.registration_limit(TENANT) == 3
    assert reader.registration_limit(TENANT) == 3
    assert len(seen) == 1
    assert seen[0].url.path == ENTITLEMENTS_PATH
    assert seen[0].headers["x-tenant-id"] == str(TENANT)
    now[0] = 61.0
    assert reader.registration_limit(TENANT) == 3
    assert len(seen) == 2
    unlimited = entitlements(lambda _: httpx2.Response(200, json=answer(None)))
    assert unlimited.registration_limit(TENANT) is None


def test_the_limit_counts_only_when_identity_says_enforced() -> None:
    """m5: identity is the single source of truth: profile's flag on and enforced false is no
    limit, cached like any answer."""
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json={**answer(1), "enforced": False})

    reader = entitlements(handler)
    assert reader.registration_limit(TENANT) is None
    assert reader.registration_limit(TENANT) is None
    assert calls == 1


@pytest.mark.parametrize(
    "handler",
    [
        lambda _: httpx2.Response(503, json={"type": "x"}),
        lambda _: httpx2.Response(500),
    ],
    ids=["503", "500"],
)
def test_a_5xx_fails_open_and_is_asked_again_after_ten_seconds(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    """m4: a failure is kept for 10 s, so an outage costs one call per tenant every 10 s."""
    calls = 0
    now = [0.0]

    def counted(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return handler(request)

    reader = entitlements(counted, now=now)
    assert reader.registration_limit(TENANT) is None
    now[0] = 9.0
    assert reader.registration_limit(TENANT) is None
    assert calls == 1, "the failure is kept for 10 s"
    now[0] = 10.0
    assert reader.registration_limit(TENANT) is None
    assert calls == 2


@pytest.mark.parametrize(
    "handler",
    [
        lambda _: httpx2.Response(401, json={"type": "auth-token-required"}),
        lambda _: httpx2.Response(403, json={"type": "auth-forbidden"}),
        lambda _: httpx2.Response(404),
        lambda _: httpx2.Response(200, text="not json"),
        lambda _: httpx2.Response(200, json={"limits": {}}),
        lambda _: httpx2.Response(200, json=answer(-1)),
        lambda _: httpx2.Response(200, json={**answer(1), "limits": {"registrations": True}}),
        lambda _: httpx2.Response(200, json={"limits": {"registrations": 1}}),
    ],
    ids=["401", "403", "404", "not-json", "no-limit-key", "negative", "bool", "no-enforced"],
)
def test_a_misconfiguration_refuses_with_503_and_never_fails_open(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    """m3: a missing client or scope (401, 403) or an answer profile cannot read is not an
    outage: the registration is refused, with the misconfiguration named and no tenant data."""
    calls = 0
    now = [0.0]

    def counted(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return handler(request)

    reader = entitlements(counted, now=now)
    with pytest.raises(EntitlementsMisconfiguredError) as refused:
        reader.registration_limit(TENANT)
    assert "CW_SERVICE_CLIENT_ID" in str(refused.value)
    assert str(TENANT) not in str(refused.value)
    with pytest.raises(EntitlementsMisconfiguredError):
        reader.registration_limit(TENANT)
    assert calls == 1
    now[0] = 10.0
    with pytest.raises(EntitlementsMisconfiguredError):
        reader.registration_limit(TENANT)
    assert calls == 2


def test_an_unreachable_identity_or_a_missing_token_fails_open() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    assert entitlements(down).registration_limit(TENANT) is None

    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    assert entitlements(slow).registration_limit(TENANT) is None

    class NoToken(httpx2.Auth):
        def auth_flow(
            self, request: httpx2.Request
        ) -> Generator[httpx2.Request, httpx2.Response, None]:
            if request.url.path:
                raise ServiceTokenUnavailableError("no token")
            yield request  # pragma: no cover

    tokenless = entitlements(lambda _: httpx2.Response(200, json=answer(1)), auth=NoToken())
    assert tokenless.registration_limit(TENANT) is None


def test_the_flag_decides_whether_identity_is_asked() -> None:
    limit = Limit(1)
    off = FlaggedEntitlements(FixedFlags(), limit)
    assert off.registration_limit(TENANT) is None
    assert limit.asked == 0
    on = FlaggedEntitlements(FixedFlags(on=[PLAN_LIMITS], tenants=[TENANT]), limit)
    assert on.registration_limit(TENANT) == 1
    assert on.registration_limit(TenantId.new()) is None
    assert UnlimitedEntitlements().registration_limit(TENANT) is None


def test_the_route_answers_402_with_the_limit_and_the_count() -> None:
    settings = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="memory",
        profile_gstin_lookup="static",
    )
    with TestClient(build_app(settings, flags=FixedFlags(), entitlements=Limit(1))) as client:
        headers = {"x-tenant-id": str(TENANT)}
        first = client.post(
            "/v1/businesses",
            json={"name": "Example Traders", "gstin": str(GSTIN_KARNATAKA)},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/v1/businesses",
            json={"name": "Example Stores", "gstin": str(GSTIN_OTHER)},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        assert second.status_code == 402, second.text
        problem = second.json()
        assert problem["type"].endswith("profile-plan-limit-reached")
        assert (problem["limit"], problem["used"]) == (1, 1)
        assert str(GSTIN_OTHER) not in second.text
        plain = client.post(
            "/v1/profile/registrations",
            json={"gstin": str(GSTIN_OTHER), "name": "Example Stores"},
            headers=headers,
        )
        assert plain.status_code == 402, plain.text


def test_the_route_answers_503_when_identity_refuses_profile() -> None:
    settings = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="memory",
        profile_gstin_lookup="static",
    )
    refusing = entitlements(lambda _: httpx2.Response(401, json={"type": "auth-token-required"}))
    with TestClient(build_app(settings, flags=FixedFlags(), entitlements=refusing)) as client:
        refused = client.post(
            "/v1/businesses",
            json={"name": "Example Traders", "gstin": str(GSTIN_KARNATAKA)},
            headers={"x-tenant-id": str(TENANT), "Idempotency-Key": str(uuid4())},
        )
    assert refused.status_code == 503, refused.text
    assert refused.json()["type"].endswith("profile-entitlements-misconfigured")
    assert str(GSTIN_KARNATAKA) not in refused.text
