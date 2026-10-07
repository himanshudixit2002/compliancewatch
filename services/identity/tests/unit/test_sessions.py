"""Sign-up, the session exchange and service tokens, with the fake provider and the memory store."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from domain_kernel.access import ANONYMOUS, Principal, Role, Scope
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import UserId
from identity.application.bootstrap import (
    CreateServiceClient,
    EnsureDevServiceClients,
    ListServiceClients,
    RevokeServiceClient,
)
from identity.application.sessions import (
    ExchangeSession,
    IssueServiceToken,
    check_session,
    user_principal,
)
from identity.application.tenancy import CreateTenant, CurrentUser
from identity.domain.errors import (
    MfaRequiredError,
    ProviderUnavailableError,
    ServiceClientExistsError,
    ServiceClientInvalidError,
    ServiceClientNotFoundError,
    SessionRevokedError,
    SubjectRegisteredError,
    TenantDeletingError,
    TenantInactiveError,
    UserDisabledError,
    UserNotProvisionedError,
)
from identity.domain.events import RoleChangeReason, TenantCreated, UserRoleChanged
from identity.domain.provider import AAL2, ProviderIdentity
from identity.domain.service_clients import ServiceClient, secret_digest
from identity.domain.sessions import AccessToken
from identity.domain.tenancy import Contact, Tenant, TenantKind, TenantStatus, User
from identity.infrastructure.memory import MemoryStore
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from py_common.auth import TokenIssuer
from py_common.auth.testing import TestIssuer

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
TTL = timedelta(minutes=10)
PHONE = "+919876543210"
OTHER_PHONE = "+919812345678"
SECRET = "s" * 40
"""A dev client secret: long enough, not random, never a real one."""


class World:
    """A store, the fake provider and the use cases over them."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.provider = FakeIdentityProvider()
        self.issuer = TestIssuer()
        self.minter = IssuerMinter(
            TokenIssuer(
                self.issuer.keys, issuer=self.issuer.issuer_name, audience=self.issuer.audience
            )
        )
        self.create = CreateTenant(
            self.store, self.provider, self.minter, ttl=TTL, clock=lambda: NOW
        )
        self.exchange = ExchangeSession(self.store, self.provider, self.minter, ttl=TTL)
        self.service_tokens = IssueServiceToken(self.store, self.minter, ttl=TTL)

    def token(self, phone: str = PHONE, aal: str = "aal1") -> str:
        return self.provider.issue(phone=phone, aal=aal)


@pytest.fixture
def world() -> World:
    return World()


# ---------------------------------------------------------------- sign-up


def test_sign_up_creates_the_tenant_its_first_admin_and_a_session(world: World) -> None:
    created = world.create.run(world.token(), TenantKind.BUSINESS, " Acme Traders ")
    tenant, user = created.tenant, created.user
    assert (tenant.kind, tenant.name, tenant.region) == (TenantKind.BUSINESS, "Acme Traders", "in")
    assert user.roles == {Role.OWNER}
    assert (user.contact.phone, user.provider) == (PHONE, "fake")
    principal = world.issuer.verifier().verify(created.session.token.token)
    assert principal == user_principal(user, mfa=False)
    assert principal.tenant_id == tenant.id
    created_event, role_event = world.store.events
    assert isinstance(created_event, TenantCreated)
    assert (created_event.tenant_id, created_event.created_by) == (tenant.id, user.id)
    assert isinstance(role_event, UserRoleChanged)
    assert (role_event.reason, role_event.roles, role_event.changed_by) == (
        RoleChangeReason.CREATED,
        (Role.OWNER,),
        user.id,
    )
    with pytest.raises(SubjectRegisteredError):
        world.create.run(world.token(), TenantKind.BUSINESS, "Second Business")
    assert len(world.store.tenants) == 1


def test_a_ca_firm_sign_up_needs_a_second_factor(world: World) -> None:
    with pytest.raises(MfaRequiredError):
        world.create.run(world.token(), TenantKind.CA_FIRM, "Mehta and Co")
    assert world.store.tenants == {}
    created = world.create.run(world.token(aal=AAL2), TenantKind.CA_FIRM, "Mehta and Co")
    assert created.user.roles == {Role.CA_ADMIN}
    assert created.session.principal.mfa


def test_sign_up_never_creates_the_internal_tenant(world: World) -> None:
    with pytest.raises(InvariantViolationError, match="operator"):
        world.create.run(world.token(aal=AAL2), TenantKind.INTERNAL, "Regulatory team")


