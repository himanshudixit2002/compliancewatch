from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from domain_kernel.identifiers import Gstin
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeSource
from ontology import load
from profile_service.application.attributes import SetAttributes
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import InvalidHierarchyError, ProfileNodeNotFoundError
from profile_service.domain.events import ChangeSource
from profile_service.domain.flags import GSTIN_CATEGORY_PREFILL
from profile_service.domain.lookup import GstinLookupProvider, GstinLookupResult, single_category
from profile_service.domain.model import AttributeChange, ReviewReason, ValueState
from profile_service.infrastructure.flags import OpenFeatureFlags
from profile_service.infrastructure.lookup import (
    DEMO_LOOKUPS,
    ManualLookupProvider,
    StaticLookupProvider,
)
from profile_service.infrastructure.memory import MemoryStore
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_KARNATAKA, OTHER_TENANT, TENANT, FixedFlags, clock
from py_common.flags import configure_flags, reset_flags

HEADERS = {"x-tenant-id": str(TENANT)}
GSTIN_OTHER_TERRITORY = Gstin("97ABCDE1234F1Z5")
"""State code 97 (Other Territory) is not a place of business; the ontology leaves it out."""
SYNTHETIC = replace(
    DEMO_LOOKUPS[GSTIN_KARNATAKA.value],
    nature_of_business=("Wholesale Business",),
    business_category="wholesale_trade",
)
"""A synthetic lookup answer with one mapped category; never a real registration."""


def profile_settings(**overrides: Any) -> ProfileSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "profile",
        "profile_store": "memory",
    }
    values.update(overrides)
    return ProfileSettings(**values)


@pytest.fixture(autouse=True)
def no_flag_provider() -> Iterator[None]:
    yield
    reset_flags()


def setup(
    provider: GstinLookupProvider,
    *,
    flags: FixedFlags | None = None,
    gstin: Gstin = GSTIN_KARNATAKA,
    entity_values: list[AttributeChange] | None = None,
) -> tuple[MemoryStore, PrefillFromGstin, BusinessId, BusinessId]:
    store = MemoryStore()
    ontology = load()
    registered = RegisterNodes(store, clock=clock).registration(TENANT, gstin, "Acme")
    entity = registered.node.parent_id
    assert entity is not None
    if entity_values:
        SetAttributes(store, ontology, clock=clock).run(
            TENANT, entity, entity_values, source=ChangeSource.USER_INPUT
        )
    prefill = PrefillFromGstin(store, provider, ontology, flags or FixedFlags(), clock=clock)
    return store, prefill, registered.node.id, entity


def attribute(store: MemoryStore, node_id: BusinessId, key: str) -> tuple[object, object] | None:
    with store(TENANT) as uow:
        node = uow.profiles.get(node_id)
    assert node is not None
    record = node.value(key)
    return None if record is None else (record.value, record.source)


def test_manual_provider_derives_the_state_code_and_opens_one_verification_task() -> None:
    store, prefill, registration, entity = setup(ManualLookupProvider())
    first = prefill.run(TENANT, registration)
    assert not first.looked_up
    assert first.applied == ("state_codes",)
    assert first.review_task is not None
    assert attribute(store, entity, "state_codes") == (frozenset({"29"}), AttributeSource.DERIVED)
    again = prefill.run(TENANT, registration)
    assert again.applied == ()
    assert again.review_task == first.review_task
    with store(TENANT) as uow:
        tasks = uow.profiles.open_review_tasks(registration)
    assert [t.reason for t in tasks] == [ReviewReason.VERIFY_REGISTRATION]


def test_static_provider_fills_attributes_with_the_lookup_source() -> None:
    provider = StaticLookupProvider(DEMO_LOOKUPS)
    store, prefill, registration, entity = setup(provider)
    result = prefill.run(TENANT, registration)
    assert result.looked_up
    assert result.review_task is None
    assert set(result.applied) == {
        "state_codes",
        "registration_type",
        "gstin_status",
        "constitution",
        "registered_since",
    }
    assert attribute(store, registration, "registration_type") == (
        "regular",
        AttributeSource.GSTIN_LOOKUP,
    )
    assert attribute(store, entity, "constitution") == (
        "private_limited",
        AttributeSource.GSTIN_LOOKUP,
    )
    assert provider.calls == [GSTIN_KARNATAKA]
    with store(TENANT) as uow:
        assert uow.profiles.open_review_tasks(registration) == []
    topics = [(event.topic, getattr(event, "source", None)) for event in store.events]
    assert topics == [("profile.updated", ChangeSource.GSTIN_LOOKUP)] * 2


def test_the_state_code_joins_the_codes_already_known() -> None:
    store, prefill, registration, entity = setup(
        ManualLookupProvider(), entity_values=[AttributeChange("state_codes", ["07"])]
    )
    assert prefill.run(TENANT, registration).applied == ("state_codes",)
    assert attribute(store, entity, "state_codes") == (
        frozenset({"07", "29"}),
        AttributeSource.DERIVED,
    )


def test_a_state_code_already_known_is_left_as_the_owner_gave_it() -> None:
    store, prefill, registration, entity = setup(
        ManualLookupProvider(), entity_values=[AttributeChange("state_codes", ["29", "07"])]
    )
    assert prefill.run(TENANT, registration).applied == ()
    assert attribute(store, entity, "state_codes") == (
        frozenset({"07", "29"}),
        AttributeSource.USER_INPUT,
    )


