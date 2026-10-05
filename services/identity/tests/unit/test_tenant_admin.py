"""What tenant admins do: list, invite, change roles and disable users, through the use cases and
the routes, in header and token mode."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domain_kernel.access import ANONYMOUS, Principal, Role, Scope
from domain_kernel.ids import TenantId, UserId
from identity.application.sessions import user_principal
from identity.application.tenancy import (
    ChangeRoles,
    CreateTenant,
    DisableUser,
    InviteUser,
    ListUsers,
    ReadMembership,
)
from identity.domain.errors import (
    LastAdminError,
    ProviderAccountExistsError,
    ProviderUnavailableError,
    RoleNotAllowedError,
    SessionRevokedError,
    SubjectRegisteredError,
    TenantNotFoundError,
    UserNotFoundError,
)
from identity.domain.events import RoleChangeReason, UserRoleChanged
from identity.domain.repository import UnitOfWork
from identity.domain.tenancy import Contact, TenantKind, User
from identity.infrastructure.memory import MemoryStore, MemoryUnitOfWork, MemoryUserRepository
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.main import build_app
from identity.testing import DEV_CLIENT_SECRET, identity_settings
from py_common.auth import TokenIssuer
from py_common.auth.errors import AuthForbiddenError
from py_common.auth.testing import TestIssuer, bearer

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
"""When invitations happen: after sign-up, so the owner lists first."""
OWNER_PHONE = "+919876543210"
STAFF_PHONE = "+919812345678"
USERS = "/v1/identity/users"


class Team:
    """A business signed up on the memory store, and the admin use cases over it."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.provider = FakeIdentityProvider()
        issuer = TestIssuer()
        minter = IssuerMinter(
            TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
        )
        created = CreateTenant(
            self.store, self.provider, minter, ttl=timedelta(minutes=10), clock=lambda: NOW
        ).run(self.provider.issue(phone=OWNER_PHONE), TenantKind.BUSINESS, "Acme Traders")
        self.tenant, self.owner = created.tenant, created.user
        self.as_owner = created.session.principal
        self.list = ListUsers(self.store)
        self.invite = InviteUser(self.store, self.provider, clock=lambda: LATER)
        self.change = ChangeRoles(self.store, clock=lambda: NOW)
        self.disable = DisableUser(self.store, clock=lambda: NOW)

    def events(self) -> list[UserRoleChanged]:
        return [event for event in self.store.events if isinstance(event, UserRoleChanged)]


@pytest.fixture
def team() -> Team:
    return Team()


# ---------------------------------------------------------------- the use cases


def test_an_owner_invites_promotes_and_disables_a_colleague(team: Team) -> None:
    staff = team.invite.run(
        team.tenant.id,
        team.as_owner,
        contact=Contact(phone=STAFF_PHONE),
        roles=[Role.STAFF],
        display_name="Ravi",
    )
    assert staff.roles == {Role.STAFF}
    assert (staff.session_version, staff.display_name) == (0, "Ravi")
    assert team.provider.lookup(staff.provider_subject) is not None
    assert [user.id for user in team.list.run(team.tenant.id, team.as_owner)] == [
        team.owner.id,
        staff.id,
    ]
    promoted = team.change.run(
        team.tenant.id, team.as_owner, staff.id, [Role.STAFF, Role.COMPLIANCE_LEAD]
    )
    assert promoted.session_version == 1
    assert team.change.run(team.tenant.id, team.as_owner, staff.id, promoted.roles) == promoted
    disabled = team.disable.run(team.tenant.id, team.as_owner, staff.id)
    assert (disabled.is_active, disabled.session_version) == (False, 2)
    assert team.disable.run(team.tenant.id, team.as_owner, staff.id) == disabled
    invited, changed, gone = team.events()[1:]
    assert (invited.reason, invited.roles, invited.changed_by) == (
        RoleChangeReason.INVITED,
        (Role.STAFF,),
        team.owner.id,
    )
    assert (changed.reason, changed.previous_roles, changed.roles, changed.session_version) == (
        RoleChangeReason.ROLES_CHANGED,
        (Role.STAFF,),
        (Role.COMPLIANCE_LEAD, Role.STAFF),
        1,
    )
    assert (gone.reason, gone.roles, gone.previous_roles) == (
        RoleChangeReason.DISABLED,
        (),
        (Role.COMPLIANCE_LEAD, Role.STAFF),
    )


def test_the_last_owner_stays(team: Team) -> None:
    with pytest.raises(LastAdminError):
        team.change.run(team.tenant.id, team.as_owner, team.owner.id, [Role.STAFF])
    with pytest.raises(LastAdminError):
        team.disable.run(team.tenant.id, team.as_owner, team.owner.id)


