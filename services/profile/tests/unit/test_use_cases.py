import pytest

import ontology as ontology_package
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Pan
from domain_kernel.ids import BusinessId
from domain_kernel.ontology import AttributeLevel, Ontology
from profile_service.application.attributes import (
    BuildSnapshot,
    ConfirmFinancialYear,
    NextQuestion,
    SetAttributes,
)
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import InvalidHierarchyError, ProfileNodeNotFoundError
from profile_service.domain.events import ChangeSource, ProfileUpdated
from profile_service.domain.model import AttributeChange, ReviewReason, ValueState
from profile_service.infrastructure.memory import MemoryStore
from profile_service.testing import GSTIN_DELHI, GSTIN_KARNATAKA, OTHER_TENANT, PAN, TENANT, clock

FY = FinancialYear(2025)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def test_registration_finds_or_creates_the_entity_from_the_gstin() -> None:
    store = MemoryStore()
    register = RegisterNodes(store, clock=clock)
    first = register.registration(TENANT, GSTIN_KARNATAKA, "Acme Bengaluru", entity_name="Acme")
    assert first.created
    entity = store.nodes[first.node.parent_id]  # type: ignore[index]
    assert (entity.level, entity.key, entity.name) == (AttributeLevel.ENTITY, PAN.value, "Acme")
    second = register.registration(TENANT, GSTIN_DELHI, "Acme Delhi")
    assert second.created
    assert second.node.parent_id == entity.id
    assert not register.registration(TENANT, GSTIN_KARNATAKA, "again").created
    assert not register.entity(TENANT, PAN, "Acme again").created
    assert register.entity(TENANT, Pan("ZZZZZ9999Z"), "Other").created
    shop = register.location(TENANT, first.node.id, "whitefield", "Whitefield store")
    assert shop.created
    assert not register.location(TENANT, first.node.id, "whitefield", "dup").created
    with pytest.raises(InvalidHierarchyError):
        register.location(TENANT, entity.id, "x", "x")
    with pytest.raises(ProfileNodeNotFoundError):
        register.location(TENANT, BusinessId.new(), "x", "x")
    assert len(store.nodes) == 5


def test_set_attributes_publishes_events_and_opens_reviews(ontology: Ontology) -> None:
    store = MemoryStore()
    registered = RegisterNodes(store, clock=clock).registration(TENANT, GSTIN_KARNATAKA, "Acme")
    entity_id = registered.node.parent_id
    assert entity_id is not None
    set_attributes = SetAttributes(store, ontology, clock=clock)
    result = set_attributes.run(
        TENANT,
        entity_id,
        [
            AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY),
            AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE),
        ],
        source=ChangeSource.USER_INPUT,
    )
    assert result.changed == ("turnover_band", "employee_count")
    assert len(result.review_tasks) == 1
    (event,) = store.events
    assert isinstance(event, ProfileUpdated)
    assert event.business_id == entity_id
    assert event.profile_version == 2
    (task,) = store.tasks.values()
    assert task.reason is ReviewReason.NOT_APPLICABLE
    assert task.attribute_key == "employee_count"
    (case,) = store.eval_cases
    assert case["kind"] == "profile.not_applicable"
    assert case["attribute"] == "employee_count"
    assert case["known_attributes"] == {}
    again = set_attributes.run(
        TENANT,
        entity_id,
        [AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY)],
        source=ChangeSource.USER_INPUT,
    )
    assert again.changed == ()
    assert len(store.events) == 1
    with pytest.raises(ProfileNodeNotFoundError):
        set_attributes.run(OTHER_TENANT, entity_id, [], source=ChangeSource.IMPORT)


def test_snapshot_and_next_question_through_the_use_cases(ontology: Ontology) -> None:
    store = MemoryStore()
    registered = RegisterNodes(store, clock=clock).registration(TENANT, GSTIN_KARNATAKA, "Acme")
    entity_id, registration_id = registered.node.parent_id, registered.node.id
    assert entity_id is not None
    SetAttributes(store, ontology, clock=clock).run(
        TENANT,
        entity_id,
        [
            AttributeChange("state_codes", ["29"]),
            AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FY),
        ],
        source=ChangeSource.GSTIN_LOOKUP,
    )
    SetAttributes(store, ontology, clock=clock).run(
        TENANT,
        registration_id,
        [AttributeChange("registration_type", "regular")],
        source=ChangeSource.GSTIN_LOOKUP,
    )
    snapshot = BuildSnapshot(store).run(TENANT, registration_id, as_of_fy=FY)
    assert snapshot.attributes == {
        "state_codes": frozenset({"29"}),
        "turnover_band": "upto_10_lakh",
        "registration_type": "regular",
    }
    assert snapshot.lineage == (entity_id,)
    assert NextQuestion(store, ontology).run(TENANT, registration_id, as_of_fy=FY) == "gstin_status"
    assert NextQuestion(store, ontology).run(TENANT, entity_id, as_of_fy=FY) == "constitution"
    with pytest.raises(ProfileNodeNotFoundError):
        BuildSnapshot(store).run(OTHER_TENANT, registration_id, as_of_fy=FY)


def test_confirm_financial_year_opens_one_task_per_entity_and_attribute(ontology: Ontology) -> None:
    store = MemoryStore()
    register = RegisterNodes(store, clock=clock)
    acme = register.entity(TENANT, PAN, "Acme").node
    other = register.entity(TENANT, Pan("ZZZZZ9999Z"), "Other").node
    SetAttributes(store, ontology, clock=clock).run(
        TENANT,
        acme.id,
        [AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FY.next())],
        source=ChangeSource.USER_INPUT,
    )
    confirm = ConfirmFinancialYear(store, ontology, clock=clock)
    opened = confirm.run(TENANT, FY.next())
    assert len(opened) == 1
    (task,) = [t for t in store.tasks.values() if t.node_id == other.id]
    assert task.reason is ReviewReason.CONFIRM_FINANCIAL_YEAR
    assert task.as_of_fy == FY.next()
    assert confirm.run(TENANT, FY.next()) == ()
    assert len(confirm.run(TENANT, FinancialYear(2030))) == 2
