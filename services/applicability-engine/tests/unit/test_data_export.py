"""The tenant's data export: on the memory store, every decision and review item of the asked
tenant only, each section present and oldest first, read a page at a time; then
``GET /v1/applicability-engine/data-export`` over HTTP in header and token mode."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from applicability_engine.application.export import (
    DECISIONS,
    REVIEW_ITEMS,
    SECTIONS,
    ExportTenantData,
)
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.review import Resolution, ReviewItem, ReviewReason
from applicability_engine.infrastructure.memory import MemoryStore
from applicability_engine.main import build_app
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import MemoryProfiles, MemoryRulebook
from applicability_engine.wiring import Readers
from domain_kernel.access import Role, Scope
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId, UserId
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

FIRST = TenantId.new()
SECOND = TenantId.new()
VERSION = RuleVersionId.new()
START = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)
GENERATED = datetime(2000, 6, 1, 12, 0, tzinfo=UTC)
REGULAR = Predicate("registration_type", Operator.EQ, "regular")
FREE_TEXT = Predicate("business_category", free_text="Example premises shared with a hotel")
EXPORT = "/v1/applicability-engine/data-export"
ISSUER = TestIssuer()


def decide(
    store: MemoryStore,
    tenant: TenantId,
    business: BusinessId,
    result: Applicability,
    *,
    minutes: int,
    trigger: Trigger = Trigger.PROFILE_UPDATED,
) -> Decision:
    unsure = result is Applicability.UNSURE
    decision = Decision(
        decision_id=DecisionId.new(),
        tenant_id=tenant,
        business_id=business,
        rule_version_id=VERSION,
        result=result,
        confidence=ZERO if unsure else CERTAIN,
        evaluated=(
            PredicateResult(
                FREE_TEXT if unsure else REGULAR,
                result,
                ZERO if unsure else CERTAIN,
                "nobody judged it" if unsure else "registration_type = regular holds",
            ),
        ),
        profile_version=1,
        decided_at=START + timedelta(minutes=minutes),
        trigger=trigger,
        as_of_fy=FinancialYear.parse("2000-01"),
    )
    with store(tenant) as uow:
        uow.decisions.add(decision)
    return decision


class Tenants:
    """The first tenant: a business decided unsure (opening a review item), then by a reviewer,
    and a second business decided once; the second tenant: one decision and its open item."""

    def __init__(self, store: MemoryStore) -> None:
        business, other = BusinessId.new(), BusinessId.new()
        self.unsure = decide(store, FIRST, business, Applicability.UNSURE, minutes=0)
        self.reviewed = decide(
            store, FIRST, business, Applicability.APPLIES, minutes=5, trigger=Trigger.REVIEW
        )
        self.later = decide(store, FIRST, other, Applicability.NOT_APPLICABLE, minutes=10)
        self.item = ReviewItem.open(self.unsure, ReviewReason.FREE_TEXT).resolve(
            Resolution.APPLIES,
            by=UserId.new(),
            at=START + timedelta(minutes=5),
            note="Example note: the premises are the business's own",
            decision_id=self.reviewed.decision_id,
        )
        with store(FIRST) as uow:
            uow.reviews.add(ReviewItem.open(self.unsure, ReviewReason.FREE_TEXT))
        with store(FIRST) as uow:
            uow.reviews.save(self.item)
        self.foreign = decide(store, SECOND, BusinessId.new(), Applicability.UNSURE, minutes=1)
        with store(SECOND) as uow:
            uow.reviews.add(ReviewItem.open(self.foreign, ReviewReason.FREE_TEXT))


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def test_the_export_holds_the_tenants_rows_only(store: MemoryStore) -> None:
    tenants = Tenants(store)
    export = ExportTenantData(store, clock=lambda: GENERATED).run(FIRST)
    assert (export.service, export.tenant_id, export.generated_at) == (
        "applicability-engine",
        FIRST,
        GENERATED,
    )
    assert tuple(export.sections) == SECTIONS
    decisions = export.sections[DECISIONS]
    assert [row["decision_id"] for row in decisions] == [
        str(tenants.unsure.decision_id),
        str(tenants.reviewed.decision_id),
        str(tenants.later.decision_id),
    ]
    first = decisions[0]
    assert first == {
        "decision_id": str(tenants.unsure.decision_id),
        "tenant_id": str(FIRST),
        "business_id": str(tenants.unsure.business_id),
        "rule_version_id": str(VERSION),
        "result": "unsure",
        "confidence": 0.0,
        "needs_review": True,
        "evaluated": [
            {
                "predicate": {
                    "attribute": "business_category",
                    "free_text": "Example premises shared with a hotel",
                },
                "outcome": "unsure",
                "confidence": 0.0,
                "reason": "nobody judged it",
            }
        ],
        "profile_version": 1,
        "decided_at": "2000-04-01T09:00:00+00:00",
        "trigger": "profile_updated",
        "trigger_ref": None,
        "as_of_fy": "2000-01",
    }
    (item,) = export.sections[REVIEW_ITEMS]
    assert item == {
        "item_id": str(tenants.item.item_id),
        "tenant_id": str(FIRST),
        "business_id": str(tenants.unsure.business_id),
        "rule_version_id": str(VERSION),
        "decision_id": str(tenants.unsure.decision_id),
        "reason": "free_text",
        "opened_at": "2000-04-01T09:00:00+00:00",
        "status": "resolved",
        "resolution": "applies",
        "resolved_by": str(tenants.item.resolved_by),
        "resolved_at": "2000-04-01T09:05:00+00:00",
        "note": "Example note: the premises are the business's own",
        "resolution_decision_id": str(tenants.reviewed.decision_id),
    }
    assert str(SECOND) not in repr(export.sections)


def test_every_section_is_present_when_the_tenant_has_nothing(store: MemoryStore) -> None:
    Tenants(store)
    export = ExportTenantData(store).run(TenantId.new())
    assert export.sections == {DECISIONS: [], REVIEW_ITEMS: []}
    assert export.generated_at.tzinfo is not None


def test_the_sections_are_read_a_page_at_a_time(store: MemoryStore) -> None:
    decided = [
        decide(store, FIRST, BusinessId.new(), Applicability.UNSURE, minutes=minute % 3)
        for minute in range(7)
    ]
    with store(FIRST) as uow:
        for decision in decided:
            uow.reviews.add(ReviewItem.open(decision, ReviewReason.FREE_TEXT))
    decide(store, SECOND, BusinessId.new(), Applicability.APPLIES, minutes=0)
    whole = ExportTenantData(store).run(FIRST)
    paged = ExportTenantData(store, page_size=2).run(FIRST)
    assert paged.sections == whole.sections
    expected = sorted(
        decided, key=lambda decision: (decision.decided_at, decision.decision_id.value)
    )
    assert [row["decision_id"] for row in paged.sections[DECISIONS]] == [
        str(decision.decision_id) for decision in expected
    ]
    assert len(paged.sections[REVIEW_ITEMS]) == 7
    assert len({row["item_id"] for row in paged.sections[REVIEW_ITEMS]}) == 7
    exact = ExportTenantData(store, page_size=7).run(FIRST)
    assert exact.sections == whole.sections


def test_a_page_size_below_one_is_refused(store: MemoryStore) -> None:
    with pytest.raises(ValueError, match="page_size"):
        ExportTenantData(store, page_size=0)


# ---------------------------------------------------------------- over HTTP


def app_in(mode: AuthMode) -> Iterator[tuple[TestClient, MemoryStore]]:
    settings = ApplicabilityEngineSettings(
        _env_file=None,
        service_name="applicability-engine",
        applicability_engine_store="memory",
        **ISSUER.settings_overrides(mode),
    )
    readers = Readers(profiles=MemoryProfiles(), rulebook=MemoryRulebook())
    with TestClient(build_app(settings, readers=readers)) as client:
        store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
        assert isinstance(store, MemoryStore)
        yield client, store


@pytest.fixture
def header_mode() -> Iterator[tuple[TestClient, MemoryStore]]:
    yield from app_in("header")


@pytest.fixture
def token_mode() -> Iterator[tuple[TestClient, MemoryStore]]:
    yield from app_in("token")


def test_header_mode_exports_the_named_tenant(header_mode: tuple[TestClient, MemoryStore]) -> None:
    client, store = header_mode
    tenants = Tenants(store)
    response = client.get(EXPORT, headers={"x-tenant-id": str(FIRST)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"service", "tenant_id", "generated_at", "sections"}
    assert (body["service"], body["tenant_id"]) == ("applicability-engine", str(FIRST))
    assert datetime.fromisoformat(body["generated_at"]).tzinfo is not None
    assert set(body["sections"]) == {"decisions", "review_items"}
    assert [row["decision_id"] for row in body["sections"]["decisions"]] == [
        str(tenants.unsure.decision_id),
        str(tenants.reviewed.decision_id),
        str(tenants.later.decision_id),
    ]
    assert [row["item_id"] for row in body["sections"]["review_items"]] == [
        str(tenants.item.item_id)
    ]
    assert str(SECOND) not in response.text


def test_header_mode_needs_a_tenant(header_mode: tuple[TestClient, MemoryStore]) -> None:
    client, _ = header_mode
    missing = client.get(EXPORT)
    assert missing.status_code == 401
    assert missing.json()["type"].endswith(":applicability-tenant-required")


def test_token_mode_serves_the_tenant_admins_and_the_exporting_service(
    token_mode: tuple[TestClient, MemoryStore],
) -> None:
    client, store = token_mode
    Tenants(store)
    owner = bearer(ISSUER.user(FIRST, [Role.OWNER]))
    ca_admin = bearer(ISSUER.user(FIRST, [Role.CA_ADMIN], mfa=True))
    for headers in (owner, ca_admin):
        response = client.get(EXPORT, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["tenant_id"] == str(FIRST)
        assert len(response.json()["sections"]["decisions"]) == 3
    staff = bearer(ISSUER.user(FIRST, [Role.STAFF]))
    assert client.get(EXPORT, headers=staff).status_code == 403
    exporting = bearer(
        ISSUER.service(
            "identity", [Scope.DATA_EXPORT], acts_for=SECOND, audience="applicability-engine"
        )
    )
    acting = client.get(EXPORT, headers={**exporting, "x-tenant-id": str(SECOND)})
    assert acting.status_code == 200, acting.text
    assert acting.json()["tenant_id"] == str(SECOND)
    assert len(acting.json()["sections"]["review_items"]) == 1
    replayed = client.get(EXPORT, headers={**exporting, "x-tenant-id": str(FIRST)})
    assert replayed.status_code == 403, "a token bound to one tenant never reads another"
    elsewhere = bearer(
        ISSUER.service("identity", [Scope.DATA_EXPORT], acts_for=SECOND, audience="profile")
    )
    assert client.get(EXPORT, headers={**elsewhere, "x-tenant-id": str(SECOND)}).status_code == 403
    unbound = bearer(ISSUER.service("worker", [Scope.DATA_EXPORT, Scope.TENANT_ACT]))
    assert client.get(EXPORT, headers={**unbound, "x-tenant-id": str(FIRST)}).status_code == 403
    plain = bearer(ISSUER.service("identity", [Scope.TENANT_ACT]))
    assert client.get(EXPORT, headers={**plain, "x-tenant-id": str(FIRST)}).status_code == 403
    mismatch = client.get(EXPORT, headers={**owner, "x-tenant-id": str(SECOND)})
    assert mismatch.status_code == 403
    assert client.get(EXPORT).status_code == 401
