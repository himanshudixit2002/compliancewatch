"""GET /v1/ontology: the attributes with their wording, the operators per type, and the ETag."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ontology as ontology_package
from domain_kernel.ontology import (
    ALLOWED_OPERATORS,
    AttributeType,
    Ontology,
    OntologyWording,
    WordingReviewStatus,
)
from profile_service.api.ontology import OntologyOut
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import FixedFlags

ONTOLOGY = "/v1/ontology"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    settings = ProfileSettings(_env_file=None, service_name="profile", profile_store="memory")
    with TestClient(build_app(settings, flags=FixedFlags())) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def body(client: TestClient) -> dict[str, Any]:
    response = client.get(ONTOLOGY)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_the_ontology_is_global_data_with_its_versions(
    client: TestClient, body: dict[str, Any]
) -> None:
    assert client.get(ONTOLOGY, headers={"x-tenant-id": "not checked"}).status_code == 200
    assert body["version"] == ontology_package.VERSION
    assert body["wording_version"] == ontology_package.WORDING_VERSION
    assert (body["language"], body["review_status"]) == ("en", "needs_review")


def test_the_operators_are_the_kernel_s_per_type(body: dict[str, Any]) -> None:
    operators = body["operators_by_type"]
    assert set(operators) == {kind.value for kind in AttributeType}
    assert operators["enum"] == ["eq", "neq", "in", "not_in"]
    assert operators["enum_set"] == ["contains", "contains_any"]
    assert operators["boolean"] == ["eq", "neq"]
    for kind, allowed in ALLOWED_OPERATORS.items():
        assert set(operators[kind.value]) == {operator.value for operator in allowed}


def test_every_attribute_carries_its_question_and_labelled_values(body: dict[str, Any]) -> None:
    ontology = ontology_package.load()
    attributes = {item["key"]: item for item in body["attributes"]}
    assert [item["key"] for item in body["attributes"]] == [d.key for d in ontology]
    assert all(item["question"].endswith("?") for item in body["attributes"])
    states = attributes["state_codes"]
    assert (states["type"], states["level"], states["source"]) == (
        "enum_set",
        "entity",
        "gstin_lookup",
    )
    assert {"value": "29", "label": "Karnataka"} in states["values"]
    assert states["example"] == ["29"]
    assert attributes["turnover_band"]["per_financial_year"] is True
    assert attributes["registered_since"]["example"] == "2019-07-01"
    assert attributes["registered_since"]["values"] == []
    employees = attributes["employee_count"]
    assert (employees["min"], employees["max"], employees["example"]) == (0, 100000, 12)
    assert attributes["constitution"]["definition"] == ontology.require("constitution").definition


def test_the_etag_lets_a_client_revalidate(client: TestClient) -> None:
    first = client.get(ONTOLOGY)
    etag = first.headers["etag"]
    assert etag.startswith('"')
    assert etag.endswith('"')
    assert first.headers["cache-control"] == "max-age=3600"
    assert client.get(ONTOLOGY).headers["etag"] == etag, "the same ontology, the same tag"
    for sent in (etag, f"W/{etag}", f'"stale", {etag}', "*"):
        revalidated = client.get(ONTOLOGY, headers={"If-None-Match": sent})
        assert revalidated.status_code == 304, sent
        assert revalidated.content == b""
        assert revalidated.headers["etag"] == etag
    changed = client.get(ONTOLOGY, headers={"If-None-Match": '"stale"'})
    assert changed.status_code == 200
    assert changed.json()["version"] == ontology_package.VERSION


def test_the_route_is_public_and_lists_its_roles(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][ONTOLOGY]["get"]
    assert operation["tags"] == ["public", "ontology"]
    assert operation["x-roles"] == ["owner", "staff", "ca_admin", "ca_staff", "compliance_lead"]
    assert {"200", "304"} <= set(operation["responses"])


def test_decimal_bounds_and_an_unworded_attribute() -> None:
    ontology = Ontology.from_mapping(
        {
            "version": "1.0.0",
            "attributes": [
                {
                    "key": "margin",
                    "type": "decimal",
                    "source": "derived",
                    "definition": "A made-up computed ratio.",
                    "min": Decimal("0.5"),
                    "max": Decimal("99.5"),
                    "example": Decimal("1.25"),
                }
            ],
        }
    )
    wording = OntologyWording(
        version="1.0.0",
        language="en",
        review_status=WordingReviewStatus.NEEDS_REVIEW,
        attributes=(),
    )
    [margin] = OntologyOut.of(ontology, wording).attributes
    assert (margin.min, margin.max, margin.example) == (0.5, 99.5, "1.25")
    assert (margin.question, margin.help, margin.values) == ("", "", [])