def test_an_admin_whose_session_is_older_than_their_roles_is_refused(team: Team) -> None:
    second = team.invite.run(
        team.tenant.id, team.as_owner, contact=Contact(phone=STAFF_PHONE), roles=[Role.OWNER]
    )
    team.change.run(team.tenant.id, team.as_owner, team.owner.id, [Role.STAFF])
    with pytest.raises(SessionRevokedError):
        team.list.run(team.tenant.id, team.as_owner)
    as_staff = user_principal(team.store.users[team.owner.id], mfa=False)
    with pytest.raises(AuthForbiddenError):
        team.list.run(team.tenant.id, as_staff)
    as_second = user_principal(second, mfa=False)
    assert len(team.list.run(team.tenant.id, as_second)) == 2


def test_without_a_token_the_tenant_header_is_trusted_and_nobody_is_named(team: Team) -> None:
    staff = team.invite.run(
        team.tenant.id, ANONYMOUS, contact=Contact(email="staff@acme.example"), roles=[Role.STAFF]
    )
    assert team.events()[-1].changed_by is None
    assert staff.contact.email == "staff@acme.example"
    with pytest.raises(TenantNotFoundError):
        team.list.run(TenantId.new(), ANONYMOUS)


def test_without_a_token_nobody_grants_an_admin_or_regulatory_role(team: Team) -> None:
    with pytest.raises(AuthForbiddenError, match="owner"):
        team.invite.run(
            team.tenant.id, ANONYMOUS, contact=Contact(phone=STAFF_PHONE), roles=[Role.OWNER]
        )
    assert team.provider.lookup(team.provider.subject_for(Contact(phone=STAFF_PHONE))) is None
    staff = team.invite.run(
        team.tenant.id, ANONYMOUS, contact=Contact(phone=STAFF_PHONE), roles=[Role.STAFF]
    )
    with pytest.raises(AuthForbiddenError, match="owner"):
        team.change.run(team.tenant.id, ANONYMOUS, staff.id, [Role.OWNER])
    lead = team.change.run(team.tenant.id, ANONYMOUS, staff.id, [Role.COMPLIANCE_LEAD])
    assert lead.roles == {Role.COMPLIANCE_LEAD}
    promoted = team.change.run(team.tenant.id, team.as_owner, staff.id, [Role.OWNER])
    assert promoted.roles == {Role.OWNER}
    kept = team.change.run(
        team.tenant.id, ANONYMOUS, team.owner.id, [Role.OWNER, Role.COMPLIANCE_LEAD]
    )
    assert kept.roles == {Role.OWNER, Role.COMPLIANCE_LEAD}, "a role already held is no grant"


def test_invitations_refuse_roles_the_kind_lacks_and_taken_addresses(team: Team) -> None:
    with pytest.raises(RoleNotAllowedError):
        team.invite.run(
            team.tenant.id, team.as_owner, contact=Contact(phone=STAFF_PHONE), roles=[Role.ANALYST]
        )
    team.invite.run(
        team.tenant.id, team.as_owner, contact=Contact(phone=STAFF_PHONE), roles=[Role.STAFF]
    )
    with pytest.raises(ProviderAccountExistsError):
        team.invite.run(
            team.tenant.id, team.as_owner, contact=Contact(phone=STAFF_PHONE), roles=[Role.STAFF]
        )
    with pytest.raises(SubjectRegisteredError):
        team.invite.run(
            team.tenant.id, team.as_owner, contact=Contact(phone=OWNER_PHONE), roles=[Role.STAFF]
        )
    owner_subject = team.provider.subject_for(Contact(phone=OWNER_PHONE))
    assert team.provider.lookup(owner_subject) is None, "the new account was removed again"


def test_a_failed_invitation_survives_a_provider_that_cannot_remove_the_account(
    team: Team,
) -> None:
    class Stuck(FakeIdentityProvider):
        def delete(self, subject: str) -> None:
            raise ProviderUnavailableError("down")

    stuck = InviteUser(team.store, Stuck(), clock=lambda: NOW)
    with pytest.raises(SubjectRegisteredError):
        stuck.run(
            team.tenant.id, team.as_owner, contact=Contact(phone=OWNER_PHONE), roles=[Role.STAFF]
        )


def test_an_unknown_user_is_not_found(team: Team) -> None:
    with pytest.raises(UserNotFoundError):
        team.change.run(team.tenant.id, team.as_owner, UserId.new(), [Role.STAFF])
    with pytest.raises(UserNotFoundError):
        team.disable.run(team.tenant.id, team.as_owner, UserId.new())


