"""A tenant's data export across the services, as ``cw-mvp serve`` runs them.

The whole app runs in one process on its memory stores (``running_app``), and identity asks profile,
the applicability engine, obligation and notification for their parts of the export over the
internal listener, as it does in the product; the owners use the public listener, and the web app's
server sets preferences on the internal one. Two business owners sign up. The first records its
consent to WhatsApp reminders and opts its number in from the web (the notification service asks
identity for that consent first; the second owner, without one, is refused), and registers its
GSTIN. The first owner then asks for an export: the bundle holds identity's, profile's,
obligation's, notification's and the engine's sections, each for that tenant only; the second tenant
sees no request of the first and its own export holds none of the first's data. The request shows
completed, and the owner's audit trail shows it was made and exported. A request made 40 days ago
and never answered is counted as overdue by the directory the alert reads. Nothing reaches a real
identity provider, model provider or regulator.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx2

from cw_mvp.app import CombinedApp
from cw_mvp.testing import running_app
from domain_kernel.ids import TenantId
from identity.domain.data_requests import (
    DataRequest,
    DataRequestKind,
    DataRequestSource,
    OpenRequests,
)
from identity.infrastructure.memory import MemoryStore as IdentityStore

IDENTITY: Final = "/v1/identity"
REQUESTS: Final = f"{IDENTITY}/data-requests"
FIRST_PHONE: Final = "+919876543210"
SECOND_PHONE: Final = "+919812345678"
GSTIN: Final = "29ABCDE1234F1Z5"
NOTICE: Final = "2000-01"
SERVICES: Final = ("identity", "profile", "applicability-engine", "obligation", "notification")


def sign_up(client: httpx2.Client, phone: str, name: str) -> dict[str, Any]:
    token = client.post(f"{IDENTITY}/dev/provider-tokens", json={"phone": phone})
    assert token.status_code == 200, token.text
    created = client.post(
        f"{IDENTITY}/tenants",
        json={"kind": "business", "name": name, "provider_token": token.json()["provider_token"]},
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def opt_in(client: httpx2.Client, tenant: dict[str, str], subject: str, phone: str) -> int:
    answer = client.put(
        f"/v1/notification/preferences/whatsapp/{phone}",
        json={"opted_in": True, "source": "web_onboarding", "subject": subject},
        headers=tenant,
    )
    return answer.status_code


def test_an_owner_downloads_the_tenant_s_export_from_every_service() -> None:
    with running_app() as app:
        public = f"http://127.0.0.1:{app.settings.mvp_public_port}"
        with (
            httpx2.Client(base_url=public, timeout=30.0) as client,
            httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
        ):
            run_the_journey(app, client, internal)


def run_the_journey(app: CombinedApp, client: httpx2.Client, internal: httpx2.Client) -> None:
    """``client`` is the public listener; ``internal`` the private one, where the web app's
    server sets preferences."""
    first = sign_up(client, FIRST_PHONE, "Example Traders")
    second = sign_up(client, SECOND_PHONE, "Example Stores")
    first_id, second_id = first["tenant"]["id"], second["tenant"]["id"]
    owner, other = {"x-tenant-id": first_id}, {"x-tenant-id": second_id}
    first_user, second_user = first["user"]["id"], second["user"]["id"]

    consent = client.post(
        f"{IDENTITY}/consents",
        json={
            "subject": first_user,
            "purpose": "whatsapp_reminders",
            "granted": True,
            "source": "web_onboarding",
            "notice_version": NOTICE,
            "evidence": "Example onboarding checkbox",
        },
        headers=owner,
    )
    assert consent.status_code == 201, consent.text
    assert opt_in(internal, owner, first_user, FIRST_PHONE) == 200
    assert opt_in(internal, other, second_user, SECOND_PHONE) == 409, "no consent recorded"
    registered = client.post(
        "/v1/profile/registrations",
        json={"gstin": GSTIN, "name": "Example Traders Bengaluru", "entity_name": "Example"},
        headers=owner,
    )
    assert registered.status_code in (200, 201), registered.text

    made = client.post(REQUESTS, json={"kind": "export", "reason": "Example copy"}, headers=owner)
    assert made.status_code == 201, made.text
    request = made.json()
    assert request["services_pending"] == sorted(SERVICES)
    assert client.get(REQUESTS, headers=other).json()["items"] == []
    assert client.get(f"{REQUESTS}/{request['id']}/export", headers=other).status_code == 404

    download = client.get(f"{REQUESTS}/{request['id']}/export", headers=owner)
    assert download.status_code == 200, download.text
    assert download.headers["content-disposition"].startswith("attachment;")
    bundle = download.json()
    assert (bundle["complete"], bundle["services_pending"]) == (True, [])
    assert set(bundle["services"]) == set(SERVICES)
    for service, section in bundle["services"].items():
        assert section["service"] == service
        assert section["tenant_id"] == first_id
        assert section["generated_at"]
    text = json.dumps(bundle)
    assert second_id not in text, "no other tenant's id in the export"
    assert SECOND_PHONE not in text
    assert GSTIN in text, "profile's registration is there"
    preferences = bundle["services"]["notification"]["sections"]["preferences"]
    assert preferences == [] or all(row["address"] != SECOND_PHONE for row in preferences)
    identity = bundle["services"]["identity"]["sections"]
    assert [user["id"] for user in identity["users"]] == [first_user]
    assert [c["purpose"] for c in identity["consents"]] == ["whatsapp_reminders"]

    after = client.get(f"{REQUESTS}/{request['id']}", headers=owner).json()
    assert (after["status"], after["services_done"], after["services_pending"]) == (
        "completed",
        sorted(SERVICES),
        [],
    )
    trail = client.get(
        f"{IDENTITY}/audit",
        params={"subject_type": "data_request", "subject_id": request["id"]},
        headers=owner,
    )
    assert trail.status_code == 200, trail.text
    actions = sorted(entry["action"] for entry in trail.json()["items"])
    assert actions == ["data_request.created", "data_request.exported"]

    theirs = client.post(REQUESTS, json={"kind": "export"}, headers=other).json()
    their_bundle = client.get(f"{REQUESTS}/{theirs['id']}/export", headers=other).json()
    assert first_id not in json.dumps(their_bundle)
    assert GSTIN not in json.dumps(their_bundle)

    identity_app = app.services["identity"]
    store = identity_app.state.wiring.unit_of_work
    assert isinstance(store, IdentityStore)
    long_ago = datetime.now(UTC) - timedelta(days=40)
    with store(TenantId.parse(second_id)) as uow:
        uow.data_requests.add(
            DataRequest.new(
                TenantId.parse(second_id),
                DataRequestKind.EXPORT,
                DataRequestSource.SELF_SERVICE,
                requested_by="",
                reason="",
                at=long_ago,
            )
        )
    counts = identity_app.state.wiring.data_request_directory.open_counts()
    assert counts[0] == OpenRequests(DataRequestKind.EXPORT, 1, 1), "the old one is overdue"
