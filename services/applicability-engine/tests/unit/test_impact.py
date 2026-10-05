"""The impact of a change on the memory store: each business's latest decision of a version,
under the client the directory places it, the counts, the result filter, the pages and the fan-out
run; then ``GET /v1/changes/{rule_version_id}/impact`` over HTTP, for the caller's tenant only,
in header and token mode."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from applicability_engine.application.fanout_runs import BeginFanOut
from applicability_engine.application.impact import ReadChangeImpact
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.fanout import FanOutStart
from applicability_engine.domain.impact import ImpactEntry, ImpactQuery, grouped
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory, MemoryStore
from applicability_engine.main import build_app
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import NOW, MemoryProfiles, MemoryRulebook
from applicability_engine.wiring import Readers
from domain_kernel.access import Role, Scope
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, DecisionId, EventId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

APPLIES, NOT_APPLICABLE, UNSURE = (
    Applicability.APPLIES,
    Applicability.NOT_APPLICABLE,
    Applicability.UNSURE,
)
REGULAR = Predicate("registration_type", Operator.EQ, "regular")
FIRM = TenantId.new()
OTHER = TenantId.new()
VERSION = RuleVersionId.new()
ISSUER = TestIssuer()


def ordered_ids(count: int) -> list[BusinessId]:
    return sorted((BusinessId.new() for _ in range(count)), key=lambda business: business.value)


def decide(
    store: MemoryStore,
    tenant: TenantId,
    business: BusinessId,
    result: Applicability,
    *,
    minutes: int = 0,
    version: RuleVersionId = VERSION,
) -> Decision:
    decision = Decision(
        decision_id=DecisionId.new(),
        tenant_id=tenant,
        business_id=business,
        rule_version_id=version,
        result=result,
        confidence=ZERO if result is UNSURE else CERTAIN,
        evaluated=(
            PredicateResult(
                REGULAR,
                result,
                ZERO if result is UNSURE else CERTAIN,
                "registration_type = regular holds",
            ),
        ),
        profile_version=1,
        decided_at=NOW + timedelta(minutes=minutes),
        trigger=Trigger.RULE_PUBLISHED,
        as_of_fy=None,
    )
    with store(tenant) as uow:
        uow.decisions.add(decision)
    return decision


def place(
    store: MemoryStore, tenant: TenantId, entity: BusinessId, *registrations: BusinessId
) -> None:
    with store(tenant) as uow:
        uow.directory.add(DirectoryEntry(tenant, entity, AttributeLevel.ENTITY, None, entity))
        for registration in registrations:
            uow.directory.add(
                DirectoryEntry(tenant, registration, AttributeLevel.REGISTRATION, entity, entity)
            )


class Firm:
    """A CA firm's clients: two entities with two registrations and one with one, every
    registration decided, one of them twice, and the other tenant's own decision."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.entities = ordered_ids(3)
        one, two, three = self.entities
        self.registrations = {entity: ordered_ids(2) for entity in (one, two)}
        self.registrations[three] = ordered_ids(1)
        for entity, registrations in self.registrations.items():
            place(store, FIRM, entity, *registrations)
        self.first = decide(store, FIRM, self.registrations[one][0], UNSURE, minutes=1)
        self.latest = decide(store, FIRM, self.registrations[one][0], APPLIES, minutes=2)
        decide(store, FIRM, self.registrations[one][1], NOT_APPLICABLE)
        decide(store, FIRM, self.registrations[two][0], NOT_APPLICABLE)
        decide(store, FIRM, self.registrations[two][1], UNSURE)
        decide(store, FIRM, self.registrations[three][0], APPLIES)
        decide(
            store, FIRM, self.registrations[three][0], NOT_APPLICABLE, version=RuleVersionId.new()
        )
        self.unlisted = decide(store, FIRM, BusinessId.new(), APPLIES)
        decide(store, OTHER, BusinessId.new(), APPLIES)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def test_each_business_has_its_latest_decision_under_its_client(store: MemoryStore) -> None:
    firm = Firm(store)
    impact = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(tenant_id=FIRM, rule_version_id=VERSION, limit=50)
    )
    one, two, three = firm.entities
    placed = {group.entity_id: group for group in impact.groups}
    assert set(placed) == {one, two, three, firm.unlisted.business_id}
    assert [group.entity_id.value for group in impact.groups] == sorted(
        entity.value for entity in placed
    )
    first = placed[one]
    assert [entry.business_id for entry in first.entries] == firm.registrations[one]
    assert first.entries[0].decision == firm.latest, "the newer decision of the business"
    assert {entry.level for entry in first.entries} == {AttributeLevel.REGISTRATION}
    (unlisted,) = placed[firm.unlisted.business_id].entries
    assert (unlisted.level, unlisted.entity_id) == (None, firm.unlisted.business_id)
    assert impact.counts == {APPLIES: 3, NOT_APPLICABLE: 2, UNSURE: 1}
    assert impact.fan_out is None