class EveryTenantsUsers(MemoryUserRepository):
    """User reads that ignore the tenant, as a database role that bypasses row-level security
    would see them without the queries' own filter."""

    def get(self, user_id: UserId) -> User | None:
        return self._users.get(user_id)

    def list(self) -> list[User]:
        return sorted(self._users.values(), key=lambda user: (user.created_at, user.id.value))


class BypassingStore(MemoryStore):
    @contextmanager
    def _open(self, tenant_id: TenantId | None) -> Iterator[UnitOfWork]:
        uow = MemoryUnitOfWork(self, tenant_id)
        uow.users = EveryTenantsUsers(uow._users, tenant_id)
        yield uow
        uow.commit(self)


def test_admins_reach_only_their_own_tenants_users_whatever_the_store_returns() -> None:
    store = BypassingStore()
    provider = FakeIdentityProvider()
    issuer = TestIssuer()
    minter = IssuerMinter(
        TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
    )
    create = CreateTenant(store, provider, minter, ttl=timedelta(minutes=10), clock=lambda: NOW)
    acme = create.run(provider.issue(phone=OWNER_PHONE), TenantKind.BUSINESS, "Acme Traders")
    other = create.run(provider.issue(phone=STAFF_PHONE), TenantKind.BUSINESS, "Other Traders")
    as_acme = acme.session.principal
    listed = ListUsers(store).run(acme.tenant.id, as_acme)
    assert [user.id for user in listed] == [acme.user.id]
    with pytest.raises(UserNotFoundError):
        ChangeRoles(store).run(acme.tenant.id, as_acme, other.user.id, [Role.STAFF])
    with pytest.raises(UserNotFoundError):
        DisableUser(store).run(acme.tenant.id, as_acme, other.user.id)
    with pytest.raises(UserNotFoundError):
        ReadMembership(store).run(acme.tenant.id, other.user.id)
    assert ReadMembership(store).run(acme.tenant.id, acme.user.id) == acme.user
    assert store.users[other.user.id] == other.user


# ---------------------------------------------------------------- the routes


def provider_token(client: TestClient, phone: str) -> str:
    response = client.post("/v1/identity/dev/provider-tokens", json={"phone": phone})
    token: str = response.json()["provider_token"]
    return token


def signed_up(client: TestClient) -> dict[str, Any]:
    created = client.post(
        "/v1/identity/tenants",
        json={
            "kind": "business",
            "name": "Acme Traders",
            "provider_token": provider_token(client, OWNER_PHONE),
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    with TestClient(build_app(identity_settings(auth_mode="token"))) as client:
        yield client


def test_the_team_routes_in_token_mode(token_mode: TestClient) -> None:
    created = signed_up(token_mode)
    owner = bearer(created["session"]["access_token"])
    invited = token_mode.post(
        USERS,
        json={"phone": STAFF_PHONE, "roles": ["staff"], "display_name": "Ravi"},
        headers=owner,
    )
    assert invited.status_code == 201, invited.text
    staff = invited.json()
    assert (staff["roles"], staff["status"], staff["display_name"]) == (["staff"], "active", "Ravi")
    listed = token_mode.get(USERS, headers=owner)
    assert [user["id"] for user in listed.json()["items"]] == [created["user"]["id"], staff["id"]]
    staff_session = token_mode.post(
        "/v1/identity/sessions", json={"provider_token": provider_token(token_mode, STAFF_PHONE)}
    ).json()
    as_staff = bearer(staff_session["access_token"])
    refused = token_mode.get(USERS, headers=as_staff)
    assert refused.status_code == 403
    assert refused.json()["type"].endswith(":auth-forbidden")
    changed = token_mode.put(
        f"{USERS}/{staff['id']}/roles", json={"roles": ["staff", "compliance_lead"]}, headers=owner
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["roles"], changed.json()["session_version"]) == (
        ["compliance_lead", "staff"],
        1,
    )
    revoked = token_mode.get("/v1/identity/me", headers=as_staff)
    assert revoked.json()["type"].endswith(":identity-session-revoked")
    disabled = token_mode.post(f"{USERS}/{staff['id']}/disable", headers=owner)
    assert (disabled.json()["status"], disabled.json()["session_version"]) == ("disabled", 2)
    signed_out = token_mode.post(
        "/v1/identity/sessions", json={"provider_token": provider_token(token_mode, STAFF_PHONE)}
    )
    assert signed_out.status_code == 403
    assert signed_out.json()["type"].endswith(":identity-user-disabled")


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "problem"),
    [
        ("put", "/{owner}/roles", {"roles": ["staff"]}, 409, "identity-last-admin"),
        ("post", "/{owner}/disable", None, 409, "identity-last-admin"),
        ("put", "/{random}/roles", {"roles": ["staff"]}, 404, "identity-user-not-found"),
        ("put", "/{owner}/roles", {"roles": ["analyst"]}, 422, "identity-role-not-allowed"),
        ("put", "/{owner}/roles", {"roles": []}, 422, "request-invalid"),
        ("post", "", {"roles": ["staff"]}, 422, "request-invalid"),
    ],
)
def test_the_team_routes_refuse(
    token_mode: TestClient,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    status: int,
    problem: str,
) -> None:
    created = signed_up(token_mode)
    owner = bearer(created["session"]["access_token"])
    url = USERS + path.format(owner=created["user"]["id"], random=uuid4())
    response = token_mode.request(method, url, json=body, headers=owner)
    assert response.status_code == status, response.text
    assert response.json()["type"].endswith(":" + problem)


