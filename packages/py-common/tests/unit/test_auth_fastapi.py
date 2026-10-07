from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

import httpx2
import pytest
import structlog
from fastapi import APIRouter, Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.requests import Request

from domain_kernel.access import (
    ANONYMOUS,
    REGULATORY_ROLES,
    TENANT_ADMIN_ROLES,
    TENANT_MEMBER_ROLES,
    Principal,
    Role,
    Scope,
)
from domain_kernel.errors import PROBLEM_TYPE_PREFIX, DomainError
from domain_kernel.ids import TenantId
from py_common.app import create_app
from py_common.auth.context import current_principal, principal_bound, principal_or_anonymous
from py_common.auth.fastapi import (
    Authenticated,
    Authenticator,
    CurrentPrincipal,
    authenticate,
    authenticator_of,
    data_export_scope,
    require_roles,
    shared_token_or_roles,
    tenant_scope,
)
from py_common.auth.testing import TestIssuer, bearer
from py_common.auth.tokens import JwksUrlSource, TokenVerifier
from py_common.settings import AuthMode, Settings

_TENANT = TenantId(UUID("55555555-5555-4555-8555-555555555555"))
_OTHER = TenantId(UUID("66666666-6666-4666-8666-666666666666"))
_SHARED = "shared-" + "s" * 24
"""The value of the demo shared secret in these tests."""
_ADMIN_TOKEN_HEADER = "x-cw-demo-admin-token"


class DemoTenantRequiredError(DomainError):
    type_slug = "demo-tenant-required"
    title = "Tenant required for the auth demo"


class DemoAdminDisabledError(DomainError):
    type_slug = "demo-admin-disabled"
    title = "Auth demo admin token is not configured"


class DemoAdminTokenInvalidError(DomainError):
    type_slug = "demo-admin-token-invalid"
    title = "Auth demo admin token missing or wrong"


class DemoSettings(Settings):
    demo_admin_token: SecretStr | None = None


Tenant = Annotated[TenantId, Depends(tenant_scope(True, DemoTenantRequiredError))]
MaybeTenant = Annotated[TenantId | None, Depends(tenant_scope(False))]
Members = Annotated[
    Principal, Depends(require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT}))
]
Admins = Annotated[Principal, Depends(require_roles(*TENANT_ADMIN_ROLES))]
ExportTenant = Annotated[TenantId, Depends(data_export_scope("demo", DemoTenantRequiredError))]
AdminAccess = Annotated[
    Principal,
    Depends(
        shared_token_or_roles(
            "demo_admin_token",
            _ADMIN_TOKEN_HEADER,
            REGULATORY_ROLES,
            [Scope.RULEBOOK_WRITE],
            disabled_error=DemoAdminDisabledError,
            invalid_error=DemoAdminTokenInvalidError,
        )
    ),
]


def _context() -> dict[str, Any]:
    fields = structlog.contextvars.get_contextvars()
    return {key: fields.get(key) for key in ("actor", "tenant_id")}


def _router() -> APIRouter:
    router = APIRouter(prefix="/v1/demo")

    @router.get("/whoami")
    def whoami(principal: CurrentPrincipal) -> dict[str, Any]:
        bound = current_principal.get()
        return {
            "actor": principal.actor_label,
            "bound": None if bound is None else bound.actor_label,
            "context": _context(),
        }

    @router.get("/tenant")
    def tenant(tenant_id: Tenant) -> dict[str, Any]:
        return {"tenant": str(tenant_id), "context": _context()}

    @router.get("/maybe-tenant")
    async def maybe_tenant(tenant_id: MaybeTenant) -> dict[str, Any]:
        return {"tenant": None if tenant_id is None else str(tenant_id)}

    @router.get("/members")
    def members(principal: Members, tenant_id: Tenant) -> dict[str, str]:
        return {"actor": principal.actor_label, "tenant": str(tenant_id)}

    @router.get("/data-export")
    def data_export(tenant_id: ExportTenant) -> dict[str, str]:
        return {"tenant": str(tenant_id)}

    @router.get("/admins")
    def admins(principal: Admins) -> dict[str, str]:
        return {"actor": principal.actor_label}

    @router.get("/me")
    def me(principal: Authenticated) -> dict[str, str]:
        return {"actor": principal.actor_label}

    @router.post("/admin-write")
    def admin_write(principal: AdminAccess) -> dict[str, str]:
        return {"actor": principal.actor_label}

    return router


