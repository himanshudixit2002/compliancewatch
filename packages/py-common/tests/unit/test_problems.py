from collections.abc import Iterator, Mapping
from typing import ClassVar

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from domain_kernel.errors import DomainError, InvariantViolationError, UnknownAttributeError
from py_common.app import create_app
from py_common.problems import PROBLEM_MEDIA_TYPE, problem_responses

PREFIX = "urn:compliancewatch:problem:"


class RateLimitedError(DomainError):
    type_slug = "rate-limited"
    title = "Rate limited"
    problem_headers: ClassVar[Mapping[str, str]] = {"Retry-After": "30"}


class TenantRateLimitedError(RateLimitedError):
    # The kernel test suite requires a unique title per DomainError subclass in the session.
    type_slug = "rate-limited-tenant"
    title = "Tenant rate limited"


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

    return create_app(
        service_name="t", version="0", routers=[router], problem_status={RateLimitedError: 429}
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