def test_a_service_cannot_manage_users(token_mode: TestClient) -> None:
    created = signed_up(token_mode)
    service = token_mode.post(
        "/v1/identity/service-tokens",
        json={"client_id": "whatsapp-bot", "client_secret": DEV_CLIENT_SECRET},
    ).json()["access_token"]
    response = token_mode.get(
        USERS, headers={**bearer(service), "x-tenant-id": created["tenant"]["id"]}
    )
    assert response.status_code == 403


def test_the_team_routes_in_header_mode() -> None:
    with TestClient(build_app(identity_settings())) as client:
        created = signed_up(client)
        tenant = {"x-tenant-id": created["tenant"]["id"]}
        assert client.get(USERS).status_code == 401
        listed = client.get(USERS, headers=tenant)
        assert [user["roles"] for user in listed.json()["items"]] == [["owner"]]
        invited = client.post(
            USERS, json={"email": "staff@acme.example", "roles": ["staff"]}, headers=tenant
        )
        assert invited.status_code == 201
        unknown = client.get(USERS, headers={"x-tenant-id": str(uuid4())})
        assert unknown.status_code == 404
        assert unknown.json()["type"].endswith(":identity-tenant-not-found")


def test_header_mode_grants_no_admin_role_to_an_anonymous_caller() -> None:
    with TestClient(build_app(identity_settings())) as client:
        created = signed_up(client)
        tenant = {"x-tenant-id": created["tenant"]["id"]}
        owner = client.post(
            USERS, json={"email": "owner2@acme.example", "roles": ["owner"]}, headers=tenant
        )
        assert owner.status_code == 403, owner.text
        assert owner.json()["type"].endswith(":auth-forbidden")
        staff = client.post(
            USERS, json={"email": "staff@acme.example", "roles": ["staff"]}, headers=tenant
        ).json()
        promoted = client.put(
            f"{USERS}/{staff['id']}/roles", json={"roles": ["owner"]}, headers=tenant
        )
        assert promoted.status_code == 403, promoted.text


def test_dual_mode_user_routes_need_the_token() -> None:
    with TestClient(build_app(identity_settings(auth_mode="dual"))) as client:
        created = signed_up(client)
        owner = bearer(created["session"]["access_token"])
        tenant = {"x-tenant-id": created["tenant"]["id"]}
        staff = client.post(USERS, json={"phone": STAFF_PHONE, "roles": ["staff"]}, headers=owner)
        assert staff.status_code == 201, staff.text
        staff_id = staff.json()["id"]
        as_staff = bearer(
            client.post(
                "/v1/identity/sessions",
                json={"provider_token": provider_token(client, STAFF_PHONE)},
            ).json()["access_token"]
        )
        own_roles = f"{USERS}/{staff_id}/roles"
        refused = client.put(own_roles, json={"roles": ["owner"]}, headers=as_staff)
        assert refused.status_code == 403
        for method, path, body in (
            ("put", own_roles, {"roles": ["owner"]}),
            ("post", f"{USERS}/{created['user']['id']}/disable", None),
            ("post", USERS, {"email": "reviewer@acme.example", "roles": ["staff"]}),
            ("get", USERS, None),
        ):
            anonymous = client.request(method, path, json=body, headers=tenant)
            assert anonymous.status_code == 401, (path, anonymous.text)
            assert anonymous.json()["type"].endswith(":auth-token-required")
            assert anonymous.headers["www-authenticate"] == "Bearer"
        listed = client.get(USERS, headers=owner).json()["items"]
        assert [(user["roles"], user["status"]) for user in listed] == [
            (["owner"], "active"),
            (["staff"], "active"),
        ]


