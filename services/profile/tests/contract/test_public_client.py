"""The generated public API models (``cw_contracts.rest.public_v1``) build requests this service
accepts and read every answer it gives, errors included."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from cw_contracts.rest import public_v1 as api
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_DELHI, GSTIN_KARNATAKA, TENANT, FixedFlags

BUSINESSES = "/v1/businesses"
AS_TENANT = {"x-tenant-id": str(TENANT)}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="memory",
        profile_gstin_lookup="static",
    )
    with TestClient(build_app(settings, flags=FixedFlags())) as test_client:
        yield test_client


def body(model: BaseModel) -> dict[str, Any]:
    """A request body as a client sends it: JSON values, unset optional fields left out."""
    return model.model_dump(mode="json", exclude_none=True)


def keyed() -> dict[str, str]:
    return {**AS_TENANT, "Idempotency-Key": f"key-{uuid4()}"}


def test_the_business_api_round_trips_through_the_generated_models(client: TestClient) -> None:
    request = api.BusinessIn(
        name="Acme",
        gstin=api.Gstin(GSTIN_KARNATAKA.value),
        answers=[api.AnswerIn(key="employee_count", value=12)],
    )
    response = client.post(BUSINESSES, json=body(request), headers=keyed())
    assert response.status_code == 201, response.text
    created = api.BusinessCreatedOut.model_validate(response.json())
    assert created.created
    assert created.prefill is not None
    assert created.prefill.result is not None
    assert created.prefill.result.state_code == "29"
    assert created.onboarding.next is not None
    business_id = created.business.id

    page = api.PageBusinessSummaryOut.model_validate(
        client.get(BUSINESSES, params={"limit": 1}, headers=AS_TENANT).json()
    )
    assert [item.id for item in page.items] == [business_id]

    path = f"{BUSINESSES}/{business_id}"
    read = api.BusinessOut.model_validate(client.get(path, headers=AS_TENANT).json())
    assert read == created.business

    patch = api.BusinessPatchIn(
        name=api.Name("Acme Traders"),
        changes=[
            api.BusinessChangeIn(
                key="turnover_band",
                value="2_crore_to_5_crore",
                as_of_fy=api.AsOfFy(created.onboarding.as_of_fy),
            ),
            api.BusinessChangeIn(key="supply_type", state=api.ValueState.unsure),
        ],
    )
    patched = client.patch(path, json=body(patch), headers=AS_TENANT)
    assert patched.status_code == 200, patched.text
    updated = api.BusinessOut.model_validate(patched.json())
    assert updated.name == "Acme Traders"
    assert updated.version > read.version

    onboarding = api.OnboardingOut.model_validate(
        client.get(f"{path}/onboarding", headers=AS_TENANT).json()
    )
    assert onboarding.business_id == business_id
    assert onboarding.answered <= onboarding.total

    added = client.post(
        f"{path}/registrations",
        json=body(api.RegistrationAddIn(gstin=GSTIN_DELHI.value, name="Delhi")),
        headers=keyed(),
    )
    assert added.status_code == 201, added.text
    registration = api.RegistrationCreatedOut.model_validate(added.json())
    assert registration.created
    assert registration.registration.name == "Delhi"
    assert len(registration.business.registrations) == 2


def test_the_ontology_reads_into_its_model(client: TestClient) -> None:
    ontology = api.OntologyOut.model_validate(client.get("/v1/ontology").json())
    assert ontology.attributes
    assert all(attribute.values is not None for attribute in ontology.attributes)
    assert ontology.operators_by_type


def test_errors_read_as_problems(client: TestClient) -> None:
    missing = client.get(f"{BUSINESSES}/{uuid4()}", headers=AS_TENANT)
    assert missing.status_code == 404
    problem = api.Problem.model_validate(missing.json())
    assert problem.status == 404
    invalid = client.post(BUSINESSES, json={"name": ""}, headers=keyed())
    assert invalid.status_code == 422
    issues = api.Problem.model_validate(invalid.json()).errors
    assert issues
    assert all(isinstance(issue, api.ValidationIssue) for issue in issues)
