"""The regulatory team's admin reads (``/v1/identity/admin/tenants``) on the memory store: the
tenant list with its plan and user counts, one tenant, and a tenant's users read with a reason
that lands in the tenant's audit trail; who is refused; and the directory twin itself."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import ANONYMOUS, Principal, Role, Scope
from domain_kernel.ids import TenantId, UserId
from identity.api.admin import CURSOR_SCOPE
from identity.api.schemas import AdminTenantKeyset
from identity.application.admin import USERS_READ, ReadTenantUsers
from identity.application.bootstrap import BootstrapInternalTenant
from identity.domain.billing import Subscription, SubscriptionStatus
from identity.domain.directory import TenantSummary
from identity.domain.errors import SessionRevokedError
from identity.domain.tenancy import Contact, TenantKind, TenantStatus
from identity.infrastructure.memory import MemoryStore, MemoryTenantDirectory
from identity.main import build_app
from identity.testing import DEV_CLIENT_SECRET, identity_settings
from py_common.auth.errors import AuthForbiddenError
from py_common.auth.testing import bearer
from py_common.pagination import decode_cursor

TENANTS = "/v1/identity/admin/tenants"
AUDIT = "/v1/identity/audit"
OWNER_PHONE = "+919876543210"
OTHER_OWNER_PHONE = "+919811111111"
STAFF_PHONE = "+919812345678"
ADMIN_EMAIL = "admin@example.org"
REASON = {"x-reason": "Example support case 2000-01: the owner asked who holds the owner role"}
AT = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)


def provider_token(client: TestClient, *, phone: str = "", email: str = "", aal: str = "") -> str:
    body: dict[str, str] = {"phone": phone} if phone else {"email": email}
    if aal:
        body["aal"] = aal
    response = client.post("/v1/identity/dev/provider-tokens", json=body)
    assert response.status_code == 200, response.text
    token: str = response.json()["provider_token"]
    return token


def sign_up(client: TestClient, phone: str, name: str) -> dict[str, Any]:
    created = client.post(
        "/v1/identity/tenants",
        json={
            "kind": "business",
            "name": name,
            "provider_token": provider_token(client, phone=phone),
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def session(client: TestClient, **contact: str) -> dict[str, str]:
    exchanged = client.post(
        "/v1/identity/sessions", json={"provider_token": provider_token(client, **contact)}
    )
    assert exchanged.status_code == 200, exchanged.text
    return bearer(exchanged.json()["access_token"])


def store_of(app: FastAPI) -> MemoryStore:
    store = app.state.wiring.unit_of_work
    assert isinstance(store, MemoryStore)
    return store


def bootstrap_admin(app: FastAPI) -> TenantId:
    wiring = app.state.wiring
    tenant, _ = BootstrapInternalTenant(wiring.unit_of_work, wiring.provider).run(
        "Example regulatory team", Contact(email=ADMIN_EMAIL)
    )
    return tenant.id


def subscribe(
    app: FastAPI, tenant: str, plan_key: str, status: SubscriptionStatus, at: datetime
) -> None:
    """A subscription in the ledger, as the billing routes would have recorded it."""
    with store_of(app)(TenantId.parse(tenant)) as uow:
        assert uow.billing.add_subscription(
            Subscription(
                tenant_id=TenantId.parse(tenant),
                plan_key=plan_key,
                provider_subscription_id=f"sub_{uuid4().hex[:12]}",
                status=status,
                started_at=at,
            )
        )


@pytest.fixture
def app() -> FastAPI:
    return build_app(identity_settings(auth_mode="token"))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class Setup:
    """Two businesses (one with a staff user and two subscriptions), the internal tenant and
    its admin's session."""

    def __init__(self, app: FastAPI, client: TestClient) -> None:
        self.traders = sign_up(client, OWNER_PHONE, "Example Traders")
        self.stores = sign_up(client, OTHER_OWNER_PHONE, "Example Stores")
        self.owner = bearer(self.traders["session"]["access_token"])
        invited = client.post(
            "/v1/identity/users",
            json={"phone": STAFF_PHONE, "roles": ["staff"]},
            headers=self.owner,
        )
        assert invited.status_code == 201, invited.text
        self.staff = invited.json()
        traders_id = self.traders["tenant"]["id"]
        subscribe(app, traders_id, "starter", SubscriptionStatus.CANCELLED, AT)
        subscribe(app, traders_id, "growth", SubscriptionStatus.ACTIVE, AT.replace(month=7))
        self.internal = bootstrap_admin(app)
        self.admin = session(client, email=ADMIN_EMAIL, aal="aal2")


