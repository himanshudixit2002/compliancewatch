"""The web app's sign-in, as its server layer takes it through identity in dual mode.

The steps ``apps/web`` runs on the identity service, in order and with the answers it maps:
the development sign-in makes a persona through the dev route and exchanges the token at once;
a person signing in by phone is not provisioned, signs up a business and is signed in; a CA
firm's admin needs a second factor before the exchange succeeds; a tenant admin invites,
promotes and disables colleagues, and the disabled colleague's session is revoked at ``/me``
while a sign-in as them is refused. Identity runs on its memory store with the fake provider,
and nothing here reaches a real identity provider.
"""

from collections.abc import Iterator
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient

from identity.main import build_app as build_identity
from identity.testing import identity_settings
from py_common.auth.testing import bearer

IDENTITY: Final = "/v1/identity"
DEV_TOKENS: Final = f"{IDENTITY}/dev/provider-tokens"
TENANTS: Final = f"{IDENTITY}/tenants"
SESSIONS: Final = f"{IDENTITY}/sessions"
ME: Final = f"{IDENTITY}/me"
USERS: Final = f"{IDENTITY}/users"
OWNER_PHONE: Final = "+919876543210"
STAFF_PHONE: Final = "+919812345678"
CA_PHONE: Final = "+919900112233"
PERSONA_EMAIL: Final = "example-owner@fake.compliancewatch.invalid"


@pytest.fixture
def identity() -> Iterator[TestClient]:
    """Identity in dual mode, as `make web-stack AUTH=dual` runs it."""
    with TestClient(build_identity(identity_settings(auth_mode="dual"))) as client:
        yield client


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def dev_token(identity: TestClient, **body: Any) -> dict[str, Any]:
    response = identity.post(DEV_TOKENS, json=body)
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def exchange(identity: TestClient, token: str) -> Any:
    return identity.post(SESSIONS, json={"provider_token": token})


def test_the_development_sign_in_is_a_persona_exchanged_at_once(identity: TestClient) -> None:
    # The web's fake adapter: the form's kind, roles and name become a persona, and the token
    # it gets exchanges like any provider token; the exchange answers what the cookie needs.
    made = dev_token(
        identity,
        email=PERSONA_EMAIL,
        aal="aal1",
        tenant_kind="business",
        roles=["owner"],
        display_name="Example owner",
    )
    session = exchange(identity, made["provider_token"])
    assert session.status_code == 200, session.text
    body = session.json()
    assert (body["tenant_id"], body["user_id"]) == (made["tenant_id"], made["user_id"])
    assert (body["tenant_kind"], body["display_name"], body["session_version"]) == (
        "business",
        "Example owner",
        0,
    )
    me = identity.get(ME, headers=bearer(body["access_token"]))
    assert me.status_code == 200, me.text
    assert (me.json()["email"], me.json()["roles"]) == (PERSONA_EMAIL, ["owner"])
    # The regulatory roles assert a second factor through the token's level (aal2).
    admin = dev_token(
        identity, phone=OWNER_PHONE, aal="aal2", tenant_kind="internal", roles=["admin"]
    )
    as_admin = exchange(identity, admin["provider_token"]).json()
    assert (as_admin["tenant_kind"], as_admin["mfa"]) == ("internal", True)


def test_a_person_by_phone_signs_up_then_signs_in(identity: TestClient) -> None:
    # Phone step, code step: the fake provider accepts any six-digit code and signs the token.
    first = dev_token(identity, phone=STAFF_PHONE, aal="aal1")
    unknown = exchange(identity, first["provider_token"])
    assert (unknown.status_code, problem(unknown)) == (404, "identity-user-not-provisioned")
    # The web keeps the verified token in cw_pending and sends the person to /sign-up.
    created = identity.post(
        TENANTS,
        json={
            "kind": "business",
            "name": "Example Traders",
            "provider_token": first["provider_token"],
            "display_name": "Example person",
        },
    )
    assert created.status_code == 201, created.text
    session = created.json()["session"]
    assert (session["tenant_kind"], session["roles"], session["display_name"]) == (
        "business",
        ["owner"],
        "Example person",
    )
    # A second sign-up with the same person is refused and the web returns them to sign-in.
    again = identity.post(
        TENANTS,
        json={"kind": "business", "name": "Other", "provider_token": first["provider_token"]},
    )
    assert (again.status_code, problem(again)) == (409, "identity-subject-registered")
    # Next time, the exchange succeeds at once.
    later = exchange(identity, dev_token(identity, phone=STAFF_PHONE)["provider_token"])
    assert later.status_code == 200
    assert later.json()["tenant_id"] == session["tenant_id"]


