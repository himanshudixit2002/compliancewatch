from datetime import timedelta

import pytest

import ontology as ontology_package
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Gstin
from domain_kernel.ids import BusinessId
from domain_kernel.ontology import AttributeLevel, AttributeSource, Ontology
from profile_service.domain.errors import (
    AttributeLevelMismatchError,
    FinancialYearRequiredError,
    InvalidHierarchyError,
)
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import (
    AttributeChange,
    AttributeRecord,
    ProfileNode,
    ReviewReason,
    ValueState,
)
from profile_service.testing import GSTIN_KARNATAKA, NOW, OTHER_TENANT, PAN, TENANT

FY = FinancialYear(2025)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def entity() -> ProfileNode:
    return ProfileNode.entity(tenant_id=TENANT, pan=PAN, name="Acme Traders", at=NOW)


def registration(parent: ProfileNode) -> ProfileNode:
    return ProfileNode.registration(
        tenant_id=TENANT, entity=parent, gstin=GSTIN_KARNATAKA, name="Acme Bengaluru", at=NOW
    )


def test_hierarchy_construction_and_checks() -> None:
    root = entity()
    branch = registration(root)
    shop = ProfileNode.location(
        tenant_id=TENANT, registration=branch, label="whitefield", name="Whitefield store", at=NOW
    )
    assert (root.level, branch.level, shop.level) == (
        AttributeLevel.ENTITY,
        AttributeLevel.REGISTRATION,
        AttributeLevel.LOCATION,
    )
    assert branch.parent_id == root.id
    assert shop.parent_id == branch.id
    with pytest.raises(InvalidHierarchyError, match="carries PAN"):
        ProfileNode.registration(
            tenant_id=TENANT, entity=root, gstin=Gstin("29ZZZZZ9999Z1Z5"), name="x", at=NOW
        )
    with pytest.raises(InvalidHierarchyError, match="same tenant"):
        ProfileNode.registration(
            tenant_id=OTHER_TENANT, entity=root, gstin=GSTIN_KARNATAKA, name="x", at=NOW
        )
    with pytest.raises(InvalidHierarchyError, match="belongs to a registration"):
        ProfileNode.location(tenant_id=TENANT, registration=root, label="a", name="x", at=NOW)
    with pytest.raises(InvalidHierarchyError, match="exactly one"):
        ProfileNode(
            id=BusinessId.new(),
            tenant_id=TENANT,
            level=AttributeLevel.REGISTRATION,
            key=GSTIN_KARNATAKA.value,
            name="x",
            parent_id=None,
            version=1,
            created_at=NOW,
            updated_at=NOW,
        )
    with pytest.raises(InvariantViolationError, match="pan"):
        ProfileNode.entity(tenant_id=TENANT, pan=PAN, name="x", at=NOW).__class__(
            id=BusinessId.new(),
            tenant_id=TENANT,
            level=AttributeLevel.ENTITY,
            key="not-a-pan",
            name="x",
            parent_id=None,
            version=1,
            created_at=NOW,
            updated_at=NOW,
        )


def test_apply_stores_values_bumps_the_version_and_emits_one_event(ontology: Ontology) -> None:
    root = entity()
    outcome = root.apply(
        [
            AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY),
            AttributeChange("state_codes", ["29", "07"], source=AttributeSource.GSTIN_LOOKUP),
            AttributeChange("constitution", state=ValueState.UNSURE),
        ],
        ontology=ontology,
        source=ChangeSource.USER_INPUT,
        at=NOW,
    )
    node, event = outcome.node, outcome.event
    assert node.version == 2
    assert event is not None
    assert event.changed_attributes == ("turnover_band", "state_codes", "constitution")
    assert event.profile_version == 2
    assert event.ontology_version == ontology.version
    assert event.source is ChangeSource.USER_INPUT
    record = node.value("turnover_band", FY)
    assert record is not None
    assert record.value == "2_crore_to_5_crore"
    assert node.value("state_codes") is not None
    assert node.value("state_codes").value == frozenset({"29", "07"})  # type: ignore[union-attr]
    assert node.value("constitution").state is ValueState.UNSURE  # type: ignore[union-attr]
    assert outcome.reviews == ()


def test_apply_is_a_no_op_for_unchanged_values(ontology: Ontology) -> None:
    root = (
        entity()
        .apply(
            [AttributeChange("employee_count", 12)],
            ontology=ontology,
            source=ChangeSource.IMPORT,
            at=NOW,
        )
        .node
    )
    again = root.apply(
        [AttributeChange("employee_count", 12)],
        ontology=ontology,
        source=ChangeSource.IMPORT,
        at=NOW,
    )
    assert again.event is None
    assert again.node.version == root.version