def test_the_filter_keeps_the_affected_clients_and_the_counts_stay_whole(
    store: MemoryStore,
) -> None:
    firm = Firm(store)
    impact = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(tenant_id=FIRM, rule_version_id=VERSION, limit=50, result=APPLIES)
    )
    one, two, _ = firm.entities
    assert two not in {group.entity_id for group in impact.groups}, "no registration applies"
    affected = {group.entity_id: group.entries for group in impact.groups}
    assert [entry.business_id for entry in affected[one]] == [firm.registrations[one][0]]
    assert [entry.decision.result for entries in affected.values() for entry in entries] == [
        APPLIES
    ] * 3
    assert impact.counts == {APPLIES: 3, NOT_APPLICABLE: 2, UNSURE: 1}


def test_pages_hold_whole_clients_after_the_last_one(store: MemoryStore) -> None:
    Firm(store)
    every = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(tenant_id=FIRM, rule_version_id=VERSION, limit=50)
    )
    first = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(tenant_id=FIRM, rule_version_id=VERSION, limit=2)
    )
    rest = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(
            tenant_id=FIRM,
            rule_version_id=VERSION,
            limit=50,
            after=first.groups[-1].entity_id,
        )
    )
    assert first.groups + rest.groups == every.groups


def test_another_tenant_reads_only_its_own(store: MemoryStore) -> None:
    Firm(store)
    impact = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(tenant_id=OTHER, rule_version_id=VERSION, limit=50)
    )
    assert [len(group.entries) for group in impact.groups] == [1]
    assert impact.counts == {APPLIES: 1, NOT_APPLICABLE: 0, UNSURE: 0}
    nothing = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(tenant_id=TenantId.new(), rule_version_id=VERSION, limit=50)
    )
    assert (nothing.groups, nothing.counts) == ((), {APPLIES: 0, NOT_APPLICABLE: 0, UNSURE: 0})


def test_the_impact_carries_the_fan_out_of_the_version(store: MemoryStore) -> None:
    Firm(store)
    BeginFanOut(store.fanouts, MemoryBusinessDirectory(store)).run(
        FanOutStart(
            rule_version_id=VERSION,
            rule_key="gstr9_annual",
            level=AttributeLevel.REGISTRATION,
            trigger_event_id=EventId.new(),
        )
    )
    impact = ReadChangeImpact(store, store.fanouts).run(
        ImpactQuery(tenant_id=FIRM, rule_version_id=VERSION, limit=50)
    )
    assert impact.fan_out is not None
    assert (impact.fan_out.rule_key, impact.fan_out.counters.businesses_total) == (
        "gstr9_annual",
        5,
    )


def test_a_query_needs_a_positive_limit_and_groups_follow_the_entries() -> None:
    with pytest.raises(InvariantViolationError):
        ImpactQuery(tenant_id=FIRM, rule_version_id=VERSION, limit=0)
    assert grouped([]) == ()
    entity = BusinessId.new()
    decision = decide(MemoryStore(), FIRM, BusinessId.new(), APPLIES)
    entries = [ImpactEntry(entity, None, decision), ImpactEntry(entity, None, decision)]
    (group,) = grouped(entries)
    assert (group.entity_id, len(group.entries)) == (entity, 2)