@pytest.fixture(scope="module")
def issuer() -> TestIssuer:
    return TestIssuer()


def _client(
    issuer: TestIssuer,
    mode: AuthMode,
    *,
    shared: str | None = _SHARED,
    authenticator: Authenticator | None = None,
) -> TestClient:
    settings = DemoSettings(
        _env_file=None,
        service_name="demo",
        demo_admin_token=None if shared is None else SecretStr(shared),
        **issuer.settings_overrides(mode),
    )
    app = create_app(
        service_name="demo",
        version="0",
        routers=[_router()],
        settings=settings,
        problem_status={
            DemoTenantRequiredError: 400,
            DemoAdminDisabledError: 503,
            DemoAdminTokenInvalidError: 401,
        },
        authenticator=authenticator,
    )
    return TestClient(app)


@pytest.fixture
def header_client(issuer: TestIssuer) -> Iterator[TestClient]:
    with _client(issuer, "header") as client:
        yield client


@pytest.fixture
def dual_client(issuer: TestIssuer) -> Iterator[TestClient]:
    with _client(issuer, "dual") as client:
        yield client


@pytest.fixture
def token_client(issuer: TestIssuer) -> Iterator[TestClient]:
    with _client(issuer, "token") as client:
        yield client


def _problem(response: httpx2.Response, status: int, slug: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == PROBLEM_TYPE_PREFIX + slug


def _tenant_header(tenant: TenantId) -> dict[str, str]:
    return {"x-tenant-id": str(tenant)}


# ---------------------------------------------------------------- modes


def test_header_mode_ignores_bearer_tokens(header_client: TestClient, issuer: TestIssuer) -> None:
    assert header_client.get("/v1/demo/whoami").json()["actor"] == "anonymous"
    response = header_client.get("/v1/demo/whoami", headers=bearer("not even a token"))
    assert response.json()["actor"] == "anonymous"
    signed = bearer(issuer.user(_TENANT))
    assert header_client.get("/v1/demo/whoami", headers=signed).json()["actor"] == "anonymous"
    tenant = header_client.get("/v1/demo/tenant", headers=_tenant_header(_OTHER))
    assert tenant.json()["tenant"] == str(_OTHER)


def test_header_mode_still_needs_the_tenant_header(header_client: TestClient) -> None:
    _problem(header_client.get("/v1/demo/tenant"), 400, "demo-tenant-required")
    assert header_client.get("/v1/demo/maybe-tenant").json() == {"tenant": None}


def test_dual_mode_serves_requests_without_a_token_as_header_mode(
    dual_client: TestClient,
) -> None:
    assert dual_client.get("/v1/demo/whoami").json()["actor"] == "anonymous"
    response = dual_client.get("/v1/demo/tenant", headers=_tenant_header(_OTHER))
    assert response.json()["tenant"] == str(_OTHER)


def test_dual_mode_verifies_and_enforces_a_token_when_present(
    dual_client: TestClient, issuer: TestIssuer
) -> None:
    token = issuer.user(_TENANT, [Role.STAFF])
    response = dual_client.get("/v1/demo/tenant", headers=bearer(token))
    assert response.json()["tenant"] == str(_TENANT)
    bad = dual_client.get("/v1/demo/whoami", headers=bearer("junk"))
    _problem(bad, 401, "auth-token-invalid")
    assert bad.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    mismatch = dual_client.get(
        "/v1/demo/tenant", headers={**bearer(token), **_tenant_header(_OTHER)}
    )
    _problem(mismatch, 403, "auth-tenant-mismatch")


def test_token_mode_requires_a_bearer_token(token_client: TestClient) -> None:
    for path in ("/v1/demo/whoami", "/v1/demo/tenant", "/v1/demo/members"):
        response = token_client.get(path, headers=_tenant_header(_TENANT))
        _problem(response, 401, "auth-token-required")
        assert response.headers["www-authenticate"] == "Bearer"
    basic = token_client.get("/v1/demo/whoami", headers={"Authorization": "Basic dXNlcjpwdw=="})
    _problem(basic, 401, "auth-token-required")


def test_token_mode_refuses_tokens_of_another_issuer(token_client: TestClient) -> None:
    stranger = TestIssuer(kid="test-key")
    response = token_client.get("/v1/demo/whoami", headers=bearer(stranger.user(_TENANT)))
    _problem(response, 401, "auth-token-invalid")
    assert response.headers["www-authenticate"].startswith("Bearer")


# ---------------------------------------------------------------- tenants


def test_a_user_acts_for_the_tenant_its_token_names(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    token = bearer(issuer.user(_TENANT, [Role.OWNER]))
    assert token_client.get("/v1/demo/tenant", headers=token).json()["tenant"] == str(_TENANT)
    same = token_client.get("/v1/demo/tenant", headers={**token, **_tenant_header(_TENANT)})
    assert same.json()["tenant"] == str(_TENANT)
    other = token_client.get("/v1/demo/tenant", headers={**token, **_tenant_header(_OTHER)})
    _problem(other, 403, "auth-tenant-mismatch")


def test_a_service_acts_for_a_tenant_only_with_tenant_act(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    acting = bearer(issuer.service("qa", [Scope.TENANT_ACT, Scope.LLM_CALL]))
    response = token_client.get("/v1/demo/tenant", headers={**acting, **_tenant_header(_OTHER)})
    assert response.json()["tenant"] == str(_OTHER)
    _problem(token_client.get("/v1/demo/tenant", headers=acting), 400, "demo-tenant-required")
    assert token_client.get("/v1/demo/maybe-tenant", headers=acting).json() == {"tenant": None}
    plain = bearer(issuer.service("pipeline", [Scope.RULEBOOK_WRITE]))
    refused = token_client.get("/v1/demo/tenant", headers={**plain, **_tenant_header(_OTHER)})
    _problem(refused, 403, "auth-forbidden")
    assert "tenant:act" in refused.json()["detail"]


def test_a_bound_service_token_acts_for_its_tenant_only(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    bound = bearer(issuer.service("identity", [Scope.DATA_EXPORT], acts_for=_TENANT, audience="x"))
    alone = token_client.get("/v1/demo/tenant", headers=bound)
    assert alone.json()["tenant"] == str(_TENANT), "no tenant:act needed for its own tenant"
    same = token_client.get("/v1/demo/tenant", headers={**bound, **_tenant_header(_TENANT)})
    assert same.json()["tenant"] == str(_TENANT)
    other = token_client.get("/v1/demo/tenant", headers={**bound, **_tenant_header(_OTHER)})
    _problem(other, 403, "auth-tenant-mismatch")
    _problem(token_client.get("/v1/demo/members", headers=bound), 403, "auth-forbidden")


def test_a_data_export_answers_admins_and_a_token_bound_to_the_tenant_and_service(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    def export(token: str, tenant: TenantId) -> httpx2.Response:
        return token_client.get(
            "/v1/demo/data-export", headers={**bearer(token), **_tenant_header(tenant)}
        )

    owner = issuer.user(_TENANT, [Role.OWNER])
    assert export(owner, _TENANT).json() == {"tenant": str(_TENANT)}
    _problem(export(owner, _OTHER), 403, "auth-tenant-mismatch")
    _problem(export(issuer.user(_TENANT, [Role.STAFF]), _TENANT), 403, "auth-forbidden")

    bound = issuer.service("identity", [Scope.DATA_EXPORT], acts_for=_TENANT, audience="demo")
    assert export(bound, _TENANT).json() == {"tenant": str(_TENANT)}
    _problem(export(bound, _OTHER), 403, "auth-tenant-mismatch")
    elsewhere = issuer.service(
        "identity", [Scope.DATA_EXPORT], acts_for=_TENANT, audience="profile"
    )
    refused = export(elsewhere, _TENANT)
    _problem(refused, 403, "auth-forbidden")
    assert "not addressed to demo" in refused.json()["detail"]
    unbound = issuer.service("worker", [Scope.DATA_EXPORT, Scope.TENANT_ACT])
    refused = export(unbound, _TENANT)
    _problem(refused, 403, "auth-forbidden")
    assert "bound to the tenant" in refused.json()["detail"]
    scopeless = issuer.service("identity", [Scope.TENANT_ACT], acts_for=_TENANT, audience="demo")
    _problem(export(scopeless, _TENANT), 403, "auth-forbidden")


def test_a_data_export_in_header_mode_reads_the_header(header_client: TestClient) -> None:
    response = header_client.get("/v1/demo/data-export", headers=_tenant_header(_OTHER))
    assert response.json() == {"tenant": str(_OTHER)}
    _problem(header_client.get("/v1/demo/data-export"), 400, "demo-tenant-required")


def test_a_malformed_tenant_header_is_a_validation_problem(header_client: TestClient) -> None:
    response = header_client.get("/v1/demo/maybe-tenant", headers={"x-tenant-id": "nope"})
    _problem(response, 422, "request-invalid")


# ---------------------------------------------------------------- roles


def test_require_roles_is_enforced_in_token_mode(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    owner = bearer(issuer.user(_TENANT, [Role.OWNER]))
    staff = bearer(issuer.user(_TENANT, [Role.STAFF]))
    analyst = bearer(issuer.user(_TENANT, [Role.ANALYST], mfa=True))
    assert token_client.get("/v1/demo/admins", headers=owner).status_code == 200
    denied = token_client.get("/v1/demo/admins", headers=staff)
    _problem(denied, 403, "auth-forbidden")
    assert denied.json()["detail"] == "this request needs one of: ca_admin, owner"
    assert token_client.get("/v1/demo/members", headers=staff).status_code == 200
    _problem(token_client.get("/v1/demo/members", headers=analyst), 403, "auth-forbidden")


def test_require_roles_accepts_a_service_with_one_of_the_scopes(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    acting = {**bearer(issuer.service("bot", [Scope.TENANT_ACT])), **_tenant_header(_TENANT)}
    response = token_client.get("/v1/demo/members", headers=acting)
    assert response.json() == {"actor": "service:bot", "tenant": str(_TENANT)}
    _problem(token_client.get("/v1/demo/admins", headers=acting), 403, "auth-forbidden")


def test_require_roles_is_a_no_op_for_the_anonymous_principal(
    header_client: TestClient, dual_client: TestClient
) -> None:
    for client in (header_client, dual_client):
        assert client.get("/v1/demo/admins").json() == {"actor": "anonymous"}
        members = client.get("/v1/demo/members", headers=_tenant_header(_TENANT))
        assert members.json() == {"actor": "anonymous", "tenant": str(_TENANT)}


def test_authenticated_routes_refuse_the_anonymous_principal(
    dual_client: TestClient, issuer: TestIssuer
) -> None:
    _problem(dual_client.get("/v1/demo/me"), 401, "auth-token-required")
    token = bearer(issuer.service("qa", [Scope.LLM_CALL]))
    assert dual_client.get("/v1/demo/me", headers=token).json() == {"actor": "service:qa"}


# ---------------------------------------------------------------- shared tokens


def test_header_mode_opens_shared_token_routes_with_the_secret_only(
    header_client: TestClient, issuer: TestIssuer
) -> None:
    path = "/v1/demo/admin-write"
    ok = header_client.post(path, headers={_ADMIN_TOKEN_HEADER: _SHARED})
    assert ok.json() == {"actor": "anonymous"}
    _problem(header_client.post(path), 401, "demo-admin-token-invalid")
    wrong = header_client.post(path, headers={_ADMIN_TOKEN_HEADER: _SHARED + "x"})
    _problem(wrong, 401, "demo-admin-token-invalid")
    analyst = bearer(issuer.user(_TENANT, [Role.ANALYST], mfa=True))
    _problem(header_client.post(path, headers=analyst), 401, "demo-admin-token-invalid")


def test_an_unset_shared_token_fails_closed_in_header_mode(issuer: TestIssuer) -> None:
    with _client(issuer, "header", shared=None) as client:
        response = client.post("/v1/demo/admin-write", headers={_ADMIN_TOKEN_HEADER: "anything"})
    _problem(response, 503, "demo-admin-disabled")


def test_dual_mode_takes_the_roles_or_the_shared_token(
    dual_client: TestClient, issuer: TestIssuer
) -> None:
    path = "/v1/demo/admin-write"
    reviewer = bearer(issuer.user(_TENANT, [Role.REVIEWER], mfa=True))
    assert dual_client.post(path, headers=reviewer).json()["actor"].startswith("user:")
    pipeline = bearer(issuer.service("pipeline", [Scope.RULEBOOK_WRITE]))
    assert dual_client.post(path, headers=pipeline).json() == {"actor": "service:pipeline"}
    assert dual_client.post(path, headers={_ADMIN_TOKEN_HEADER: _SHARED}).status_code == 200
    owner = {**bearer(issuer.user(_TENANT, [Role.OWNER])), _ADMIN_TOKEN_HEADER: _SHARED}
    _problem(dual_client.post(path, headers=owner), 403, "auth-forbidden")


def test_dual_mode_without_a_shared_token_asks_for_a_bearer(issuer: TestIssuer) -> None:
    with _client(issuer, "dual", shared=None) as client:
        response = client.post("/v1/demo/admin-write")
    _problem(response, 401, "auth-token-required")


def test_token_mode_never_accepts_the_shared_token(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    path = "/v1/demo/admin-write"
    response = token_client.post(path, headers={_ADMIN_TOKEN_HEADER: _SHARED})
    _problem(response, 401, "auth-token-required")
    admin = bearer(issuer.user(_TENANT, [Role.ADMIN], mfa=True))
    assert token_client.post(path, headers=admin).status_code == 200


# ---------------------------------------------------------------- context


def test_actor_and_tenant_are_bound_for_the_request(
    token_client: TestClient, issuer: TestIssuer
) -> None:
    token = issuer.user(_TENANT, [Role.OWNER])
    body = token_client.get("/v1/demo/whoami", headers=bearer(token)).json()
    assert body["actor"] == body["bound"]
    assert body["context"] == {"actor": body["actor"], "tenant_id": str(_TENANT)}
    service = bearer(issuer.service("qa", [Scope.TENANT_ACT]))
    acting = token_client.get("/v1/demo/tenant", headers={**service, **_tenant_header(_OTHER)})
    assert acting.json()["context"] == {"actor": "service:qa", "tenant_id": str(_OTHER)}


async def test_authenticate_binds_and_then_clears_the_context(issuer: TestIssuer) -> None:
    app = FastAPI()
    app.state.authenticator = Authenticator("token", issuer.verifier())
    request = Request({"type": "http", "app": app, "headers": []})
    token = issuer.user(_TENANT, [Role.STAFF])
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    structlog.contextvars.clear_contextvars()
    steps = authenticate(request, credentials)
    principal = await anext(steps)
    assert current_principal.get() == principal
    assert principal_or_anonymous() == principal
    assert _context() == {"actor": principal.actor_label, "tenant_id": str(_TENANT)}
    with pytest.raises(StopAsyncIteration):
        await anext(steps)
    assert current_principal.get() is None
    assert principal_or_anonymous() is ANONYMOUS
    assert _context() == {"actor": None, "tenant_id": None}


def test_principal_bound_restores_the_context() -> None:
    structlog.contextvars.clear_contextvars()
    service = Principal.service("relay", [Scope.TENANT_ACT])
    with principal_bound(service):
        assert _context() == {"actor": "service:relay", "tenant_id": None}
    assert _context() == {"actor": None, "tenant_id": None}
    assert current_principal.get() is None


# ---------------------------------------------------------------- construction and spec


def test_the_authenticator_needs_a_verifier_outside_header_mode(issuer: TestIssuer) -> None:
    with pytest.raises(ValueError, match="needs a token verifier"):
        Authenticator("token")
    with pytest.raises(ValueError, match="auth mode must be one of"):
        Authenticator("off")  # type: ignore[arg-type]
    assert not Authenticator("token", issuer.verifier()).accepts_shared_tokens
    assert Authenticator("dual", issuer.verifier()).accepts_shared_tokens
    header = Authenticator.from_settings(Settings(_env_file=None))
    assert (header.mode, header.verifier) == ("header", None)
    assert header.principal_for("anything") is ANONYMOUS


def test_an_app_without_an_authenticator_is_a_programming_error() -> None:
    request = Request({"type": "http", "app": FastAPI(), "headers": []})
    with pytest.raises(RuntimeError, match="create_app"):
        authenticator_of(request)


def test_factories_refuse_nonsense() -> None:
    with pytest.raises(ValueError, match="missing-tenant error"):
        tenant_scope(True, None)  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="at least one role or scope"):
        require_roles()
    with pytest.raises(ValueError, match="at least one role or scope"):
        shared_token_or_roles(
            "demo_admin_token",
            _ADMIN_TOKEN_HEADER,
            disabled_error=DemoAdminDisabledError,
            invalid_error=DemoAdminTokenInvalidError,
        )
    with pytest.raises(ValueError, match="settings field"):
        shared_token_or_roles(
            "CW-DEMO",
            _ADMIN_TOKEN_HEADER,
            [Role.ADMIN],
            disabled_error=DemoAdminDisabledError,
            invalid_error=DemoAdminTokenInvalidError,
        )


def test_unavailable_keys_are_a_503(issuer: TestIssuer) -> None:
    def down(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("identity is down")

    source = JwksUrlSource(
        "http://identity.test/jwks.json", client=httpx2.Client(transport=httpx2.MockTransport(down))
    )
    verifier = TokenVerifier(source, issuer=issuer.issuer_name, audience=issuer.audience)
    with _client(issuer, "token", authenticator=Authenticator("token", verifier)) as client:
        response = client.get("/v1/demo/whoami", headers=bearer(issuer.user(_TENANT)))
    _problem(response, 503, "auth-keys-unavailable")


def test_the_spec_declares_the_bearer_scheme_and_the_headers(token_client: TestClient) -> None:
    spec = token_client.get("/openapi.json").json()
    schemes = spec["components"]["securitySchemes"]
    assert schemes["HTTPBearer"]["scheme"] == "bearer"
    operation = spec["paths"]["/v1/demo/admin-write"]["post"]
    assert operation["security"] == [{"HTTPBearer": []}]
    headers = {param["name"] for param in operation["parameters"] if param["in"] == "header"}
    assert headers == {_ADMIN_TOKEN_HEADER}
    tenant = spec["paths"]["/v1/demo/tenant"]["get"]["parameters"]
    assert [(param["name"], param["required"]) for param in tenant] == [("x-tenant-id", False)]
