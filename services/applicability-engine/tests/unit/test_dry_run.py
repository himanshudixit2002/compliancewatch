"""The dry run on the memory store: the attributes that decide a result, the counts and samples
over the directory, the scope, the cap, the audit entry and nothing else written; then
``POST /v1/applicability-engine/dry-runs`` over HTTP with its guard in header, dual and token
mode."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ontology as ontology_package
from applicability_engine.application.dry_run import (
    DRY_RUN_ACTION,
    DryRun,
    DryRunRequest,
    specification_digest,
)
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.errors import DryRunTooLargeError, RuleVersionNotFoundError
from applicability_engine.domain.evaluation import deciding_attributes, evaluate
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory, MemoryStore
from applicability_engine.main import build_app
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import (
    FY,
    NOW,
    MemoryProfiles,
    MemoryRulebook,
    clock,
    rule_version,
)
from applicability_engine.wiring import Readers
from domain_kernel.access import Role, Scope
from domain_kernel.audit import AuditActor
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability, specification_from_mapping
from domain_kernel.status import RuleVersionStatus
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

APPLIES, NOT_APPLICABLE, UNSURE = (
    Applicability.APPLIES,
    Applicability.NOT_APPLICABLE,
    Applicability.UNSURE,
)
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
MONTHLY = {"attribute": "return_filing_frequency", "operator": "eq", "value": "monthly"}
BOTH = {"all_of": [REGULAR, MONTHLY]}
SPECIFICATION = specification_from_mapping(REGULAR)
ADMIN_ID = UserId.new()
ADMIN = AuditActor.user(ADMIN_ID, [Role.ADMIN])
FIRST = TenantId.new()
SECOND = TenantId.new()
ONTOLOGY = ontology_package.load()
DRY_RUNS = "/v1/applicability-engine/dry-runs"
ISSUER = TestIssuer()


# ---------------------------------------------------------------- deciding attributes


@pytest.mark.parametrize(
    ("specification", "attributes", "result", "deciding"),
    [
        (BOTH, {"registration_type": "regular", "return_filing_frequency": "monthly"},
         APPLIES, ("registration_type", "return_filing_frequency")),
        (BOTH, {"registration_type": "composition", "return_filing_frequency": "monthly"},
         NOT_APPLICABLE, ("registration_type",)),
        (BOTH, {"registration_type": "regular"}, UNSURE, ("return_filing_frequency",)),
        ({"any_of": [REGULAR, MONTHLY]}, {"registration_type": "regular"}, APPLIES,
         ("registration_type",)),
        ({"any_of": [REGULAR, MONTHLY]},
         {"registration_type": "composition", "return_filing_frequency": "quarterly"},
         NOT_APPLICABLE, ("registration_type", "return_filing_frequency")),
        ({"not": REGULAR}, {"registration_type": "regular"}, NOT_APPLICABLE,
         ("registration_type",)),
        ({"all_of": [REGULAR, {"attribute": "business_category", "free_text": "A hotel"}]},
         {"registration_type": "regular"}, UNSURE, ("business_category",)),
        ({"all_of": []}, {}, APPLIES, ()),
    ],
)  # fmt: skip
def test_the_deciding_attributes_are_the_predicates_that_made_the_result(
    specification: dict[str, Any],
    attributes: dict[str, object],
    result: Applicability,
    deciding: tuple[str, ...],
) -> None:
    tree = specification_from_mapping(specification)
    evaluation = evaluate(tree, attributes, ONTOLOGY)
    assert evaluation.result is result
    assert deciding_attributes(tree, evaluation.evaluated) == deciding


# ---------------------------------------------------------------- the use case


class World:
    """Two tenants' registrations in the directory with their profiles: three of the first
    tenant (a monthly filer, a quarterly one and a composition dealer), one of the second whose
    frequency is not answered, and one the profile service no longer has."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.profiles = MemoryProfiles()
        self.rulebook = MemoryRulebook()
        self.monthly = self.registration(FIRST, "regular", "monthly")
        self.quarterly = self.registration(FIRST, "regular", "quarterly")
        self.composition = self.registration(FIRST, "composition", "quarterly")
        self.unanswered = self.registration(SECOND, "regular", None)
        self.gone = self.registration(SECOND, None, None)

    def registration(
        self, tenant: TenantId, registration_type: str | None, frequency: str | None
    ) -> BusinessId:
        entity, business = BusinessId.new(), BusinessId.new()
        with self.store(tenant) as uow:
            uow.directory.add(DirectoryEntry(tenant, entity, AttributeLevel.ENTITY, None, entity))
            uow.directory.add(
                DirectoryEntry(tenant, business, AttributeLevel.REGISTRATION, entity, entity)
            )
        if registration_type is not None:
            answers: dict[str, object] = {"registration_type": registration_type}
            if frequency is not None:
                answers["return_filing_frequency"] = frequency
            self.profiles.put(answers, tenant_id=tenant, business_id=business, lineage=(entity,))
        return business

    def dry_run(self, *, max_businesses: int = 100) -> DryRun:
        return DryRun(
            MemoryBusinessDirectory(self.store),
            self.store.fanouts,
            self.profiles,
            self.rulebook,
            ONTOLOGY,
            max_businesses=max_businesses,
            clock=clock,
        )