@pytest.fixture
def setup(app: FastAPI, client: TestClient) -> Setup:
    return Setup(app, client)


def test_the_admin_lists_every_tenant_with_its_plan_and_counts(
    client: TestClient, setup: Setup
) -> None:
    page = client.get(TENANTS, headers=setup.admin)
    assert page.status_code == 200, page.text
    listed = {item["id"]: item for item in page.json()["items"]}
    assert set(listed) == {
        setup.traders["tenant"]["id"],
        setup.stores["tenant"]["id"],
        str(setup.internal),
    }
    traders = listed[setup.traders["tenant"]["id"]]
    assert (traders["kind"], traders["name"], traders["status"]) == (
        "business",
        "Example Traders",
        "active",
    )
    assert (traders["plan_key"], traders["subscription_status"]) == ("growth", "active"), (
        "the newest subscription, whatever its status"
    )
    assert (traders["users"], traders["active_users"]) == (2, 2)
    stores = listed[setup.stores["tenant"]["id"]]
    assert (stores["plan_key"], stores["subscription_status"], stores["users"]) == (None, None, 1)
    assert page.json()["next_cursor"] is None
    assert "+91" not in page.text, "no phone number in the list"
    assert "@" not in page.text, "no email address in the list"
    assert [item["name"] for item in page.json()["items"]] == [
        "Example Stores",
        "Example Traders",
        "Example regulatory team",
    ], "in the order of (name, id)"


def test_the_list_pages_and_searches_by_name_or_id(client: TestClient, setup: Setup) -> None:
    first = client.get(TENANTS, params={"limit": 2}, headers=setup.admin).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    keyset = decode_cursor(first["next_cursor"], CURSOR_SCOPE, AdminTenantKeyset)
    assert str(keyset.id) == first["items"][-1]["id"]
    rest = client.get(
        TENANTS, params={"limit": 2, "cursor": first["next_cursor"]}, headers=setup.admin
    ).json()
    assert [item["id"] for item in rest["items"]] == [str(setup.internal)]
    assert rest["next_cursor"] is None
    by_name = client.get(TENANTS, params={"q": "STORES"}, headers=setup.admin).json()
    assert [item["name"] for item in by_name["items"]] == ["Example Stores"]
    padded = client.get(TENANTS, params={"q": "  stores\t"}, headers=setup.admin).json()
    assert [item["name"] for item in padded["items"]] == ["Example Stores"], "q is trimmed once"
    by_id = client.get(
        TENANTS, params={"q": setup.traders["tenant"]["id"]}, headers=setup.admin
    ).json()
    assert [item["name"] for item in by_id["items"]] == ["Example Traders"]
    none = client.get(TENANTS, params={"q": "nobody"}, headers=setup.admin).json()
    assert none["items"] == []
    foreign = client.get(TENANTS, params={"cursor": "bm90LWEtY3Vyc29y"}, headers=setup.admin)
    assert foreign.status_code == 422
    assert foreign.json()["type"].endswith(":pagination-cursor-invalid")
    largest = client.get(TENANTS, params={"limit": 200}, headers=setup.admin)
    assert largest.status_code == 200, "a full page reads one row past it"
    assert len(largest.json()["items"]) == 3
    too_many = client.get(TENANTS, params={"limit": 201}, headers=setup.admin)
    assert too_many.status_code == 422