def test_a_service_principal_is_refused_by_the_use_cases(team: Team) -> None:
    service = Principal.service("qa", [Scope.TENANT_ACT])
    with pytest.raises(SessionRevokedError):
        team.list.run(team.tenant.id, service)


# ---------------------------------------------------------------- memberships


MEMBERSHIP = USERS + "/{user_id}/membership"


def service_bearer(client: TestClient, client_id: str) -> dict[str, str]:
    issued = client.post(
        "/v1/identity/service-tokens",
        json={"client_id": client_id, "client_secret": DEV_CLIENT_SECRET},
    )
    assert issued.status_code == 200, issued.text
    return bearer(issued.json()["access_token"])


def test_a_service_acting_for_the_tenant_reads_a_membership(token_mode: TestClient) -> None:
    created = signed_up(token_mode)
    owner = bearer(created["session"]["access_token"])
    tenant = created["tenant"]["id"]
    staff = token_mode.post(
        USERS, json={"phone": STAFF_PHONE, "roles": ["staff"]}, headers=owner
    ).json()
    acting = {**service_bearer(token_mode, "obligation"), "x-tenant-id": tenant}
    path = MEMBERSHIP.format(user_id=staff["id"])
    read = token_mode.get(path, headers=acting)
    assert read.status_code == 200, read.text
    assert read.json() == {
        "user_id": staff["id"],
        "tenant_id": tenant,
        "roles": ["staff"],
        "status": "active",
    }
    token_mode.post(f"{USERS}/{staff['id']}/disable", headers=owner)
    assert token_mode.get(path, headers=acting).json()["status"] == "disabled"
    unknown = token_mode.get(MEMBERSHIP.format(user_id=uuid4()), headers=acting)
    assert (unknown.status_code, unknown.json()["type"].rsplit(":", 1)[-1]) == (
        404,
        "identity-user-not-found",
    )


def test_a_membership_stays_inside_its_tenant(token_mode: TestClient) -> None:
    created = signed_up(token_mode)
    other = token_mode.post(
        "/v1/identity/tenants",
        json={
            "kind": "business",
            "name": "Other Traders",
            "provider_token": provider_token(token_mode, STAFF_PHONE),
        },
    ).json()
    acting = service_bearer(token_mode, "obligation")
    path = MEMBERSHIP.format(user_id=created["user"]["id"])
    theirs = token_mode.get(path, headers={**acting, "x-tenant-id": other["tenant"]["id"]})
    assert theirs.status_code == 404
    assert theirs.json()["type"].endswith(":identity-user-not-found")
    nowhere = token_mode.get(path, headers={**acting, "x-tenant-id": str(uuid4())})
    assert nowhere.json()["type"].endswith(":identity-tenant-not-found")


def test_a_membership_is_read_by_a_service_with_tenant_act_only(token_mode: TestClient) -> None:
    created = signed_up(token_mode)
    tenant = {"x-tenant-id": created["tenant"]["id"]}
    path = MEMBERSHIP.format(user_id=created["user"]["id"])
    owner = token_mode.get(path, headers=bearer(created["session"]["access_token"]))
    assert (owner.status_code, owner.json()["type"].rsplit(":", 1)[-1]) == (403, "auth-forbidden")
    without_scope = token_mode.get(
        path, headers={**service_bearer(token_mode, "notification"), **tenant}
    )
    assert without_scope.status_code == 403
    no_tenant = token_mode.get(path, headers=service_bearer(token_mode, "obligation"))
    assert no_tenant.json()["type"].endswith(":identity-tenant-required")
    anonymous = token_mode.get(path, headers=tenant)
    assert anonymous.json()["type"].endswith(":auth-token-required")


def test_a_membership_without_a_token_in_header_and_dual_mode() -> None:
    with TestClient(build_app(identity_settings())) as client:
        created = signed_up(client)
        path = MEMBERSHIP.format(user_id=created["user"]["id"])
        read = client.get(path, headers={"x-tenant-id": created["tenant"]["id"]})
        assert (read.status_code, read.json()["roles"]) == (200, ["owner"])
    with TestClient(build_app(identity_settings(auth_mode="dual"))) as client:
        created = signed_up(client)
        path = MEMBERSHIP.format(user_id=created["user"]["id"])
        anonymous = client.get(path, headers={"x-tenant-id": created["tenant"]["id"]})
        assert anonymous.status_code == 401
        assert anonymous.json()["type"].endswith(":auth-token-required")