def test_an_unsure_state_code_answer_is_replaced_by_the_gstin_code() -> None:
    store, prefill, registration, entity = setup(
        ManualLookupProvider(),
        entity_values=[AttributeChange("state_codes", state=ValueState.UNSURE)],
    )
    assert prefill.run(TENANT, registration).applied == ("state_codes",)
    assert attribute(store, entity, "state_codes") == (frozenset({"29"}), AttributeSource.DERIVED)


def test_a_state_code_the_ontology_does_not_list_is_skipped() -> None:
    store, prefill, registration, entity = setup(
        ManualLookupProvider(), gstin=GSTIN_OTHER_TERRITORY
    )
    result = prefill.run(TENANT, registration)
    assert result.applied == ()
    assert result.review_task is not None
    assert attribute(store, entity, "state_codes") is None


@pytest.mark.parametrize(
    ("flags", "category", "written"),
    [
        (FixedFlags(), "wholesale_trade", False),
        (FixedFlags(on={GSTIN_CATEGORY_PREFILL}), "wholesale_trade", True),
        (FixedFlags(on={GSTIN_CATEGORY_PREFILL}), "", False),
        (FixedFlags(on={GSTIN_CATEGORY_PREFILL}, tenants={OTHER_TENANT}), "wholesale_trade", False),
        (FixedFlags(on={GSTIN_CATEGORY_PREFILL}, tenants={TENANT}), "wholesale_trade", True),
    ],
    ids=["flag-off", "flag-on", "no-single-category", "on-for-another-tenant", "on-for-tenant"],
)
def test_the_business_category_needs_the_flag_and_a_single_category(
    flags: FixedFlags, category: str, written: bool
) -> None:
    answer = replace(SYNTHETIC, business_category=category)
    store, prefill, registration, entity = setup(
        StaticLookupProvider({GSTIN_KARNATAKA.value: answer}), flags=flags
    )
    result = prefill.run(TENANT, registration)
    assert ("business_category" in result.applied) is written
    stored = attribute(store, entity, "business_category")
    assert stored == (("wholesale_trade", AttributeSource.GSTIN_LOOKUP) if written else None)


def test_prefill_needs_a_registration() -> None:
    store, prefill, _, entity = setup(ManualLookupProvider())
    with pytest.raises(InvalidHierarchyError):
        prefill.run(TENANT, entity)
    with pytest.raises(ProfileNodeNotFoundError):
        prefill.run(TENANT, BusinessId.new())
    with store(TENANT) as uow:
        node = uow.profiles.get(entity)
        assert node is not None
        with pytest.raises(InvalidHierarchyError):
            prefill.apply(uow, TENANT, node, None)


def test_lookup_result_maps_only_what_it_knows() -> None:
    result = GstinLookupResult(
        Gstin("07ABCDE1234F1Z9"),
        legal_name="X",
        registered_since=date(2020, 1, 1),
        nature_of_business=("Retail Business",),
        business_category="retail_trade",
    )
    assert result.attribute_values() == {"registered_since": "2020-01-01"}


def test_lookup_result_refuses_a_blank_activity() -> None:
    with pytest.raises(ValueError, match="nature_of_business"):
        GstinLookupResult(GSTIN_KARNATAKA, legal_name="X", nature_of_business=(" ",))


@pytest.mark.parametrize(
    ("categories", "expected"),
    [
        ((), ""),
        (("",), ""),
        (("wholesale_trade",), "wholesale_trade"),
        (("wholesale_trade", "wholesale_trade", ""), "wholesale_trade"),
        (("wholesale_trade", "retail_trade"), ""),
    ],
)
def test_single_category_needs_every_mapped_activity_to_agree(
    categories: tuple[str, ...], expected: str
) -> None:
    assert single_category(categories) == expected


def test_open_feature_flags_answer_per_tenant() -> None:
    configure_flags(
        profile_settings(),
        environ={
            "CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL": "true",
            "CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL__TENANTS": str(TENANT),
        },
    )
    flags = OpenFeatureFlags()
    assert flags.enabled(GSTIN_CATEGORY_PREFILL, TENANT)
    assert not flags.enabled(GSTIN_CATEGORY_PREFILL, OTHER_TENANT)


def test_the_app_configures_the_flags_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL", "true")
    build_app(profile_settings())
    assert OpenFeatureFlags().enabled(GSTIN_CATEGORY_PREFILL, TenantId.new())
    monkeypatch.delenv("CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL")
    build_app(profile_settings())
    assert not OpenFeatureFlags().enabled(GSTIN_CATEGORY_PREFILL, TenantId.new())


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
        assert body["result"]["nature_of_business"] == []
        assert body["result"]["business_category"] == ""
        assert {"registration_type", "state_codes"} <= set(body["applied"])
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
        assert body["applied"] == ["state_codes"]
        assert body["review_task"] is not None
        tasks = client.get(f"/v1/profile/nodes/{node_id}/review-tasks", headers=HEADERS).json()
        assert tasks[0]["reason"] == "verify_registration"