# ---------------------------------------------------------------- over HTTP

IMPACT = f"/v1/changes/{VERSION}/impact"


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


def test_the_route_answers_a_page_of_clients(header_mode: tuple[TestClient, MemoryStore]) -> None:
    client, store = header_mode
    firm = Firm(store)
    first = client.get(IMPACT, params={"limit": 2}, headers={"x-tenant-id": str(FIRM)})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["rule_version_id"] == str(VERSION)
    assert body["counts"] == {"applies": 3, "not_applicable": 2, "unsure": 1}
    assert body["fan_out"] is None
    assert len(body["items"]) == 2
    one = next(i for i in body["items"] if i["entity_id"] == str(firm.entities[0]))
    business = one["businesses"][0]
    assert business["business_id"] == str(firm.registrations[firm.entities[0]][0])
    assert (business["result"], business["needs_review"], business["level"]) == (
        "applies",
        False,
        "registration",
    )
    assert business["decision_id"] == str(firm.latest.decision_id)
    assert business["evaluated"][0]["description"] == "registration_type = regular"
    rest = client.get(
        IMPACT,
        params={"limit": 2, "cursor": body["next_cursor"]},
        headers={"x-tenant-id": str(FIRM)},
    ).json()
    assert rest["next_cursor"] is None
    clients = [i["entity_id"] for i in body["items"] + rest["items"]]
    assert len(clients) == 4 == len(set(clients))
    affected = client.get(
        IMPACT, params={"result": "applies"}, headers={"x-tenant-id": str(FIRM)}
    ).json()
    assert str(firm.entities[1]) not in {i["entity_id"] for i in affected["items"]}


def test_the_route_needs_a_tenant_and_reads_no_other(
    header_mode: tuple[TestClient, MemoryStore],
) -> None:
    client, store = header_mode
    Firm(store)
    missing = client.get(IMPACT)
    assert missing.status_code == 401
    assert missing.json()["type"].endswith(":applicability-tenant-required")
    other = client.get(IMPACT, headers={"x-tenant-id": str(OTHER)}).json()
    assert other["counts"] == {"applies": 1, "not_applicable": 0, "unsure": 0}
    assert (
        client.get(
            IMPACT, params={"result": "maybe"}, headers={"x-tenant-id": str(FIRM)}
        ).status_code
        == 422
    )


def test_token_mode_serves_the_members_of_the_tenant(
    token_mode: tuple[TestClient, MemoryStore],
) -> None:
    client, store = token_mode
    Firm(store)
    ca_admin = bearer(ISSUER.user(FIRM, [Role.CA_ADMIN], mfa=True))
    member = client.get(IMPACT, headers=ca_admin)
    assert member.status_code == 200, member.text
    assert member.json()["counts"]["applies"] == 3
    analyst = bearer(ISSUER.user(TenantId.new(), [Role.ANALYST], mfa=True))
    assert client.get(IMPACT, headers={**analyst, "x-tenant-id": str(FIRM)}).status_code == 403
    service = bearer(ISSUER.service("notification", [Scope.TENANT_ACT]))
    acting = client.get(IMPACT, headers={**service, "x-tenant-id": str(OTHER)})
    assert acting.json()["counts"]["applies"] == 1
    mismatch = client.get(IMPACT, headers={**ca_admin, "x-tenant-id": str(OTHER)})
    assert mismatch.status_code == 403
    assert client.get(IMPACT).status_code == 401


def test_the_route_is_public_for_the_tenant_members(
    header_mode: tuple[TestClient, MemoryStore],
) -> None:
    client, _ = header_mode
    paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
    operation = paths["/v1/changes/{rule_version_id}/impact"]["get"]
    assert "public" in operation["tags"]
    assert operation["x-roles"] == ["owner", "staff", "ca_admin", "ca_staff", "compliance_lead"]