def test_not_applicable_opens_a_review_request(ontology: Ontology) -> None:
    outcome = entity().apply(
        [AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE)],
        ontology=ontology,
        source=ChangeSource.USER_INPUT,
        at=NOW,
    )
    (request,) = outcome.reviews
    assert request.reason is ReviewReason.NOT_APPLICABLE
    assert request.attribute_key == "employee_count"


def test_ontology_rules_apply(ontology: Ontology) -> None:
    root = entity()
    with pytest.raises(AttributeLevelMismatchError, match="registration"):
        root.apply(
            [AttributeChange("registration_type", "regular")],
            ontology=ontology,
            source=ChangeSource.USER_INPUT,
            at=NOW,
        )
    with pytest.raises(FinancialYearRequiredError):
        root.apply(
            [AttributeChange("turnover_band", "upto_10_lakh")],
            ontology=ontology,
            source=ChangeSource.USER_INPUT,
            at=NOW,
        )
    with pytest.raises(InvariantViolationError, match="drop as_of_fy"):
        root.apply(
            [AttributeChange("employee_count", 1, as_of_fy=FY)],
            ontology=ontology,
            source=ChangeSource.USER_INPUT,
            at=NOW,
        )
    with pytest.raises(Exception, match="turnover_band"):
        root.apply(
            [AttributeChange("turnover_band", "nonsense", as_of_fy=FY)],
            ontology=ontology,
            source=ChangeSource.USER_INPUT,
            at=NOW,
        )


def test_snapshot_inherits_downward_and_picks_the_year(ontology: Ontology) -> None:
    root = (
        entity()
        .apply(
            [
                AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY),
                AttributeChange("turnover_band", "5_crore_to_10_crore", as_of_fy=FY.next()),
                AttributeChange("state_codes", ["29"]),
                AttributeChange("employee_count", state=ValueState.UNSURE),
            ],
            ontology=ontology,
            source=ChangeSource.USER_INPUT,
            at=NOW,
        )
        .node
    )
    branch = (
        registration(root)
        .apply(
            [
                AttributeChange("registration_type", "regular"),
                AttributeChange("filing_scheme", "regular_qrmp"),
            ],
            ontology=ontology,
            source=ChangeSource.GSTIN_LOOKUP,
            at=NOW + timedelta(minutes=1),
        )
        .node
    )
    snapshot = branch.snapshot([root], as_of_fy=FY)
    assert snapshot.attributes == {
        "turnover_band": "2_crore_to_5_crore",
        "state_codes": frozenset({"29"}),
        "registration_type": "regular",
        "filing_scheme": "regular_qrmp",
    }
    assert snapshot.level is AttributeLevel.REGISTRATION
    assert snapshot.lineage == (root.id,)
    assert snapshot.as_of_fy == FY
    assert snapshot.version == 2
    next_year = branch.snapshot([root], as_of_fy=FY.next())
    assert next_year.attributes["turnover_band"] == "5_crore_to_10_crore"
    assert "turnover_band" not in branch.snapshot([root], as_of_fy=FinancialYear(2030)).attributes
    with pytest.raises(InvalidHierarchyError, match="lineage"):
        branch.snapshot([], as_of_fy=FY)


def test_next_question_and_missing_for_year(ontology: Ontology) -> None:
    root = entity()
    assert root.next_question(ontology, as_of_fy=FY) == "state_codes"
    filled = root.apply(
        [
            AttributeChange("state_codes", ["29"]),
            AttributeChange("constitution", "proprietorship"),
            AttributeChange("business_category", state=ValueState.UNSURE),
        ],
        ontology=ontology,
        source=ChangeSource.USER_INPUT,
        at=NOW,
    ).node
    assert filled.next_question(ontology, as_of_fy=FY) == "business_category"
    assert filled.missing_for_year(ontology, FY) == ("turnover_band",)
    with_turnover = filled.apply(
        [AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FY)],
        ontology=ontology,
        source=ChangeSource.USER_INPUT,
        at=NOW,
    ).node
    assert with_turnover.missing_for_year(ontology, FY) == ()
    assert with_turnover.missing_for_year(ontology, FY.next()) == ("turnover_band",)
    assert with_turnover.next_question(ontology, as_of_fy=FY.next()) == "business_category"


def test_attribute_record_invariants() -> None:
    with pytest.raises(InvariantViolationError, match="cannot be None"):
        AttributeRecord("k", ValueState.KNOWN)
    with pytest.raises(InvariantViolationError, match="only a known value"):
        AttributeRecord("k", ValueState.UNSURE, value=1)
    with pytest.raises(InvariantViolationError, match="cannot be None"):
        AttributeChange("k")