def test_a_ca_firm_admin_meets_the_second_factor_before_the_exchange(
    identity: TestClient,
) -> None:
    one_factor = dev_token(identity, phone=CA_PHONE, aal="aal1")
    refused = identity.post(
        TENANTS,
        json={
            "kind": "ca_firm",
            "name": "Example CA",
            "provider_token": one_factor["provider_token"],
        },
    )
    assert (refused.status_code, problem(refused)) == (403, "identity-mfa-required")
    # The MFA page confirms the second factor: the fake provider mints an aal2 token.
    two_factors = dev_token(identity, phone=CA_PHONE, aal="aal2")
    created = identity.post(
        TENANTS,
        json={
            "kind": "ca_firm",
            "name": "Example CA",
            "provider_token": two_factors["provider_token"],
        },
    )
    assert created.status_code == 201, created.text
    assert (created.json()["session"]["mfa"], created.json()["session"]["roles"]) == (
        True,
        ["ca_admin"],
    )
    weaker = exchange(identity, dev_token(identity, phone=CA_PHONE, aal="aal1")["provider_token"])
    assert (weaker.status_code, problem(weaker)) == (403, "identity-mfa-required")


def test_a_tenant_admin_manages_the_team_and_a_disabled_user_is_signed_out(
    identity: TestClient,
) -> None:
    owner = dev_token(
        identity, phone=OWNER_PHONE, tenant_kind="business", roles=["owner"], display_name="Owner"
    )
    as_owner = bearer(exchange(identity, owner["provider_token"]).json()["access_token"])
    invited = identity.post(
        USERS,
        json={"phone": STAFF_PHONE, "roles": ["staff"], "display_name": "Example staff"},
        headers=as_owner,
    )
    assert invited.status_code == 201, invited.text
    staff_id = invited.json()["id"]
    listed = identity.get(USERS, headers=as_owner)
    assert [user["display_name"] for user in listed.json()["items"]] == ["Owner", "Example staff"]
    # The invited person signs in: the subject the invitation made is the one the token names.
    as_staff = bearer(
        exchange(identity, dev_token(identity, phone=STAFF_PHONE)["provider_token"]).json()[
            "access_token"
        ]
    )
    assert identity.get(ME, headers=as_staff).status_code == 200
    # A change of roles revokes the staff member's session, and a role the kind lacks is a 422.
    promoted = identity.put(
        f"{USERS}/{staff_id}/roles", json={"roles": ["staff", "compliance_lead"]}, headers=as_owner
    )
    assert promoted.status_code == 200, promoted.text
    revoked = identity.get(ME, headers=as_staff)
    assert (revoked.status_code, problem(revoked)) == (401, "identity-session-revoked")
    wrong = identity.put(f"{USERS}/{staff_id}/roles", json={"roles": ["analyst"]}, headers=as_owner)
    assert (wrong.status_code, problem(wrong)) == (422, "identity-role-not-allowed")
    # The last admin stays: the owner cannot be demoted or disabled.
    demoted = identity.put(
        f"{USERS}/{owner['user_id']}/roles", json={"roles": ["staff"]}, headers=as_owner
    )
    assert (demoted.status_code, problem(demoted)) == (409, "identity-last-admin")
    # Disabling ends the staff member's sessions and refuses their next sign-in.
    fresh = bearer(
        exchange(identity, dev_token(identity, phone=STAFF_PHONE)["provider_token"]).json()[
            "access_token"
        ]
    )
    disabled = identity.post(f"{USERS}/{staff_id}/disable", headers=as_owner)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    assert problem(identity.get(ME, headers=fresh)) == "identity-session-revoked"
    refused = exchange(identity, dev_token(identity, phone=STAFF_PHONE)["provider_token"])
    assert (refused.status_code, problem(refused)) == (403, "identity-user-disabled")
    # Without a token the user routes refuse in dual mode: the web always sends the bearer.
    anonymous = identity.get(USERS, headers={"x-tenant-id": owner["tenant_id"]})
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
