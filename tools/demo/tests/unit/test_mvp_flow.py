"""A business onboarded and evaluated through the one deployable (ADR-013), on memory stores.

The whole app runs as ``cw-mvp serve`` runs it, on two free local ports: the public listener,
which the edge reaches, and the internal one, where the services call each other. The owner
creates the demo business from its GSTIN on the public listener, with the answers that make its
registration a monthly GSTR-3B filer, and reads its onboarding there. The rulebook's memory store
holds the seed's monthly GSTR-3B rule as a published version (the seed command writes drafts;
publishing is the analysts' flow, not this test's). Evaluating is internal: the public listener
answers it, like every internal route, with the 404 ``route-not-found`` it gives a path no
service serves. On the internal listener the engine reads the registration's profile snapshot
and the rule version over that listener and stores the decision, which the owner reads back on
the public one.

In token mode the owner signs up at identity on the public listener and every call carries
their access token; the engine's own calls carry the token identity mints for it in the process,
whose tenant:act (``identity_dev_clients.toml``) lets it read the tenant's profile.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

import httpx2

from cw_demo import tenant as demo
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, running_app
from domain_kernel.ids import RuleVersionId
from domain_kernel.predicates import specification_to_mapping
from domain_kernel.status import RuleVersionStatus
from ontology import load as load_ontology
from rulebook.application.seed_loader import load_calendar
from rulebook.infrastructure.memory import MemoryKnowledgeStore

MONTHLY: Final = "gstr3b_monthly"
BUSINESSES: Final = "/v1/businesses"
ENGINE: Final = "/v1/applicability-engine"
ROUTE_NOT_FOUND: Final = "urn:compliancewatch:problem:route-not-found"
OWNER_PHONE: Final = "+919876543210"
ANSWERS: Final = [
    {"key": "registration_type", "value": "regular"},
    {"key": "filing_scheme", "value": "regular_monthly"},
]
"""What makes the registration a monthly filer of GSTR-3B (the seed rule's specification)."""
INTERNAL_ONLY: Final = [
    ("GET", f"{ENGINE}/ping"),
    ("POST", "/v1/identity/service-tokens"),
    ("POST", "/v1/notification/send"),
    ("POST", "/v1/eval/runs"),
    ("GET", "/v1/eval/runs"),
    ("PUT", f"/v1/rulebook/documents/{uuid4()}"),
]
"""Internal routes, and admin ones, which the public listener serves only in token mode."""


@contextmanager
def listeners(app: CombinedApp) -> Iterator[tuple[httpx2.Client, httpx2.Client]]:
    """Clients of the public and the internal listener of the running app."""
    public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    with (
        httpx2.Client(base_url=public_url, timeout=30.0) as public,
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
    ):
        yield public, internal


def ok(response: httpx2.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


def route_not_found(response: httpx2.Response) -> bool:
    return bool(response.status_code == 404 and response.json()["type"] == ROUTE_NOT_FOUND)


def created() -> dict[str, str]:
    """A fresh ``Idempotency-Key``, which the creating routes require."""
    return {"idempotency-key": str(uuid4())}


def publish_monthly_rule(app: CombinedApp) -> RuleVersionId:
    """The seed's monthly GSTR-3B rule, published in the rulebook's memory store."""
    store = app.services["rulebook"].state.wiring.unit_of_work
    assert isinstance(store, MemoryKnowledgeStore)
    seed = next(rule for rule in load_calendar(load_ontology()).rules if rule.rule_key == MONTHLY)
    _, version = store.add_rule(
        seed.rule_key,
        title=seed.title,
        regulator=seed.regulator,
        level=seed.level,
        status=RuleVersionStatus.PUBLISHED,
        effective_from=seed.effective_from,
        specification=specification_to_mapping(seed.specification),
        obligation_template=seed.obligation_template.to_mapping(),
        published_at=datetime.now(UTC),
    )
    return version


def onboard(public: httpx2.Client, headers: Mapping[str, str]) -> str:
    """The demo business created from its GSTIN with the answers; its registration's id."""
    body = {
        "name": demo.ENTITY_NAME,
        "gstin": demo.GSTIN,
        "registration_name": demo.REGISTRATION_NAME,
        "answers": ANSWERS,
    }
    answer = public.post(BUSINESSES, json=body, headers={**headers, **created()})
    business = ok(answer, 201)
    assert business["created"]
    business_id = business["business"]["id"]
    (registration,) = business["business"]["registrations"]
    onboarding = ok(public.get(f"{BUSINESSES}/{business_id}/onboarding", headers=headers))
    assert onboarding["business_id"] == business_id
    assert onboarding["answered"] >= len(ANSWERS)
    registration_id: str = registration["id"]
    return registration_id


def evaluate(
    client: httpx2.Client, registration: str, version: RuleVersionId, headers: Mapping[str, str]
) -> httpx2.Response:
    return client.post(
        f"{ENGINE}/businesses/{registration}/decisions",
        json={"rule_version_id": str(version)},
        headers={**headers, **created()},
    )


def test_a_business_is_onboarded_in_public_and_evaluated_on_the_internal_listener() -> None:
    tenant = {"x-tenant-id": str(demo.TENANT_ID)}
    with running_app() as app, listeners(app) as (public, internal):
        version = publish_monthly_rule(app)
        registration = onboard(public, tenant)

        assert route_not_found(evaluate(public, registration, version, tenant))
        for method, path in INTERNAL_ONLY:
            assert route_not_found(public.request(method, path, headers=tenant, json={})), path
            assert not route_not_found(internal.request(method, path, json={})), path

        decision = ok(evaluate(internal, registration, version, tenant), 201)
        assert (decision["business_id"], decision["rule_version_id"]) == (
            registration,
            str(version),
        )
        assert (decision["result"], decision["needs_review"]) == ("applies", False)
        assert [item["attribute"] for item in decision["evaluated"]] == [
            "registration_type",
            "filing_scheme",
        ]

        page = ok(public.get(f"{ENGINE}/businesses/{registration}/decisions", headers=tenant))
        assert [item["decision_id"] for item in page["items"]] == [decision["decision_id"]]
        read = ok(public.get(f"{ENGINE}/decisions/{decision['decision_id']}", headers=tenant))
        assert read == decision
        other = {"x-tenant-id": str(uuid4())}
        hidden = public.get(f"{ENGINE}/decisions/{decision['decision_id']}", headers=other)
        assert hidden.status_code == 404
        assert not route_not_found(hidden)


def test_in_token_mode_the_engine_reads_the_profile_with_its_own_token() -> None:
    with running_app(auth_mode="token") as app, listeners(app) as (public, internal):
        version = publish_monthly_rule(app)
        provider = ok(public.post("/v1/identity/dev/provider-tokens", json={"phone": OWNER_PHONE}))
        signed_up = public.post(
            "/v1/identity/tenants",
            json={
                "kind": "business",
                "name": demo.ENTITY_NAME,
                "provider_token": provider["provider_token"],
            },
        )
        owner = {"authorization": f"Bearer {ok(signed_up, 201)['session']['access_token']}"}
        registration = onboard(public, owner)

        assert route_not_found(evaluate(public, registration, version, owner))
        decision = ok(evaluate(internal, registration, version, owner), 201)
        assert decision["result"] == "applies"
        page = ok(public.get(f"{ENGINE}/businesses/{registration}/decisions", headers=owner))
        assert [item["decision_id"] for item in page["items"]] == [decision["decision_id"]]
        anonymous = internal.get(f"{ENGINE}/decisions/{decision['decision_id']}")
        assert anonymous.status_code == 401
