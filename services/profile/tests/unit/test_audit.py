"""The audit entries the profile's use cases write on the memory store: one per created node,
per save that changes values and per pre-fill that fills any, with only the changed values,
and none for a no-op or a failed unit of work."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
import structlog

from domain_kernel.access import Principal, Role
from domain_kernel.audit import AuditActor
from domain_kernel.errors import InvalidAttributeValueError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Pan
from domain_kernel.ids import BusinessId, UserId
from domain_kernel.ontology import Ontology
from ontology import load
from profile_service.application.attributes import SetAttributes
from profile_service.application.audit import (
    ATTRIBUTES_CHANGED,
    PREFILLED,
    REGISTERED,
    SUBJECT,
)
from profile_service.application.businesses import Answer, CreateBusiness, UpdateBusiness
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ValueState
from profile_service.infrastructure.lookup import DEMO_LOOKUPS, StaticLookupProvider
from profile_service.infrastructure.memory import MemoryStore
from profile_service.testing import GSTIN_KARNATAKA, PAN, TENANT, FixedFlags
from py_common.audit import CORRELATION_FIELD
from py_common.auth.context import principal_bound

AT = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
FY = FinancialYear(2000)
SYSTEM = AuditActor.system("profile")
USER = UserId.new()
REQUEST_ID = "0123456789abcdef0123456789abcdef"
LOOKUP = replace(DEMO_LOOKUPS[GSTIN_KARNATAKA.value], registered_since=date(2000, 7, 1))
"""A synthetic lookup answer; never a real registration."""


def clock() -> datetime:
    return AT


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return load()


def known(value: object, source: str = "user_input") -> dict[str, object]:
    return {"state": "known", "value": value, "source": source}


def entity_of(store: MemoryStore) -> BusinessId:
    return RegisterNodes(store, clock=clock).entity(TENANT, PAN, "Example Traders").node.id


def test_each_created_node_writes_one_registered_entry() -> None:
    store = MemoryStore()
    register = RegisterNodes(store, clock=clock)
    registration = register.registration(
        TENANT, GSTIN_KARNATAKA, "Example Bengaluru", entity_name="Example Traders"
    ).node
    entity_id = registration.parent_id
    assert entity_id is not None
    shop = register.location(TENANT, registration.id, "shop-1", "Example shop").node

    assert [(e.action, e.subject_id) for e in store.audit] == [
        (REGISTERED, str(entity_id)),
        (REGISTERED, str(registration.id)),
        (REGISTERED, str(shop.id)),
    ]
    assert [e.after for e in store.audit] == [
        {"level": "entity", "parent_id": None},
        {"level": "registration", "parent_id": str(entity_id)},
        {"level": "location", "parent_id": str(registration.id)},
    ]
    for entry in store.audit:
        assert (entry.tenant_id, entry.subject_type, entry.actor) == (TENANT, SUBJECT, SYSTEM)
        assert (entry.before, entry.reason, entry.occurred_at) == (None, "", AT)
        assert entry.correlation_id is None

    register.registration(TENANT, GSTIN_KARNATAKA, "Example again")
    register.entity(TENANT, PAN, "Example again")
    register.location(TENANT, registration.id, "shop-1", "Example shop again")
    assert len(store.audit) == 3, "a node that existed writes nothing"


def test_a_save_writes_only_the_changed_values(ontology: Ontology) -> None:
    store = MemoryStore()
    entity_id = entity_of(store)
    store.audit.clear()
    set_attributes = SetAttributes(store, ontology, clock=clock)
    set_attributes.run(
        TENANT,
        entity_id,
        [
            AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY),
            AttributeChange("employee_count", 7),
        ],
        source=ChangeSource.USER_INPUT,
    )
    set_attributes.run(
        TENANT,
        entity_id,
        [
            AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY),
            AttributeChange("employee_count", state=ValueState.UNSURE),
        ],
        source=ChangeSource.USER_INPUT,
    )

    first, second = store.audit
    assert (first.action, first.subject_id, first.tenant_id) == (
        ATTRIBUTES_CHANGED,
        str(entity_id),
        TENANT,
    )
    assert first.before == {"employee_count": None, "turnover_band@2000-01": None}
    assert first.after == {
        "employee_count": known(7),
        "turnover_band@2000-01": known("2_crore_to_5_crore"),
    }
    assert second.before == {"employee_count": known(7)}
    assert second.after == {
        "employee_count": {"state": "unsure", "value": None, "source": "user_input"}
    }
    assert (second.actor, second.reason, second.occurred_at) == (SYSTEM, "", AT)


def test_a_save_that_changes_nothing_writes_nothing(ontology: Ontology) -> None:
    store = MemoryStore()
    entity_id = entity_of(store)
    set_attributes = SetAttributes(store, ontology, clock=clock)
    change = [AttributeChange("employee_count", 7)]
    set_attributes.run(TENANT, entity_id, change, source=ChangeSource.USER_INPUT)
    count = len(store.audit)
    result = set_attributes.run(TENANT, entity_id, change, source=ChangeSource.USER_INPUT)
    assert result.changed == ()
    assert len(store.audit) == count


def test_a_failed_save_writes_nothing(ontology: Ontology) -> None:
    store = MemoryStore()
    create = CreateBusiness(
        store,
        ontology,
        PrefillFromGstin(store, StaticLookupProvider({}), ontology, FixedFlags(), clock=clock),
        clock=clock,
    )
    with pytest.raises(InvalidAttributeValueError):
        create.run(
            TENANT,
            name="Example Traders",
            gstin=GSTIN_KARNATAKA,
            answers=[
                Answer(AttributeChange("employee_count", 7)),
                Answer(AttributeChange("supply_type", "spaceships")),
            ],
        )
    assert store.audit == []
    assert store.nodes == {}


def test_a_business_update_writes_each_changed_node(ontology: Ontology) -> None:
    store = MemoryStore()
    prefill = PrefillFromGstin(store, StaticLookupProvider({}), ontology, FixedFlags(), clock=clock)
    business = CreateBusiness(store, ontology, prefill, clock=clock).run(
        TENANT, name="Example Traders", gstin=GSTIN_KARNATAKA
    )
    store.audit.clear()
    update = UpdateBusiness(store, ontology, clock=clock)
    update.run(
        TENANT,
        business.business.id,
        answers=[
            Answer(AttributeChange("employee_count", 7)),
            Answer(AttributeChange("registration_type", "regular")),
        ],
    )
    assert [(e.action, e.subject_id, dict(e.after or {})) for e in store.audit] == [
        (ATTRIBUTES_CHANGED, str(business.business.id), {"employee_count": known(7)}),
        (
            ATTRIBUTES_CHANGED,
            str(business.business.registrations[0].id),
            {"registration_type": known("regular")},
        ),
    ]
    store.audit.clear()
    update.run(TENANT, business.business.id, name="Example Renamed")
    assert store.audit == [], "a rename changes no attribute"


def test_the_prefill_writes_what_it_filled(ontology: Ontology) -> None:
    store = MemoryStore()
    registration = (
        RegisterNodes(store, clock=clock)
        .registration(TENANT, GSTIN_KARNATAKA, "Example Bengaluru")
        .node
    )
    entity_id = registration.parent_id
    assert entity_id is not None
    SetAttributes(store, ontology, clock=clock).run(
        TENANT,
        registration.id,
        [AttributeChange("gstin_status", "cancelled")],
        source=ChangeSource.USER_INPUT,
    )
    store.audit.clear()
    provider = StaticLookupProvider({GSTIN_KARNATAKA.value: LOOKUP})
    prefill = PrefillFromGstin(store, provider, ontology, FixedFlags(), clock=clock)
    prefill.run(TENANT, registration.id)

    on_entity, on_registration = store.audit
    assert (on_entity.action, on_entity.subject_id) == (PREFILLED, str(entity_id))
    assert on_entity.before == {"constitution": None, "state_codes": None}
    assert on_entity.after == {
        "constitution": known("private_limited", "gstin_lookup"),
        "state_codes": known(("29",), "derived"),
    }
    assert (on_registration.action, on_registration.subject_id) == (
        PREFILLED,
        str(registration.id),
    )
    assert on_registration.before == {
        "gstin_status": known("cancelled"),
        "registered_since": None,
        "registration_type": None,
    }
    assert on_registration.after == {
        "gstin_status": known("active", "gstin_lookup"),
        "registered_since": known("2000-07-01", "gstin_lookup"),
        "registration_type": known("regular", "gstin_lookup"),
    }

    store.audit.clear()
    prefill.run(TENANT, registration.id)
    assert store.audit == [], "a prefill that fills nothing writes nothing"


def test_the_entry_names_the_bound_principal_and_the_request(ontology: Ontology) -> None:
    store = MemoryStore()
    principal = Principal.user(USER, TENANT, [Role.OWNER])
    structlog.contextvars.bind_contextvars(**{CORRELATION_FIELD: REQUEST_ID})
    try:
        with principal_bound(principal):
            RegisterNodes(store, clock=clock).entity(TENANT, Pan("ZZZZZ9999Z"), "Example")
    finally:
        structlog.contextvars.unbind_contextvars(CORRELATION_FIELD)
    (entry,) = store.audit
    assert entry.actor == AuditActor.user(USER, [Role.OWNER])
    assert entry.correlation_id == REQUEST_ID