def test_a_dry_run_counts_the_directory_and_writes_only_its_audit_entry() -> None:
    world = World()
    version = world.rulebook.put(rule_version(BOTH, status=RuleVersionStatus.DRAFT))
    report = world.dry_run().run(
        DryRunRequest(
            actor=ADMIN,
            rule_version_id=version.rule_version_id,
            sample_size=2,
            correlation_id="dry-run-1",
        )
    )
    assert (report.rule_key, report.status, report.level) == (
        "example_rule",
        RuleVersionStatus.DRAFT,
        AttributeLevel.REGISTRATION,
    )
    assert (report.businesses_total, report.evaluated, report.skipped) == (5, 4, 1)
    assert report.counts == {APPLIES: 1, NOT_APPLICABLE: 2, UNSURE: 1}
    assert report.needs_review == 1
    assert report.as_of_fy == FY
    assert {item.attribute: dict(item.counts) for item in report.by_attribute} == {
        "registration_type": {APPLIES: 1, NOT_APPLICABLE: 1, UNSURE: 0},
        "return_filing_frequency": {APPLIES: 1, NOT_APPLICABLE: 2, UNSURE: 1},
    }, "the composition dealer files quarterly too: both attributes rule it out"
    assert [sample.result for sample in report.samples] == [APPLIES, NOT_APPLICABLE]
    assert report.samples[0].business_id == world.monthly
    assert world.store.decisions == {}
    assert world.store.events == []
    assert world.store.reviews == {}
    assert world.store.fanout_runs == {}
    (entry,) = world.store.audit
    assert (entry.action, entry.tenant_id, entry.actor) == (DRY_RUN_ACTION, None, ADMIN)
    assert (entry.subject_type, entry.subject_id) == ("rule_version", str(version.rule_version_id))
    assert entry.before is None
    assert entry.after == {
        "level": "registration",
        "tenant_id": None,
        "as_of_fy": FY.label,
        "businesses_total": 5,
        "evaluated": 4,
        "skipped": 1,
        "counts": {"applies": 1, "not_applicable": 2, "unsure": 1},
        "needs_review": 1,
    }
    assert (entry.correlation_id, entry.occurred_at) == ("dry-run-1", NOW)


def test_the_samples_take_each_result_in_turn() -> None:
    world = World()
    version = world.rulebook.put(rule_version(BOTH))
    report = world.dry_run().run(
        DryRunRequest(actor=ADMIN, rule_version_id=version.rule_version_id, sample_size=50)
    )
    assert [sample.result for sample in report.samples] == [
        APPLIES,
        NOT_APPLICABLE,
        UNSURE,
        NOT_APPLICABLE,
    ]
    unsure = report.samples[2]
    assert (unsure.business_id, unsure.deciding, unsure.needs_review) == (
        world.unanswered,
        ("return_filing_frequency",),
        True,
    )
    none = world.dry_run().run(
        DryRunRequest(actor=ADMIN, rule_version_id=version.rule_version_id, sample_size=0)
    )
    assert none.samples == ()


