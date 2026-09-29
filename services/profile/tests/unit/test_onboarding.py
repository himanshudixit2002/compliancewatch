"""The onboarding checklist: order, per-year keys, derived attributes and completeness; and the
use case that asks it for the financial year of today in IST."""

from datetime import UTC, datetime, timedelta

import pytest

import ontology as ontology_package
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Gstin
from domain_kernel.ids import BusinessId
from domain_kernel.ontology import AttributeLevel, AttributeSource, Ontology
from profile_service.application.onboarding import OnboardingChecklist
from profile_service.application.registration import RegisterNodes
from profile_service.domain.errors import (
    InvalidHierarchyError,
    NotABusinessError,
    ProfileNodeNotFoundError,
)
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ProfileNode, ValueState
from profile_service.domain.onboarding import ItemState, build_checklist
from profile_service.infrastructure.memory import MemoryStore
from profile_service.testing import GSTIN_DELHI, GSTIN_KARNATAKA, NOW, PAN, TENANT

FY = FinancialYear(2026)
SMALL = Ontology.from_mapping(
    {
        "version": "1.0.0",
        "attributes": [
            {
                "key": "constitution",
                "type": "enum",
                "source": "gstin_lookup",
                "level": "entity",
                "definition": "Legal form.",
                "allowed_values": ["llp", "huf"],
            },
            {
                "key": "size_class",
                "type": "enum",
                "source": "derived",
                "level": "entity",
                "definition": "Computed from the turnover.",
                "allowed_values": ["small", "large"],
            },
            {
                "key": "turnover_band",
                "type": "ordered_enum",
                "source": "user_input",
                "level": "entity",
                "per_financial_year": True,
                "definition": "Turnover of the year.",
                "allowed_values": ["low", "high"],
            },
            {
                "key": "supply_type",
                "type": "enum",
                "source": "user_input",
                "level": "registration",
                "definition": "Goods or services.",
                "allowed_values": ["goods", "services"],
            },
        ],
    }
)
"""A made-up ontology with a derived attribute, which the packaged one does not have yet."""


def business() -> tuple[ProfileNode, ProfileNode, ProfileNode]:
    entity = ProfileNode.entity(tenant_id=TENANT, pan=PAN, name="Acme", at=NOW)
    first = ProfileNode.registration(
        tenant_id=TENANT, entity=entity, gstin=GSTIN_KARNATAKA, name="Bengaluru", at=NOW
    )
    later = ProfileNode.registration(
        tenant_id=TENANT,
        entity=entity,
        gstin=GSTIN_DELHI,
        name="Delhi",
        at=NOW + timedelta(minutes=1),
    )
    return entity, first, later


def answer(node: ProfileNode, *changes: AttributeChange) -> ProfileNode:
    return node.apply(changes, ontology=SMALL, source=ChangeSource.USER_INPUT, at=NOW).node


def test_the_entity_comes_first_then_registrations_by_creation_in_ontology_order() -> None:
    entity, first, later = business()
    checklist = build_checklist(entity, [later, first], SMALL, FY)
    assert [(item.node_id, item.key) for item in checklist.items] == [
        (entity.id, "constitution"),
        (entity.id, "turnover_band"),
        (first.id, "supply_type"),
        (later.id, "supply_type"),
    ]
    assert all(item.state is ItemState.MISSING for item in checklist.items)
    assert all(item.source is None for item in checklist.items)
    assert checklist.next == checklist.items[0]
    assert (checklist.answered, checklist.total, checklist.complete) == (0, 4, False)


def test_a_derived_attribute_is_never_asked() -> None:
    entity, first, _ = business()
    keys = {item.key for item in build_checklist(entity, [first], SMALL, FY).items}
    assert "size_class" not in keys


def test_a_per_year_attribute_is_answered_for_its_year_only() -> None:
    entity, _, _ = business()
    entity = answer(entity, AttributeChange("turnover_band", "low", as_of_fy=FY))
    this_year = build_checklist(entity, [], SMALL, FY)
    next_year = build_checklist(entity, [], SMALL, FY.next())
    [item] = [item for item in this_year.items if item.key == "turnover_band"]
    assert (item.state, item.per_financial_year, item.source) == (
        ItemState.KNOWN,
        True,
        AttributeSource.USER_INPUT,
    )
    assert [i.state for i in next_year.items if i.key == "turnover_band"] == [ItemState.MISSING]


def test_an_unsure_answer_is_asked_again_and_not_applicable_counts_as_answered() -> None:
    entity, first, _ = business()
    entity = answer(
        entity,
        AttributeChange("constitution", state=ValueState.NOT_APPLICABLE),
        AttributeChange("turnover_band", state=ValueState.UNSURE, as_of_fy=FY),
    )
    checklist = build_checklist(entity, [first], SMALL, FY)
    assert checklist.next is not None
    assert (checklist.next.key, checklist.next.state) == ("turnover_band", ItemState.UNSURE)
    assert checklist.answered == 1


def test_every_question_answered_completes_the_checklist() -> None:
    entity, first, _ = business()
    entity = answer(
        entity,
        AttributeChange("constitution", "llp"),
        AttributeChange("turnover_band", "high", as_of_fy=FY),
    )
    first = answer(first, AttributeChange("supply_type", "goods"))
    checklist = build_checklist(entity, [first], SMALL, FY)
    assert checklist.next is None
    assert (checklist.answered, checklist.total, checklist.complete) == (2 + 1, 3, True)


def test_the_packaged_ontology_asks_every_attribute_once() -> None:
    ontology = ontology_package.load()
    entity, first, _ = business()
    checklist = build_checklist(entity, [first], ontology, FY)
    assert checklist.total == len(ontology)
    assert {item.level for item in checklist.items} == {
        AttributeLevel.ENTITY,
        AttributeLevel.REGISTRATION,
    }


def test_the_checklist_refuses_a_broken_hierarchy() -> None:
    _, first, _ = business()
    other = ProfileNode.entity(
        tenant_id=TENANT, pan=Gstin("29ZZZZZ9999Z1Z5").pan, name="Other", at=NOW
    )
    with pytest.raises(InvalidHierarchyError, match="starts at the legal entity"):
        build_checklist(first, [], SMALL, FY)
    with pytest.raises(InvalidHierarchyError, match="is not a registration of entity"):
        build_checklist(other, [first], SMALL, FY)


@pytest.mark.parametrize(
    ("now", "label"),
    [
        (datetime(2027, 3, 31, 18, 29, tzinfo=UTC), "2026-27"),
        (datetime(2027, 3, 31, 18, 30, tzinfo=UTC), "2027-28"),
    ],
    ids=["last-minute-of-march-ist", "first-minute-of-april-ist"],
)
def test_the_use_case_asks_for_the_financial_year_of_today_in_ist(
    now: datetime, label: str
) -> None:
    store = MemoryStore()
    registered = RegisterNodes(store).registration(TENANT, GSTIN_KARNATAKA, "Acme")
    entity_id = registered.node.parent_id
    assert entity_id is not None
    checklist = OnboardingChecklist(store, ontology_package.load(), clock=lambda: now).run(
        TENANT, entity_id
    )
    assert checklist.as_of_fy.label == label
    with pytest.raises(NotABusinessError):
        OnboardingChecklist(store, ontology_package.load()).run(TENANT, registered.node.id)
    with pytest.raises(ProfileNodeNotFoundError):
        OnboardingChecklist(store, ontology_package.load()).run(TENANT, BusinessId.new())
