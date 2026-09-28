from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from domain_kernel.identifiers import Gstin
from domain_kernel.ids import BusinessId
from domain_kernel.ontology import AttributeSource
from ontology import load
from profile_service.application.attributes import SetAttributes
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import InvalidHierarchyError, ProfileNodeNotFoundError
from profile_service.domain.lookup import GstinLookupProvider, GstinLookupResult
from profile_service.domain.model import ReviewReason
from profile_service.infrastructure.lookup import (
    DEMO_LOOKUPS,
    ManualLookupProvider,
    StaticLookupProvider,
)
from profile_service.infrastructure.memory import MemoryStore
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_KARNATAKA, TENANT, clock

HEADERS = {"x-tenant-id": str(TENANT)}


def profile_settings(**overrides: Any) -> ProfileSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "profile",
        "profile_store": "memory",
    }
    values.update(overrides)
    return ProfileSettings(**values)


def setup(
    provider: GstinLookupProvider,
) -> tuple[MemoryStore, PrefillFromGstin, BusinessId, BusinessId]:
    store = MemoryStore()
    ontology = load()
    set_attributes = SetAttributes(store, ontology, clock=clock)
    registered = RegisterNodes(store, clock=clock).registration(TENANT, GSTIN_KARNATAKA, "Acme")
    entity = registered.node.parent_id
    assert entity is not None
    return (
        store,
        PrefillFromGstin(store, provider, set_attributes, ontology),
        registered.node.id,
        entity,
    )


def test_manual_provider_opens_one_verification_task() -> None:
    store, prefill, registration, _ = setup(ManualLookupProvider())
    first = prefill.run(TENANT, registration)
    assert not first.looked_up
    assert first.review_task is not None
    again = prefill.run(TENANT, registration)
    assert again.review_task == first.review_task
    with store(TENANT) as uow:
        tasks = uow.profiles.open_review_tasks(registration)
    assert [t.reason for t in tasks] == [ReviewReason.VERIFY_REGISTRATION]


def test_static_provider_fills_attributes_with_the_lookup_source() -> None:
    provider = StaticLookupProvider(DEMO_LOOKUPS)
    store, prefill, registration, _ = setup(provider)
    result = prefill.run(TENANT, registration)
    assert result.looked_up
    assert set(result.applied) == {
        "registration_type",
        "gstin_status",
        "constitution",
        "registered_since",
    }
    with store(TENANT) as uow:
        node = uow.profiles.get(registration)
        assert node is not None
        assert node.parent_id is not None
        entity = uow.profiles.get(node.parent_id)
    record = node.value("registration_type")
    assert record is not None
    assert (record.value, record.source) == ("regular", AttributeSource.GSTIN_LOOKUP)
    assert entity is not None
    constitution = entity.value("constitution")
    assert constitution is not None
    assert constitution.value == "private_limited"
    assert provider.calls == [GSTIN_KARNATAKA]


def test_prefill_needs_a_registration() -> None:
    _, prefill, _, entity = setup(ManualLookupProvider())
    with pytest.raises(InvalidHierarchyError):
        prefill.run(TENANT, entity)
    with pytest.raises(ProfileNodeNotFoundError):
        prefill.run(TENANT, BusinessId.new())


def test_lookup_result_maps_only_what_it_knows() -> None:
    result = GstinLookupResult(
        Gstin("07ABCDE1234F1Z9"), legal_name="X", registered_since=date(2020, 1, 1)
    )
    assert result.attribute_values() == {"registered_since": "2020-01-01"}


def test_prefill_endpoint_with_the_static_provider() -> None:
    with TestClient(build_app(profile_settings(profile_gstin_lookup="static"))) as client:
        created = client.post(
            "/v1/profile/registrations",
            json={"gstin": GSTIN_KARNATAKA.value, "name": "Acme Bengaluru", "entity_name": "Acme"},
            headers=HEADERS,
        )
        node_id = created.json()["id"]
        response = client.post(
            f"/v1/profile/registrations/{node_id}/prefill", json={}, headers=HEADERS
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["looked_up"] is True
        assert body["result"]["legal_name"] == "Acme Traders Private Limited"
        assert "registration_type" in body["applied"]
    with TestClient(build_app(profile_settings())) as client:
        created = client.post(
            "/v1/profile/registrations",
            json={"gstin": GSTIN_KARNATAKA.value, "name": "Acme Bengaluru", "entity_name": "Acme"},
            headers=HEADERS,
        )
        node_id = created.json()["id"]
        body = client.post(
            f"/v1/profile/registrations/{node_id}/prefill", json={}, headers=HEADERS
        ).json()
        assert body["looked_up"] is False
        assert body["review_task"] is not None
        tasks = client.get(f"/v1/profile/nodes/{node_id}/review-tasks", headers=HEADERS).json()
        assert tasks[0]["reason"] == "verify_registration"