def test_the_admin_reads_one_tenant_and_404_for_an_unknown_id(
    client: TestClient, setup: Setup
) -> None:
    one = client.get(f"{TENANTS}/{setup.stores['tenant']['id']}", headers=setup.admin)
    assert one.status_code == 200, one.text
    assert (one.json()["name"], one.json()["users"]) == ("Example Stores", 1)
    unknown = client.get(f"{TENANTS}/{uuid4()}", headers=setup.admin)
    assert unknown.status_code == 404
    assert unknown.json()["type"].endswith(":identity-tenant-not-found")


def test_the_users_read_needs_a_reason_and_lands_in_the_tenant_s_trail(
    client: TestClient, setup: Setup
) -> None:
    tenant = setup.traders["tenant"]["id"]
    users = client.get(f"{TENANTS}/{tenant}/users", headers={**setup.admin, **REASON})
    assert users.status_code == 200, users.text
    assert [(user["id"], user["roles"]) for user in users.json()["items"]] == [
        (setup.traders["user"]["id"], ["owner"]),
        (setup.staff["id"], ["staff"]),
    ]
    without = client.get(f"{TENANTS}/{tenant}/users", headers=setup.admin)
    assert without.status_code == 422, without.text
    assert without.json()["type"].endswith(":request-invalid")
    # A blank reason is refused at the edge as a missing one is, whatever whitespace it holds
    # (the test client hands the header over as given, with no HTTP parser to trim it).
    for blank in ("", "   ", "\t", " \t "):
        refused = client.get(
            f"{TENANTS}/{tenant}/users", headers={**setup.admin, "x-reason": blank}
        )
        assert refused.status_code == 422, (repr(blank), refused.text)
        assert refused.json()["type"].endswith(":request-invalid"), repr(blank)
    unknown = client.get(f"{TENANTS}/{uuid4()}/users", headers={**setup.admin, **REASON})
    assert unknown.status_code == 404

    # The tenant's owner sees the read in their trail, with the reason and the admin as actor;
    # the admin's own trail (the platform's rows and the internal tenant's) does not hold it.
    trail = client.get(AUDIT, params={"action": USERS_READ}, headers=setup.owner).json()["items"]
    assert len(trail) == 1, "one row per read"
    (entry,) = trail
    assert (entry["tenant_id"], entry["subject"], entry["reason"]) == (
        tenant,
        {"type": "tenant", "id": tenant},
        REASON["x-reason"],
    )
    assert entry["actor"]["kind"] == "user"
    assert entry["actor"]["label"] == "admin"
    assert entry["after"] == {"users": 2}
    assert entry["before"] is None
    assert "+91" not in str(entry)
    mine = client.get(AUDIT, params={"action": USERS_READ}, headers=setup.admin).json()["items"]
    assert mine == []
    # A second read is a second row; the reason lands trimmed of surrounding whitespace.
    padded = client.get(
        f"{TENANTS}/{tenant}/users",
        headers={**setup.admin, "x-reason": f"  {REASON['x-reason']}\t"},
    )
    assert padded.status_code == 200, padded.text
    again = client.get(AUDIT, params={"action": USERS_READ}, headers=setup.owner).json()
    assert len(again["items"]) == 2
    assert {item["reason"] for item in again["items"]} == {REASON["x-reason"]}


def test_owners_staff_services_and_callers_without_a_token_are_refused(
    client: TestClient, setup: Setup
) -> None:
    tenant = setup.traders["tenant"]["id"]
    for headers in (setup.owner, session(client, phone=STAFF_PHONE)):
        for path in (TENANTS, f"{TENANTS}/{tenant}", f"{TENANTS}/{tenant}/users"):
            refused = client.get(path, headers={**headers, **REASON})
            assert refused.status_code == 403, (path, refused.text)
            assert refused.json()["type"].endswith(":auth-forbidden")
    service = client.post(
        "/v1/identity/service-tokens",
        json={"client_id": "whatsapp-bot", "client_secret": DEV_CLIENT_SECRET},
    ).json()["access_token"]
    assert client.get(TENANTS, headers=bearer(service)).status_code == 403
    missing = client.get(TENANTS, headers=REASON)
    assert missing.status_code == 401
    assert missing.json()["type"].endswith(":auth-token-required")
    assert (
        client.get(AUDIT, params={"action": USERS_READ}, headers=setup.owner).json()["items"] == []
    ), "a refused read writes nothing"