# ---------------------------------------------------------------- the exchange


def test_a_signed_up_person_exchanges_a_provider_token_for_a_session(world: World) -> None:
    created = world.create.run(world.token(), TenantKind.BUSINESS, "Acme Traders")
    session = world.exchange.run(world.token())
    assert (session.tenant, session.user) == (created.tenant, created.user)
    assert session.token.expires_in == int(TTL.total_seconds())
    principal = world.issuer.verifier().verify(session.token.token)
    assert principal.roles == {Role.OWNER}
    assert principal.session_version == 0


def test_an_unknown_subject_is_not_provisioned(world: World) -> None:
    with pytest.raises(UserNotProvisionedError, match="POST /v1/identity/tenants"):
        world.exchange.run(world.token(OTHER_PHONE))


def test_a_disabled_user_cannot_sign_in(world: World) -> None:
    created = world.create.run(world.token(), TenantKind.BUSINESS, "Acme Traders")
    second = User.new(
        created.tenant,
        provider="fake",
        provider_subject="second-owner",
        contact=Contact(phone=OTHER_PHONE),
        roles=[Role.OWNER],
        at=NOW,
    )
    disabled = created.user.disabled(created.tenant, colleagues=[second], at=NOW)
    with world.store(created.tenant.id) as uow:
        uow.users.add(second)
        uow.users.save(disabled)
    with pytest.raises(UserDisabledError):
        world.exchange.run(world.token())


def test_a_ca_admin_without_a_second_factor_is_sent_to_enrol(world: World) -> None:
    world.create.run(world.token(aal=AAL2), TenantKind.CA_FIRM, "Mehta and Co")
    with pytest.raises(MfaRequiredError, match="aal2"):
        world.exchange.run(world.token())
    assert world.exchange.run(world.token(aal=AAL2)).principal.mfa


def test_a_tenant_that_asked_for_deletion_signs_nobody_in(world: World) -> None:
    created = world.create.run(world.token(), TenantKind.BUSINESS, "Acme Traders")
    closing = Tenant(
        created.tenant.id,
        created.tenant.kind,
        created.tenant.name,
        created.tenant.created_at,
        status=TenantStatus.DELETION_REQUESTED,
    )
    world.store.tenants[closing.id] = closing
    with pytest.raises(TenantDeletingError):
        world.exchange.run(world.token())
    with pytest.raises(TenantDeletingError):
        CurrentUser(world.store).run(created.session.principal)


def test_unreachable_provider_keys_fail_sign_in_closed(world: World) -> None:
    class Unreachable(FakeIdentityProvider):
        def verify(self, token: str) -> ProviderIdentity:
            raise ProviderUnavailableError("keys could not be fetched")

    exchange = ExchangeSession(world.store, Unreachable(), world.minter, ttl=TTL)
    with pytest.raises(ProviderUnavailableError):
        exchange.run("any")


def test_an_index_entry_without_its_user_is_not_provisioned(world: World) -> None:
    created = world.create.run(world.token(), TenantKind.BUSINESS, "Acme Traders")
    del world.store.users[created.user.id]
    with pytest.raises(UserNotProvisionedError):
        world.exchange.run(world.token())


# ---------------------------------------------------------------- the current session


def test_check_session_refuses_an_older_session_version(world: World) -> None:
    created = world.create.run(world.token(), TenantKind.BUSINESS, "Acme Traders")
    principal = created.session.principal
    current = CurrentUser(world.store)
    assert current.run(principal) == (created.tenant, created.user)
    promoted = created.user.with_roles(
        [Role.OWNER, Role.COMPLIANCE_LEAD], created.tenant, colleagues=[], at=NOW
    )
    with world.store(created.tenant.id) as uow:
        uow.users.save(promoted)
    with pytest.raises(SessionRevokedError):
        current.run(principal)
    assert current.run(user_principal(promoted, mfa=False))[1] == promoted
    stranger = Principal.user(UserId.new(), created.tenant.id, [Role.OWNER])
    for refused in (stranger, Principal.service("qa", [Scope.LLM_CALL]), ANONYMOUS):
        with pytest.raises(SessionRevokedError), world.store(created.tenant.id) as uow:
            check_session(uow, refused)


def test_check_session_refuses_an_inactive_tenant(world: World) -> None:
    created = world.create.run(world.token(), TenantKind.BUSINESS, "Acme Traders")
    tenant = created.tenant
    world.store.tenants[tenant.id] = tenant.deletion_requested().erased()
    with pytest.raises(TenantInactiveError):
        CurrentUser(world.store).run(created.session.principal)