def test_a_scope_with_a_tenant_reads_its_directory_alone() -> None:
    world = World()
    report = world.dry_run().run(
        DryRunRequest(
            actor=ADMIN,
            specification=specification_from_mapping(REGULAR),
            level=AttributeLevel.REGISTRATION,
            tenant_id=FIRST,
        )
    )
    assert (report.tenant_id, report.businesses_total, report.counts[APPLIES]) == (FIRST, 3, 2)
    (entry,) = world.store.audit
    assert entry.subject_type == "specification"
    assert entry.subject_id == specification_digest(specification_from_mapping(REGULAR))
    assert entry.after is not None
    assert entry.after["tenant_id"] == str(FIRST)
    entities = world.dry_run().run(
        DryRunRequest(
            actor=ADMIN,
            specification=specification_from_mapping(REGULAR),
            level=AttributeLevel.ENTITY,
        )
    )
    assert (entities.businesses_total, entities.skipped) == (5, 5)


def test_a_scope_wider_than_the_cap_is_refused_before_anything_is_read() -> None:
    world = World()
    version = world.rulebook.put(rule_version(BOTH))
    with pytest.raises(DryRunTooLargeError, match="lists 5 businesses"):
        world.dry_run(max_businesses=4).run(
            DryRunRequest(actor=ADMIN, rule_version_id=version.rule_version_id)
        )
    assert world.profiles.asked == []
    assert world.store.audit == []
    scoped = world.dry_run(max_businesses=3).run(
        DryRunRequest(actor=ADMIN, rule_version_id=version.rule_version_id, tenant_id=FIRST)
    )
    assert scoped.businesses_total == 3


def test_the_version_must_exist_and_keep_its_level() -> None:
    world = World()
    with pytest.raises(RuleVersionNotFoundError):
        world.dry_run().run(DryRunRequest(actor=ADMIN, rule_version_id=RuleVersionId.new()))
    version = world.rulebook.put(rule_version(BOTH))
    with pytest.raises(InvariantViolationError, match="applies to registration nodes"):
        world.dry_run().run(
            DryRunRequest(
                actor=ADMIN,
                rule_version_id=version.rule_version_id,
                level=AttributeLevel.ENTITY,
            )
        )
    unplaced = world.rulebook.put(rule_version(BOTH, level=None))
    with pytest.raises(InvariantViolationError, match="give the scope's level"):
        world.dry_run().run(DryRunRequest(actor=ADMIN, rule_version_id=unplaced.rule_version_id))
    assert world.store.audit == []


@pytest.mark.parametrize(
    "request_values",
    [
        {},
        {"rule_version_id": RuleVersionId.new(), "specification": SPECIFICATION},
        {"specification": SPECIFICATION},
        {"rule_version_id": RuleVersionId.new(), "sample_size": 51},
    ],
)  # fmt: skip
def test_a_request_names_one_thing_to_run(request_values: dict[str, Any]) -> None:
    with pytest.raises(InvariantViolationError):
        DryRunRequest(actor=ADMIN, **request_values)
    with pytest.raises(ValueError, match="at least 1"):
        World().dry_run(max_businesses=0)


# ---------------------------------------------------------------- over HTTP


def app_in(mode: AuthMode, world: World, **settings: Any) -> Iterator[TestClient]:
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "applicability-engine",
        "applicability_engine_store": "memory",
        **ISSUER.settings_overrides(mode),
        **settings,
    }
    readers = Readers(profiles=world.profiles, rulebook=world.rulebook)
    app = build_app(ApplicabilityEngineSettings(**values), readers=readers)
    store = app.state.wiring.unit_of_work
    assert isinstance(store, MemoryStore)
    world.store = store
    for tenant, business, entity in (
        (FIRST, world.monthly, BusinessId.new()),
        (FIRST, world.composition, BusinessId.new()),
        (SECOND, world.unanswered, BusinessId.new()),
    ):
        with store(tenant) as uow:
            uow.directory.add(
                DirectoryEntry(tenant, business, AttributeLevel.REGISTRATION, entity, entity)
            )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def header_mode(world: World) -> Iterator[TestClient]:
    yield from app_in("header", world)


@pytest.fixture
def dual_mode(world: World) -> Iterator[TestClient]:
    yield from app_in("dual", world)