def test_a_demoted_admin_is_refused_at_once(app: FastAPI, client: TestClient, setup: Setup) -> None:
    """The use case checks the session against the store, as the user routes do."""
    with store_of(app)(setup.internal) as uow:
        users = uow.users.list()
    (admin_user,) = [user for user in users if user.contact.email == ADMIN_EMAIL]
    stale = Principal.user(
        admin_user.id, setup.internal, admin_user.roles, mfa=True, session_version=99
    )
    with pytest.raises(Exception, match="session"):
        app.state.wiring.list_tenants.run(stale, limit=10)


def test_in_header_mode_the_anonymous_caller_passes_and_dual_mode_needs_the_token() -> None:
    with TestClient(build_app(identity_settings())) as client:
        created = sign_up(client, OWNER_PHONE, "Example Traders")
        listed = client.get(TENANTS)
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()["items"]] == [created["tenant"]["id"]]
        users = client.get(f"{TENANTS}/{created['tenant']['id']}/users", headers=REASON)
        assert users.status_code == 200, users.text
        assert client.get(f"{TENANTS}/{created['tenant']['id']}/users").status_code == 422
        trail = client.get(
            AUDIT,
            params={"action": USERS_READ},
            headers={"x-tenant-id": created["tenant"]["id"]},
        ).json()["items"]
        assert [item["actor"]["label"] for item in trail] == ["system:identity"]
    with TestClient(build_app(identity_settings(auth_mode="dual"))) as client:
        sign_up(client, OWNER_PHONE, "Example Traders")
        assert client.get(TENANTS).status_code == 401


def test_the_use_case_refuses_a_blank_reason_and_a_customer_s_admin() -> None:
    store = MemoryStore()
    read = ReadTenantUsers(store)
    with pytest.raises(ValueError, match="reason"):
        read.run(ANONYMOUS, TenantId.new(), reason="   ")
    nobody = Principal.user(UserId.new(), TenantId.new(), [Role.OWNER])
    with pytest.raises(SessionRevokedError):
        read.run(nobody, TenantId.new(), reason="Example")
    service = Principal.service("whatsapp-bot", [Scope.TENANT_ACT])
    with pytest.raises(AuthForbiddenError):
        read.run(service, TenantId.new(), reason="Example")


def test_the_memory_directory_mirrors_the_function(app: FastAPI, client: TestClient) -> None:
    setup = Setup(app, client)
    directory = MemoryTenantDirectory(store_of(app))
    page = directory.page("", None, 10)
    assert [summary.name for summary in page] == [
        "Example Stores",
        "Example Traders",
        "Example regulatory team",
    ]
    traders = next(s for s in page if s.name == "Example Traders")
    assert isinstance(traders, TenantSummary)
    assert (traders.kind, traders.status) == (TenantKind.BUSINESS, TenantStatus.ACTIVE)
    assert (traders.plan_key, traders.subscription_status) == ("growth", SubscriptionStatus.ACTIVE)
    assert (traders.users, traders.active_users) == (2, 2)
    assert directory.page("", page[0].id, 10) == page[1:]
    assert directory.page("", TenantId.new(), 10) == [], "a cursor naming no tenant reads nothing"
    assert directory.page("traders", None, 10) == [traders]
    assert directory.page(str(traders.id), None, 10) == [traders]
    assert directory.page("traders ", None, 10) == [], "matched as given, as the function does"
    assert directory.page(f"{traders.id} ", None, 10) == [], "the use case trims q, not the twin"
    assert directory.get(traders.id) == traders
    assert directory.get(TenantId.new()) is None
    assert directory.page("", None, 1) == page[:1]
    assert setup.internal in {summary.id for summary in page}
