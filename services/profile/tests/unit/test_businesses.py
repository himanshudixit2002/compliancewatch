"""The business API on the memory store: the use cases (create, update, read, list, add a
registration) and the routes under /v1/businesses with idempotency keys and pagination."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import ontology as ontology_package
from domain_kernel.errors import InvalidAttributeValueError
from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId
from domain_kernel.ontology import AttributeSource, Ontology
from profile_service.application.businesses import (
    AddRegistration,
    Answer,
    Business,
    CreateBusiness,
    ListBusinesses,
    ReadBusiness,
    UpdateBusiness,
)
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import (
    AttributeLevelMismatchError,
    BusinessIdentifierRequiredError,
    InvalidHierarchyError,
    NotABusinessError,
    ProfileNodeNotFoundError,
    RegistrationAmbiguousError,
)
from profile_service.domain.events import ProfileUpdated
from profile_service.domain.model import AttributeChange, ProfileNode, ValueState
from profile_service.infrastructure.lookup import DEMO_LOOKUPS, StaticLookupProvider
from profile_service.infrastructure.memory import MemoryStore
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import (
    GSTIN_DELHI,
    GSTIN_KARNATAKA,
    NOW,
    OTHER_TENANT,
    PAN,
    TENANT,
    FixedFlags,
    clock,
)

BUSINESSES = "/v1/businesses"
AS_TENANT = {"x-tenant-id": str(TENANT)}
AS_OTHER = {"x-tenant-id": str(OTHER_TENANT)}
PAN_ALPHA = Pan("AAAAA1111A")
PAN_BRAVO = Pan("BBBBB2222B")
GSTIN_OTHER_PAN = Gstin("29ZZZZZ9999Z1Z5")


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


class Service:
    """The business use cases on one memory store, with the demo lookup table."""

    def __init__(self, ontology: Ontology) -> None:
        self.store = MemoryStore()
        self.lookup = StaticLookupProvider(DEMO_LOOKUPS)
        prefill = PrefillFromGstin(self.store, self.lookup, ontology, FixedFlags(), clock=clock)
        self.create = CreateBusiness(self.store, ontology, prefill, clock=clock)
        self.update = UpdateBusiness(self.store, ontology, clock=clock)
        self.read = ReadBusiness(self.store)
        self.list = ListBusinesses(self.store)
        self.add_registration = AddRegistration(self.store, prefill, clock=clock)

    def node(self, node_id: BusinessId) -> ProfileNode:
        with self.store(TENANT) as uow:
            node = uow.profiles.get(node_id)
        assert node is not None
        return node

    def updates(self) -> list[tuple[BusinessId, tuple[str, ...]]]:
        return [
            (event.business_id, event.changed_attributes)
            for event in self.store.events
            if isinstance(event, ProfileUpdated)
        ]


@pytest.fixture
def service(ontology: Ontology) -> Service:
    return Service(ontology)


def value_of(node: ProfileNode, key: str) -> object:
    record = node.value(key)
    return None if record is None else record.value


# ---------------------------------------------------------------------------------- use cases


def test_a_gstin_creates_the_business_prefills_it_and_stores_the_answers(
    service: Service,
) -> None:
    created = service.create.run(
        TENANT,
        name="Acme",
        gstin=GSTIN_KARNATAKA,
        registration_name="Acme Bengaluru",
        answers=[
            Answer(AttributeChange("employee_count", 12)),
            Answer(AttributeChange("supply_type", "goods")),
        ],
    )
    business = created.business
    assert created.created
    assert (business.entity.key, business.entity.name) == (PAN.value, "Acme")
    [registration] = business.registrations
    assert (registration.key, registration.name) == (GSTIN_KARNATAKA.value, "Acme Bengaluru")
    assert created.prefill is not None
    assert created.prefill.looked_up
    assert value_of(business.entity, "state_codes") == frozenset({"29"})
    assert value_of(business.entity, "constitution") == "private_limited"
    assert value_of(business.entity, "employee_count") == 12
    assert value_of(registration, "supply_type") == "goods"
    assert value_of(registration, "registration_type") == "regular"
    assert service.lookup.calls == [GSTIN_KARNATAKA]
    assert created.checklist.next is not None
    assert created.checklist.next.key == "business_category"
    assert {node_id for node_id, _ in service.updates()} == {business.id, registration.id}


def test_the_same_business_again_is_found_not_created(service: Service) -> None:
    first = service.create.run(TENANT, name="Acme", gstin=GSTIN_KARNATAKA)
    again = service.create.run(TENANT, name="Renamed", pan=PAN, gstin=GSTIN_KARNATAKA)
    assert not again.created
    assert again.business.id == first.business.id
    assert again.business.entity.name == "Acme"


def test_a_pan_alone_creates_a_business_without_a_registration(service: Service) -> None:
    created = service.create.run(
        TENANT, name="Beta", pan=PAN_BRAVO, answers=[Answer(AttributeChange("employee_count", 3))]
    )
    assert created.created
    assert created.prefill is None
    assert created.business.registrations == ()
    assert value_of(created.business.entity, "employee_count") == 3
    assert service.lookup.calls == []
    assert created.checklist.total == 6, "only the entity's questions without a registration"


def test_a_business_needs_a_pan_or_a_gstin_that_agree(service: Service) -> None:
    with pytest.raises(BusinessIdentifierRequiredError):
        service.create.run(TENANT, name="Nobody")
    with pytest.raises(InvalidHierarchyError, match="carries PAN"):
        service.create.run(TENANT, name="Mixed", pan=PAN_ALPHA, gstin=GSTIN_KARNATAKA)
    assert service.store.nodes == {}


def test_a_registration_answer_without_a_registration_creates_nothing(service: Service) -> None:
    with pytest.raises(RegistrationAmbiguousError, match="has no registration"):
        service.create.run(
            TENANT,
            name="Beta",
            pan=PAN_BRAVO,
            answers=[Answer(AttributeChange("supply_type", "goods"))],
        )
    assert service.store.nodes == {}
    assert service.store.events == []


def test_an_update_is_all_or_nothing(service: Service) -> None:
    business = service.create.run(TENANT, name="Acme", gstin=GSTIN_KARNATAKA).business
    before = (service.node(business.id).version, len(service.store.events))
    with pytest.raises(InvalidAttributeValueError):
        service.update.run(
            TENANT,
            business.id,
            name="Acme Renamed",
            answers=[
                Answer(AttributeChange("employee_count", 40)),
                Answer(AttributeChange("supply_type", "spaceships")),
            ],
        )
    entity = service.node(business.id)
    assert (entity.version, len(service.store.events)) == before
    assert (entity.name, value_of(entity, "employee_count")) == ("Acme", None)


def test_an_update_routes_each_answer_and_publishes_per_node(service: Service) -> None:
    business = service.create.run(TENANT, name="Acme", gstin=GSTIN_KARNATAKA).business
    [registration] = business.registrations
    published = len(service.store.events)
    updated = service.update.run(
        TENANT,
        business.id,
        answers=[
            Answer(AttributeChange("employee_count", 40)),
            Answer(AttributeChange("supply_type", "services")),
            Answer(AttributeChange("business_category", state=ValueState.UNSURE)),
        ],
    )
    assert value_of(updated.entity, "employee_count") == 40
    assert updated.entity.value("business_category") is not None
    assert value_of(updated.registrations[0], "supply_type") == "services"
    assert service.updates()[published:] == [
        (business.id, ("employee_count", "business_category")),
        (registration.id, ("supply_type",)),
    ]


def test_a_registration_answer_needs_a_node_when_there_are_several(service: Service) -> None:
    business = service.create.run(TENANT, name="Acme", gstin=GSTIN_KARNATAKA).business
    delhi = service.add_registration.run(TENANT, business.id, GSTIN_DELHI).registration
    with pytest.raises(RegistrationAmbiguousError, match="has 2"):
        service.update.run(
            TENANT, business.id, answers=[Answer(AttributeChange("supply_type", "goods"))]
        )
    updated = service.update.run(
        TENANT,
        business.id,
        answers=[Answer(AttributeChange("supply_type", "goods"), node_id=delhi.id)],
    )
    assert {node.id: value_of(node, "supply_type") for node in updated.registrations} == {
        business.registrations[0].id: None,
        delhi.id: "goods",
    }


def test_a_node_outside_the_business_or_at_another_level_is_refused(service: Service) -> None:
    business = service.create.run(TENANT, name="Acme", gstin=GSTIN_KARNATAKA).business
    [registration] = business.registrations
    other = service.create.run(TENANT, name="Beta", pan=PAN_BRAVO).business
    shop = RegisterNodes(service.store, clock=clock).location(
        TENANT, registration.id, "whitefield", "Whitefield"
    )
    with pytest.raises(InvalidHierarchyError, match="is not part of business"):
        service.update.run(
            TENANT,
            business.id,
            answers=[Answer(AttributeChange("employee_count", 1), node_id=other.id)],
        )
    with pytest.raises(AttributeLevelMismatchError):
        service.update.run(
            TENANT,
            business.id,
            answers=[Answer(AttributeChange("employee_count", 1), node_id=shop.node.id)],
        )


def test_a_location_answer_goes_to_the_only_location() -> None:
    ontology = Ontology.from_mapping(
        {
            "version": "1.0.0",
            "attributes": [
                {
                    "key": "has_warehouse",
                    "type": "boolean",
                    "source": "user_input",
                    "level": "location",
                    "definition": "A made-up location attribute.",
                }
            ],
        }
    )
    store = MemoryStore()
    register = RegisterNodes(store, clock=clock)
    registration = register.registration(TENANT, GSTIN_KARNATAKA, "Acme").node
    assert registration.parent_id is not None
    update = UpdateBusiness(store, ontology, clock=clock)
    answer = Answer(AttributeChange("has_warehouse", value=True))
    with pytest.raises(RegistrationAmbiguousError, match="has no location"):
        update.run(TENANT, registration.parent_id, answers=[answer])
    shop = register.location(TENANT, registration.id, "whitefield", "Whitefield").node
    update.run(TENANT, registration.parent_id, answers=[answer])
    with store(TENANT) as uow:
        stored = uow.profiles.get(shop.id)
    assert stored is not None
    assert value_of(stored, "has_warehouse") is True


def test_a_rename_bumps_the_version_without_an_event(service: Service) -> None:
    business = service.create.run(TENANT, name="Acme", pan=PAN_ALPHA).business
    renamed = service.update.run(TENANT, business.id, name="Acme Holdings")
    assert (renamed.entity.name, renamed.entity.version) == ("Acme Holdings", 2)
    assert renamed.entity.updated_at == NOW
    assert service.update.run(TENANT, business.id, name="Acme Holdings").entity.version == 2
    both = service.update.run(
        TENANT,
        business.id,
        name="Acme Group",
        answers=[Answer(AttributeChange("employee_count", 5))],
    )
    assert (both.entity.name, both.entity.version) == ("Acme Group", 4)
    assert service.updates() == [(business.id, ("employee_count",))]
    node = service.node(business.id)
    assert node.renamed("Acme Group", NOW) is node


def test_read_names_a_business_only(service: Service) -> None:
    business = service.create.run(TENANT, name="Acme", gstin=GSTIN_KARNATAKA).business
    assert service.read.run(TENANT, business.id) == business
    with pytest.raises(NotABusinessError):
        service.read.run(TENANT, business.registrations[0].id)
    with pytest.raises(ProfileNodeNotFoundError):
        service.read.run(TENANT, BusinessId.new())
    with pytest.raises(ProfileNodeNotFoundError):
        service.read.run(OTHER_TENANT, business.id)


def names(page: list[Business]) -> list[str]:
    return [business.entity.name for business in page]


def test_the_list_pages_by_name_and_filters_by_name_pan_or_gstin(service: Service) -> None:
    service.create.run(TENANT, name="Charlie", gstin=GSTIN_KARNATAKA)
    alpha = service.create.run(TENANT, name="Alpha", pan=PAN_ALPHA).business
    service.create.run(TENANT, name="Bravo", pan=PAN_BRAVO)
    service.create.run(OTHER_TENANT, name="Aardvark", pan=PAN_ALPHA)
    first = service.list.run(TENANT, limit=2)
    assert names(first) == ["Alpha", "Bravo"]
    assert names(service.list.run(TENANT, after=first[-1].id, limit=2)) == ["Charlie"]
    assert names(service.list.run(TENANT, after=alpha.id, limit=5)) == ["Bravo", "Charlie"]
    assert names(service.list.run(TENANT, limit=5, query="rav")) == ["Bravo"]
    assert names(service.list.run(TENANT, limit=5, query="aaaaa1111")) == ["Alpha"]
    assert names(service.list.run(TENANT, limit=5, query="29abcde")) == ["Charlie"]
    [charlie] = service.list.run(TENANT, limit=5, query="charlie")
    assert [node.key for node in charlie.registrations] == [GSTIN_KARNATAKA.value]
    with pytest.raises(ProfileNodeNotFoundError):
        service.list.run(OTHER_TENANT, after=alpha.id, limit=2)
    with pytest.raises(ValueError, match="at least 1"):
        service.list.run(TENANT, limit=0)


def test_a_registration_is_added_under_its_pan_and_prefilled(service: Service) -> None:
    business = service.create.run(TENANT, name="Acme", gstin=GSTIN_KARNATAKA).business
    added = service.add_registration.run(TENANT, business.id, GSTIN_DELHI)
    assert added.created
    assert (added.registration.key, added.registration.name) == (GSTIN_DELHI.value, "Acme")
    assert not added.prefill.looked_up, "the demo table has no Delhi entry"
    assert added.prefill.review_task is not None
    assert value_of(added.business.entity, "state_codes") == frozenset({"07", "29"})
    record = added.business.entity.value("state_codes")
    assert record is not None
    assert record.source is AttributeSource.DERIVED
    again = service.add_registration.run(TENANT, business.id, GSTIN_DELHI, name="Delhi")
    assert not again.created
    assert again.registration.id == added.registration.id
    with pytest.raises(InvalidHierarchyError, match="carries PAN"):
        service.add_registration.run(TENANT, business.id, GSTIN_OTHER_PAN)
    with pytest.raises(NotABusinessError):
        service.add_registration.run(TENANT, added.registration.id, GSTIN_DELHI)


# ---------------------------------------------------------------------------------- routes


def settings(**overrides: Any) -> ProfileSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "profile",
        "profile_store": "memory",
        "profile_gstin_lookup": "static",
    }
    return ProfileSettings(**(values | overrides))


@pytest.fixture
def api() -> Iterator[TestClient]:
    with TestClient(build_app(settings(), flags=FixedFlags())) as client:
        yield client


def keyed(key: str | None = None) -> dict[str, str]:
    return {**AS_TENANT, "Idempotency-Key": key or f"key-{uuid4()}"}


def create(client: TestClient, body: dict[str, Any], key: str | None = None) -> Any:
    response = client.post(BUSINESSES, json=body, headers=keyed(key))
    assert response.status_code == 201, response.text
    return response.json()


def problem_type(response: Any) -> str:
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"]).rsplit(":", 1)[-1]


def test_create_replays_a_retry_and_refuses_a_reused_key(api: TestClient) -> None:
    body = {
        "name": "Acme",
        "gstin": " 29abcde1234f1z5 ",
        "answers": [{"key": "employee_count", "value": 12}],
    }
    first = api.post(BUSINESSES, json=body, headers=keyed("retry-key-0001"))
    assert first.status_code == 201, first.text
    assert "idempotent-replayed" not in first.headers
    created = first.json()
    assert created["created"] is True
    assert created["business"]["pan"] == PAN.value
    assert created["prefill"]["looked_up"] is True
    assert created["onboarding"]["next"]["key"] == "business_category"
    retry = api.post(BUSINESSES, json=body, headers=keyed("retry-key-0001"))
    assert retry.status_code == 201
    assert retry.headers["idempotent-replayed"] == "true"
    assert retry.json() == created
    reused = api.post(BUSINESSES, json={**body, "name": "Other"}, headers=keyed("retry-key-0001"))
    assert reused.status_code == 422
    assert problem_type(reused) == "idempotency-key-reused"
    listed = api.get(BUSINESSES, headers=AS_TENANT).json()
    assert [item["name"] for item in listed["items"]] == ["Acme"]


def test_create_needs_a_tenant_then_a_key(api: TestClient) -> None:
    body = {"name": "Acme", "pan": PAN.value}
    assert api.post(BUSINESSES, json=body).status_code == 401
    missing = api.post(BUSINESSES, json=body, headers=AS_TENANT)
    assert missing.status_code == 428
    assert problem_type(missing) == "idempotency-key-required"


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ({"name": "Nobody"}, "profile-business-identifier-required"),
        ({"name": "Bad", "pan": "not-a-pan!"}, "invariant-violation"),
        (
            {"name": "X", "pan": PAN.value, "gstin": GSTIN_OTHER_PAN.value},
            "profile-hierarchy-invalid",
        ),
        (
            {"name": "X", "pan": PAN.value, "answers": [{"key": "supply_type", "value": "goods"}]},
            "profile-registration-ambiguous",
        ),
        (
            {"name": "X", "pan": PAN.value, "answers": [{"key": "nope", "value": 1}]},
            "unknown-attribute",
        ),
    ],
)
def test_create_refusals_are_problems_and_free_the_key(
    api: TestClient, body: dict[str, Any], problem: str
) -> None:
    refused = api.post(BUSINESSES, json=body, headers=keyed("refused-key-01"))
    assert refused.status_code == 422, refused.text
    assert problem_type(refused) == problem
    fixed = api.post(
        BUSINESSES, json={"name": "Fixed", "pan": PAN_ALPHA.value}, headers=keyed("refused-key-01")
    )
    assert fixed.status_code == 201, "a refused request records nothing against its key"


def test_the_list_pages_with_a_cursor_and_filters(api: TestClient) -> None:
    for name, pan in (
        ("Charlie", PAN.value),
        ("Alpha", PAN_ALPHA.value),
        ("Bravo", PAN_BRAVO.value),
    ):
        create(api, {"name": name, "pan": pan})
    first = api.get(BUSINESSES, params={"limit": 2}, headers=AS_TENANT)
    assert first.status_code == 200, first.text
    page = first.json()
    assert [item["name"] for item in page["items"]] == ["Alpha", "Bravo"]
    assert page["next_cursor"]
    last = api.get(
        BUSINESSES, params={"limit": 2, "cursor": page["next_cursor"]}, headers=AS_TENANT
    ).json()
    assert [item["name"] for item in last["items"]] == ["Charlie"]
    assert last["next_cursor"] is None
    found = api.get(BUSINESSES, params={"q": "BRAVO"}, headers=AS_TENANT).json()
    assert [(item["name"], item["pan"], item["gstins"]) for item in found["items"]] == [
        ("Bravo", PAN_BRAVO.value, [])
    ]
    foreign = api.get(BUSINESSES, params={"cursor": page["next_cursor"]}, headers=AS_OTHER)
    assert foreign.status_code == 422
    assert problem_type(foreign) == "pagination-cursor-invalid"
    garbage = api.get(BUSINESSES, params={"cursor": "not-a-cursor"}, headers=AS_TENANT)
    assert problem_type(garbage) == "pagination-cursor-invalid"
    assert api.get(BUSINESSES, headers=AS_OTHER).json() == {"items": [], "next_cursor": None}


def test_read_and_patch_a_business(api: TestClient) -> None:
    created = create(api, {"name": "Acme", "gstin": GSTIN_KARNATAKA.value})
    business_id = created["business"]["id"]
    registration_id = created["business"]["registrations"][0]["id"]
    read = api.get(f"{BUSINESSES}/{business_id}", headers=AS_TENANT)
    assert read.json() == created["business"]
    patched = api.patch(
        f"{BUSINESSES}/{business_id}",
        json={
            "name": "Acme Traders",
            "changes": [
                {"key": "turnover_band", "value": "2_crore_to_5_crore", "as_of_fy": "2026-27"},
                {"key": "supply_type", "value": "goods", "node_id": registration_id},
            ],
        },
        headers=AS_TENANT,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Acme Traders"
    assert {a["key"]: a["value"] for a in body["registrations"][0]["attributes"]}[
        "supply_type"
    ] == "goods"
    refused = api.patch(
        f"{BUSINESSES}/{business_id}",
        json={
            "changes": [
                {"key": "employee_count", "value": 3},
                {"key": "employee_count", "value": -1},
            ]
        },
        headers=AS_TENANT,
    )
    assert problem_type(refused) == "invalid-attribute-value"
    again = api.get(f"{BUSINESSES}/{business_id}", headers=AS_TENANT).json()
    assert "employee_count" not in {a["key"] for a in again["attributes"]}
    assert again["version"] == body["version"]
    not_a_business = api.get(f"{BUSINESSES}/{registration_id}", headers=AS_TENANT)
    assert not_a_business.status_code == 404
    assert problem_type(not_a_business) == "profile-node-not-a-business"
    assert api.get(f"{BUSINESSES}/{business_id}", headers=AS_OTHER).status_code == 404
    assert api.patch(f"{BUSINESSES}/{uuid4()}", json={}, headers=AS_TENANT).status_code == 404


def test_onboarding_asks_one_worded_question_at_a_time(api: TestClient) -> None:
    created = create(api, {"name": "Beta", "pan": PAN_BRAVO.value})
    business_id = created["business"]["id"]
    onboarding = api.get(f"{BUSINESSES}/{business_id}/onboarding", headers=AS_TENANT)
    assert onboarding.status_code == 200, onboarding.text
    body = onboarding.json()
    assert body == created["onboarding"]
    question = body["next"]
    assert (question["key"], question["state"], question["level"]) == (
        "state_codes",
        "missing",
        "entity",
    )
    assert question["question"].endswith("?")
    labels = {option["value"]: option["label"] for option in question["options"]}
    assert labels["29"] == "Karnataka"
    assert (body["answered"], body["total"], body["complete"]) == (0, 6, False)
    answers = [
        {"key": "state_codes", "value": ["29"]},
        {"key": "constitution", "value": "llp"},
        {"key": "business_category", "value": "services"},
        {"key": "turnover_band", "state": "unsure", "as_of_fy": body["as_of_fy"]},
        {"key": "peak_turnover_band", "value": "upto_10_lakh"},
        {"key": "employee_count", "state": "not_applicable"},
    ]
    api.patch(f"{BUSINESSES}/{business_id}", json={"changes": answers}, headers=AS_TENANT)
    unsure = api.get(f"{BUSINESSES}/{business_id}/onboarding", headers=AS_TENANT).json()
    assert (unsure["next"]["key"], unsure["next"]["state"]) == ("turnover_band", "unsure")
    assert unsure["next"]["as_of_fy"] == body["as_of_fy"]
    api.patch(
        f"{BUSINESSES}/{business_id}",
        json={
            "changes": [
                {"key": "turnover_band", "value": "upto_10_lakh", "as_of_fy": body["as_of_fy"]}
            ]
        },
        headers=AS_TENANT,
    )
    done = api.get(f"{BUSINESSES}/{business_id}/onboarding", headers=AS_TENANT).json()
    assert (done["answered"], done["total"], done["complete"], done["next"]) == (6, 6, True, None)


def test_the_onboarding_question_carries_the_bounds_of_a_number(api: TestClient) -> None:
    created = create(
        api,
        {
            "name": "Beta",
            "pan": PAN_BRAVO.value,
            "answers": [
                {"key": key, "state": "unsure"}
                for key in ("state_codes", "constitution", "business_category")
            ]
            + [{"key": "turnover_band", "state": "unsure", "as_of_fy": "2026-27"}],
        },
    )
    question = created["onboarding"]["next"]
    assert question["key"] == "state_codes"
    business_id = created["business"]["id"]
    api.patch(
        f"{BUSINESSES}/{business_id}",
        json={
            "changes": [
                {"key": "state_codes", "value": ["29"]},
                {"key": "constitution", "value": "llp"},
                {"key": "business_category", "value": "other"},
                {
                    "key": "turnover_band",
                    "value": "upto_10_lakh",
                    "as_of_fy": created["onboarding"]["as_of_fy"],
                },
                {"key": "peak_turnover_band", "value": "upto_10_lakh"},
            ]
        },
        headers=AS_TENANT,
    )
    number = api.get(f"{BUSINESSES}/{business_id}/onboarding", headers=AS_TENANT).json()["next"]
    assert (number["key"], number["type"], number["min"], number["max"]) == (
        "employee_count",
        "integer",
        0,
        100000,
    )
    assert number["options"] == []


def test_add_a_registration_through_the_api(api: TestClient) -> None:
    created = create(api, {"name": "Acme", "gstin": GSTIN_KARNATAKA.value})
    business_id = created["business"]["id"]
    url = f"{BUSINESSES}/{business_id}/registrations"
    body = {"gstin": GSTIN_DELHI.value, "name": "Acme Delhi"}
    added = api.post(url, json=body, headers=keyed("registration-01"))
    assert added.status_code == 201, added.text
    payload = added.json()
    assert payload["created"] is True
    assert payload["registration"]["key"] == GSTIN_DELHI.value
    assert payload["registration"]["created"] is True
    assert [node["key"] for node in payload["business"]["registrations"]] == [
        GSTIN_KARNATAKA.value,
        GSTIN_DELHI.value,
    ]
    assert payload["prefill"]["applied"] == ["state_codes"]
    replay = api.post(url, json=body, headers=keyed("registration-01"))
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json() == payload
    assert api.post(url, json=body, headers=AS_TENANT).status_code == 428
    wrong = api.post(url, json={"gstin": GSTIN_OTHER_PAN.value}, headers=keyed())
    assert problem_type(wrong) == "profile-hierarchy-invalid"
    missing = api.post(f"{BUSINESSES}/{uuid4()}/registrations", json=body, headers=keyed())
    assert missing.status_code == 404


def test_every_business_route_is_public_and_lists_its_roles(api: TestClient) -> None:
    schema = api.get("/openapi.json").json()
    operations = [
        operation
        for path, item in schema["paths"].items()
        if path.startswith(BUSINESSES)
        for operation in item.values()
    ]
    assert len(operations) == 6
    for operation in operations:
        assert operation["tags"] == ["public", "businesses"]
        assert operation["x-roles"] == ["owner", "staff", "ca_admin", "ca_staff", "compliance_lead"]