@pytest.fixture
def token_mode(world: World) -> Iterator[TestClient]:
    yield from app_in("token", world)


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def test_the_route_answers_the_counts_and_the_samples(
    header_mode: TestClient, world: World
) -> None:
    version = world.rulebook.put(rule_version(BOTH, status=RuleVersionStatus.APPROVED))
    answered = header_mode.post(
        DRY_RUNS,
        json={"rule_version_id": str(version.rule_version_id), "scope": {"sample_size": 3}},
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert (body["rule_key"], body["status"], body["level"]) == (
        "example_rule",
        "approved",
        "registration",
    )
    assert (body["businesses_total"], body["evaluated"], body["skipped"]) == (3, 3, 0)
    assert body["counts"] == {"applies": 1, "not_applicable": 1, "unsure": 1}
    assert body["max_businesses"] == 2_000
    sample = body["samples"][0]
    assert (sample["result"], sample["deciding"]) == (
        "applies",
        ["registration_type", "return_filing_frequency"],
    )
    assert sample["evaluated"][0]["description"] == "registration_type = regular"
    assert {item["attribute"] for item in body["by_attribute"]} == {
        "registration_type",
        "return_filing_frequency",
    }
    (entry,) = world.store.audit
    assert (entry.action, entry.actor.label) == (DRY_RUN_ACTION, "system:applicability-engine")
    inline = header_mode.post(
        DRY_RUNS,
        json={
            "specification": REGULAR,
            "scope": {"level": "registration", "tenant_id": str(SECOND)},
        },
    )
    assert inline.status_code == 200, inline.text
    assert (inline.json()["businesses_total"], inline.json()["rule_version_id"]) == (1, None)


@pytest.mark.parametrize(
    ("body", "status", "slug"),
    [
        ({}, 422, "request-invalid"),
        ({"specification": REGULAR}, 422, "request-invalid"),
        ({"specification": {"attribute": "x", "op": "eq"}, "scope": {"level": "registration"}},
         422, "invariant-violation"),
        ({"rule_version_id": "00000000-0000-4000-8000-000000000001", "scope": {"sample_size": 51}},
         422, "request-invalid"),
        ({"rule_version_id": "00000000-0000-4000-8000-000000000001"}, 404,
         "applicability-rule-version-not-found"),
        ({"specification": REGULAR, "scope": {"level": "registration"}, "extra": 1}, 422,
         "request-invalid"),
    ],
)  # fmt: skip
def test_the_route_refuses_what_it_cannot_run(
    header_mode: TestClient, body: dict[str, Any], status: int, slug: str
) -> None:
    refused = header_mode.post(DRY_RUNS, json=body)
    assert (refused.status_code, problem(refused)) == (status, slug), refused.text


def test_the_route_refuses_a_scope_wider_than_its_cap(world: World) -> None:
    for client in app_in("header", world, applicability_dry_run_max=2):
        refused = client.post(
            DRY_RUNS, json={"specification": REGULAR, "scope": {"level": "registration"}}
        )
        assert (refused.status_code, problem(refused)) == (422, "applicability-dry-run-too-large")
        assert world.store.audit == []


def test_only_an_admin_runs_one_once_tokens_are_read(
    token_mode: TestClient, dual_mode: TestClient, world: World
) -> None:
    body = {"specification": REGULAR, "scope": {"level": "registration"}}
    internal = TenantId.new()
    admin = bearer(ISSUER.user(internal, [Role.ADMIN], mfa=True, user_id=ADMIN_ID))
    ran = token_mode.post(DRY_RUNS, json=body, headers=admin)
    assert ran.status_code == 200, ran.text
    store = token_mode.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    assert store.audit[-1].actor.id == str(ADMIN_ID)
    for other in (
        bearer(ISSUER.user(internal, [Role.ANALYST, Role.REVIEWER], mfa=True)),
        bearer(ISSUER.user(FIRST, [Role.OWNER])),
        bearer(ISSUER.service("applicability-engine", [Scope.TENANT_ACT])),
    ):
        refused = token_mode.post(DRY_RUNS, json=body, headers=other)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    assert token_mode.post(DRY_RUNS, json=body).status_code == 401
    anonymous = dual_mode.post(DRY_RUNS, json=body)
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