# ---------------------------------------------------------------- service tokens


def test_a_service_client_gets_a_token_with_its_scopes(world: World) -> None:
    client, secret = CreateServiceClient(world.store, clock=lambda: NOW).run(
        "pipeline", frozenset({Scope.RULEBOOK_WRITE, Scope.LLM_CALL})
    )
    assert client.secret_sha256 == secret_digest(secret)
    assert secret not in repr(world.store.service_clients)
    issued = world.service_tokens.run("pipeline", secret)
    principal = world.issuer.verifier().verify(issued.token.token)
    assert principal.subject == "pipeline"
    assert principal.scopes == {Scope.RULEBOOK_WRITE, Scope.LLM_CALL}
    with pytest.raises(ServiceClientExistsError):
        CreateServiceClient(world.store).run("pipeline", frozenset())


@pytest.mark.parametrize(("client_id", "secret"), [("pipeline", "wrong"), ("nobody", SECRET)])
def test_a_wrong_secret_or_an_unknown_client_gets_no_token(
    world: World, client_id: str, secret: str
) -> None:
    CreateServiceClient(world.store).run("pipeline", frozenset({Scope.LLM_CALL}))
    with pytest.raises(ServiceClientInvalidError):
        world.service_tokens.run(client_id, secret)


def test_a_revoked_client_gets_no_token(world: World) -> None:
    _, secret = CreateServiceClient(world.store).run("qa", frozenset({Scope.LLM_CALL}))
    revoke = RevokeServiceClient(world.store, clock=lambda: NOW)
    revoked = revoke.run("qa")
    assert revoked.revoked_at == NOW
    assert revoke.run("qa") == revoked
    with pytest.raises(ServiceClientInvalidError):
        world.service_tokens.run("qa", secret)
    with pytest.raises(ServiceClientNotFoundError):
        revoke.run("nobody")
    assert [client.client_id for client in ListServiceClients(world.store).run()] == ["qa"]


def test_dev_clients_are_created_updated_and_reactivated(world: World) -> None:
    ensure = EnsureDevServiceClients(world.store, clock=lambda: NOW)
    clients = {
        "pipeline": frozenset({Scope.RULEBOOK_WRITE}),
        "qa": frozenset({Scope.LLM_CALL, Scope.TENANT_ACT}),
    }
    first = ensure.run(clients, SECRET)
    assert [client.client_id for client in first] == ["pipeline", "qa"]
    assert world.service_tokens.run("qa", SECRET).principal.scopes == clients["qa"]
    RevokeServiceClient(world.store).run("qa")
    later = EnsureDevServiceClients(world.store, clock=lambda: NOW + timedelta(days=1))
    again = later.run({**clients, "pipeline": frozenset({Scope.LLM_CALL})}, SECRET + "x")
    assert again[0].scopes == {Scope.LLM_CALL}
    assert again[0].created_at == NOW
    assert again[1].is_active
    assert later.run({**clients, "pipeline": frozenset({Scope.LLM_CALL})}, SECRET + "x") == again
    with pytest.raises(ServiceClientInvalidError):
        world.service_tokens.run("qa", SECRET)


# ---------------------------------------------------------------- the minter and clients


def test_the_minter_bounds_the_token_lifetime(world: World) -> None:
    principal = Principal.service("qa", [Scope.LLM_CALL])
    token = world.minter.mint(principal, TTL)
    assert isinstance(token, AccessToken)
    for ttl in (timedelta(seconds=30), timedelta(hours=2)):
        with pytest.raises(ValueError, match="lives between"):
            world.minter.mint(principal, ttl)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"client_id": "Pipeline"}, "client id"),
        ({"client_id": "x" * 129}, "client id"),
        ({"secret_sha256": "abc"}, "hex"),
        ({"scopes": frozenset({"llm:call"})}, "Scope"),
        ({"revoked_at": datetime(2026, 10, 1)}, "timezone"),
    ],
)
def test_service_client_invariants(values: dict[str, Any], message: str) -> None:
    fields: dict[str, Any] = {
        "client_id": "qa",
        "secret_sha256": secret_digest(SECRET),
        "scopes": frozenset({Scope.LLM_CALL}),
        "created_at": NOW,
    }
    fields.update(values)
    with pytest.raises(InvariantViolationError, match=message):
        ServiceClient(**fields)
    with pytest.raises(InvariantViolationError, match="at least"):
        ServiceClient.with_secret("qa", frozenset(), "short", at=NOW)
