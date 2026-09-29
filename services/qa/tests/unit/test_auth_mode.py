"""POST /v1/qa/ask in header, dual and token mode: where the tenant comes from and who may ask."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.errors import PROBLEM_TYPE_PREFIX
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode
from qa.main import build_app
from qa.testing import qa_settings

World = Any
ISSUER = TestIssuer()
ASK = "/v1/qa/ask"


@contextmanager
def api(world: World, mode: AuthMode) -> Iterator[TestClient]:
    app = build_app(
        qa_settings(**ISSUER.settings_overrides(mode)), ports=world.ports(), ontology=world.ontology
    )
    with TestClient(app) as client:
        yield client


def question(world: World) -> dict[str, Any]:
    """A question the structured layer answers from the business's obligations, with no model."""
    return {
        "question": "What is due next month?",
        "as_of": "2026-04-10",
        "business_node_id": str(world.BUSINESS.value),
    }


def as_tenant(world: World) -> dict[str, str]:
    return {"x-tenant-id": str(world.TENANT)}


def as_other(world: World) -> dict[str, str]:
    return {"x-tenant-id": str(world.OTHER_TENANT)}


def problem(response: Any) -> tuple[int, str]:
    kind: str = response.json()["type"]
    return response.status_code, kind.removeprefix(PROBLEM_TYPE_PREFIX)


def answered(response: Any) -> str:
    assert response.status_code == 200, response.text
    layer: str = response.json()["layer"]
    return layer


# ---------------------------------------------------------------- header mode


def test_header_mode_reads_the_tenant_header_and_ignores_a_bearer(world: World) -> None:
    staff_of_other = bearer(ISSUER.user(world.OTHER_TENANT, [Role.STAFF]))
    with api(world, "header") as client:
        headers = {**as_tenant(world), **staff_of_other}
        assert answered(client.post(ASK, json=question(world), headers=headers)) == "structured"
        missing = client.post(ASK, json=question(world), headers=staff_of_other)
    assert problem(missing) == (401, "qa-tenant-required")


# ---------------------------------------------------------------- dual mode


def test_dual_mode_serves_the_header_without_a_bearer_and_the_token_with_one(
    world: World,
) -> None:
    owner = bearer(ISSUER.user(world.TENANT, [Role.OWNER]))
    staff_of_other = bearer(ISSUER.user(world.OTHER_TENANT, [Role.STAFF]))
    with api(world, "dual") as client:
        assert (
            answered(client.post(ASK, json=question(world), headers=as_tenant(world)))
            == "structured"
        )
        assert answered(client.post(ASK, json=question(world), headers=owner)) == "structured"
        mismatch = client.post(
            ASK, json=question(world), headers={**staff_of_other, **as_tenant(world)}
        )
        missing = client.post(ASK, json=question(world))
    assert problem(mismatch) == (403, "auth-tenant-mismatch")
    assert problem(missing) == (401, "qa-tenant-required")


# ---------------------------------------------------------------- token mode


def test_token_mode_needs_a_bearer(world: World) -> None:
    with api(world, "token") as client:
        missing = client.post(ASK, json=question(world), headers=as_tenant(world))
    assert problem(missing) == (401, "auth-token-required")
    assert missing.headers["www-authenticate"].startswith("Bearer")


def test_token_mode_answers_a_member_for_the_tenant_their_token_names(world: World) -> None:
    lead = bearer(ISSUER.user(world.TENANT, [Role.COMPLIANCE_LEAD]))
    staff_of_other = bearer(ISSUER.user(world.OTHER_TENANT, [Role.STAFF]))
    with api(world, "token") as client:
        assert answered(client.post(ASK, json=question(world), headers=lead)) == "structured"
        # The other tenant's member asks about a business that is not theirs.
        foreign = client.post(ASK, json=question(world), headers=staff_of_other)
    assert problem(foreign) == (404, "qa-business-not-found")


def test_token_mode_refuses_another_tenant_and_other_roles(world: World) -> None:
    owner = bearer(ISSUER.user(world.TENANT, [Role.OWNER]))
    analyst = bearer(ISSUER.user(world.TENANT, [Role.ANALYST], mfa=True))
    with api(world, "token") as client:
        mismatch = client.post(ASK, json=question(world), headers={**owner, **as_other(world)})
        regulatory = client.post(ASK, json=question(world), headers=analyst)
    assert problem(mismatch) == (403, "auth-tenant-mismatch")
    assert problem(regulatory) == (403, "auth-forbidden")


def test_token_mode_lets_a_service_ask_for_the_tenant_it_names_with_tenant_act(
    world: World,
) -> None:
    acting = bearer(ISSUER.service("whatsapp-bot", [Scope.TENANT_ACT]))
    alone = bearer(ISSUER.service("whatsapp-bot", [Scope.NOTIFICATION_PREFERENCES]))
    with api(world, "token") as client:
        headers = {**acting, **as_tenant(world)}
        assert answered(client.post(ASK, json=question(world), headers=headers)) == "structured"
        refused = client.post(ASK, json=question(world), headers={**alone, **as_tenant(world)})
        no_tenant = client.post(ASK, json=question(world), headers=acting)
    assert problem(refused) == (403, "auth-forbidden")
    assert problem(no_tenant) == (401, "qa-tenant-required")
