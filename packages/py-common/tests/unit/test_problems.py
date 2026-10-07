from collections.abc import Iterator, Mapping
from typing import Annotated, ClassVar

import pytest
from fastapi import APIRouter, FastAPI, Header
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from domain_kernel.errors import DomainError, InvariantViolationError, UnknownAttributeError
from py_common.app import create_app
from py_common.problems import (
    PROBLEM_MEDIA_TYPE,
    limit_problem_responses,
    problem_response,
    problem_responses,
)
from py_common.request_context import REQUEST_ID_HEADER, RequestContextMiddleware

PREFIX = "urn:compliancewatch:problem:"


class RateLimitedError(DomainError):
    type_slug = "rate-limited"
    title = "Rate limited"
    problem_headers: ClassVar[Mapping[str, str]] = {"Retry-After": "30"}


class TenantRateLimitedError(RateLimitedError):
    # The kernel test suite requires a unique title per DomainError subclass in the session.
    type_slug = "rate-limited-tenant"
    title = "Tenant rate limited"


class QuotaReachedError(DomainError):
    type_slug = "quota-reached"
    title = "Quota reached"
    problem_extensions: ClassVar[Mapping[str, object]] = {"limit": 3, "used": 3, "status": 200}


class UnmappedError(DomainError):
    type_slug = "unmapped"
    title = "Unmapped"


class Thing(BaseModel):
    name: str


def _app() -> FastAPI:
    router = APIRouter(prefix="/t")

    @router.get("/mapped")
    async def mapped() -> None:
        raise TenantRateLimitedError("slow down")

    @router.get("/quota", responses=limit_problem_responses())
    async def quota() -> None:
        raise QuotaReachedError()

    @router.get("/unmapped")
    async def unmapped() -> None:
        raise UnmappedError()

    @router.get("/invariant")
    async def invariant() -> None:
        raise InvariantViolationError("bad value")

    @router.get("/unknown-attribute")
    async def unknown_attribute() -> None:
        raise UnknownAttributeError("turnover")

    @router.get("/items/{item_id}", responses=problem_responses(422))
    async def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @router.post("/things")
    async def things(thing: Thing, limit: int = 1) -> Thing:
        return thing

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    @router.get("/signed")
    async def signed(signature: Annotated[str, Header(alias="x-signature")]) -> str:
        return signature

    return create_app(
        service_name="t",
        version="0",
        routers=[router],
        problem_status={RateLimitedError: 429, QuotaReachedError: 402},
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def test_mapped_error_uses_the_most_specific_status_and_the_error_type(client: TestClient) -> None:
    response = client.get("/t/mapped", headers={"x-request-id": "req-1"})
    assert response.status_code == 429
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.headers["retry-after"] == "30"
    assert response.headers["x-request-id"] == "req-1"
    assert response.json() == {
        "type": PREFIX + "rate-limited-tenant",
        "title": "Tenant rate limited",
        "status": 429,
        "detail": "slow down",
        "instance": "/t/mapped",
        "correlation_id": "req-1",
    }


def test_an_error_adds_its_extension_members_but_never_replaces_one(client: TestClient) -> None:
    response = client.get("/t/quota")
    assert response.status_code == 402
    body = response.json()
    assert (body["type"], body["status"]) == (PREFIX + "quota-reached", 402)
    assert (body["limit"], body["used"]) == (3, 3)


def test_unmapped_domain_error_is_400(client: TestClient) -> None:
    response = client.get("/t/unmapped")
    assert response.status_code == 400
    assert response.json()["type"] == PREFIX + "unmapped"


@pytest.mark.parametrize(("path", "status"), [("/t/invariant", 422), ("/t/unknown-attribute", 404)])
def test_kernel_defaults_apply(client: TestClient, path: str, status: int) -> None:
    response = client.get(path)
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)


def test_validation_error_is_422_with_issues(client: TestClient) -> None:
    response = client.get("/t/items/abc")
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == PREFIX + "request-invalid"
    assert problem["errors"][0]["loc"] == ["path", "item_id"]
    assert "input" not in problem["errors"][0]


def test_a_missing_header_without_its_own_problem_is_request_invalid(client: TestClient) -> None:
    response = client.get("/t/signed")
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == PREFIX + "request-invalid"
    assert problem["errors"][0]["loc"] == ["header", "x-signature"]


def test_unhandled_exception_is_500_without_internals(client: TestClient) -> None:
    response = client.get("/t/boom", headers={"x-request-id": "req-500"})
    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.headers["x-request-id"] == "req-500"
    problem = response.json()
    assert problem["type"] == PREFIX + "internal-error"
    assert problem["correlation_id"] == "req-500"
    assert "secret" not in response.text


def test_unknown_route_is_a_404_problem(client: TestClient) -> None:
    response = client.get("/nowhere")
    assert response.status_code == 404
    assert response.json()["type"] == "about:blank"
    assert response.json()["title"] == "Not Found"


def test_openapi_publishes_the_problem_schema() -> None:
    spec = _app().openapi()
    assert "Problem" in spec["components"]["schemas"]
    assert "ValidationIssue" in spec["components"]["schemas"]
    content = spec["paths"]["/t/items/{item_id}"]["get"]["responses"]["422"]["content"]
    assert list(content) == [PROBLEM_MEDIA_TYPE]


def test_openapi_publishes_the_limit_problem_only_where_a_route_answers_it() -> None:
    spec = _app().openapi()
    limited = spec["components"]["schemas"]["LimitProblem"]
    assert {"limit", "used", "type", "title", "status"} <= set(limited["required"])
    content = spec["paths"]["/t/quota"]["get"]["responses"]["402"]["content"]
    assert content[PROBLEM_MEDIA_TYPE]["schema"]["$ref"].endswith("/LimitProblem")
    bare = create_app(service_name="p", version="0", routers=[APIRouter()])
    assert "LimitProblem" not in bare.openapi()["components"]["schemas"]


def test_openapi_documents_problems_for_undecodable_bodies_and_validation() -> None:
    app = _app()
    spec = app.openapi()
    create = spec["paths"]["/t/things"]["post"]["responses"]
    assert list(create["400"]["content"]) == [PROBLEM_MEDIA_TYPE]
    assert list(create["422"]["content"]) == [PROBLEM_MEDIA_TYPE]
    assert "400" not in spec["paths"]["/t/items/{item_id}"]["get"]["responses"]
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    assert "ValidationError" not in spec["components"]["schemas"]
    assert app.openapi() == spec


def test_undecodable_body_is_a_400_problem(client: TestClient) -> None:
    headers = {"content-type": "application/json"}
    response = client.post("/t/things", content=b'{"name": "\xff"}', headers=headers)
    assert response.status_code == 400
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)


def test_problem_response_answers_from_plain_asgi_code() -> None:
    async def not_here(scope: Scope, receive: Receive, send: Send) -> None:
        response = problem_response(
            Request(scope),
            status=404,
            type_uri=PREFIX + "route-not-found",
            title="Route not found",
            detail="No route serves this path here",
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)

    client = TestClient(RequestContextMiddleware(not_here))  # no lifespan: an HTTP-only app
    response = client.get("/v1/elsewhere", headers={REQUEST_ID_HEADER: "req-7"})
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "type": PREFIX + "route-not-found",
        "title": "Route not found",
        "status": 404,
        "detail": "No route serves this path here",
        "instance": "/v1/elsewhere",
        "correlation_id": "req-7",
    }
