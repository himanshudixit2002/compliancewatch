"""The regulatory team's admin reads and the hardened operations, as ``cw-mvp serve`` runs them.

The whole app runs in one process on its memory stores in token mode (``running_app``), so every
route reads who is asking. Two business owners sign up and register a GSTIN each; the internal
tenant is set up as ``identity-admin bootstrap-internal`` does, and its admin signs in with a
second factor. The three memory stores share one audit log, as the services share
``audit.event``. The admin then:

- lists every tenant with its plan and user counts, and reads one tenant's users for a reason:
  the tenant's owner sees the read in their audit trail with the reason and the admin as the
  actor; a read without a reason is refused (422), and an owner who tries the admin reads gets
  403;
- reads the attribute usage across tenants, which matches what the two tenants' nodes hold,
  counted from the profile API, and names no tenant;
- resends a failed notification of a tenant once, for a reason, naming the tenant: the second
  request with the same key and body is the first answer replayed, and the owner's trail shows
  one ``notification.resent`` row with the reason.

Then, with the flag ``profile.fy_schedule`` on and a frozen clock at the first minute of April,
the job the worker hosts (``fy_schedule``, as wired there) runs twice over the profile store and
opens one confirmation task per tenant, once. One owner answers the turnover band, which closes
their task in the same request;
the other resolves theirs through the route, and their trail shows the closure. Nothing reaches a
real identity provider, model provider or regulator.
"""

from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

import httpx2

import ontology as ontology_package
from cw_mvp.app import CombinedApp
from cw_mvp.testing import running_app
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from identity.application.bootstrap import BootstrapInternalTenant
from identity.domain.tenancy import Contact
from identity.infrastructure.memory import MemoryStore as IdentityStore
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import OccasionKind
from notification.domain.repository import WorkEntry
from notification.infrastructure.memory import MemoryStore as NotificationStore
from profile_service.application.fy_schedule import ScheduleRun
from profile_service.infrastructure.memory import MemoryStore as ProfileStore
from profile_service.infrastructure.memory import MemoryTenantDirectory
from profile_service.settings import ProfileSettings
from profile_service.worker import FY_SCHEDULE_JOB, fy_schedule
from py_common.auth.testing import bearer

IDENTITY: Final = "/v1/identity"
TENANTS: Final = f"{IDENTITY}/admin/tenants"
AUDIT: Final = f"{IDENTITY}/audit"
USAGE: Final = "/v1/profile/admin/attribute-usage"
FIRST_PHONE: Final = "+919876543210"
SECOND_PHONE: Final = "+919812345678"
ADMIN_EMAIL: Final = "admin@example.org"
GSTINS: Final = {"Example Traders": "29ABCDE1234F1Z5", "Example Stores": "07ZZZZZ9999Z1Z1"}
REASON: Final = "Example support case 2000-01: the owner asked who holds the owner role"
WHEN: Final = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
FIRST_MINUTE_OF_APRIL_IST: Final = datetime(2027, 3, 31, 18, 30, tzinfo=UTC)
"""00:00 IST on 1 April 2027, still 31 March in UTC: financial year 2027-28."""


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


def regulatory_admin(app: CombinedApp, client: httpx2.Client) -> tuple[str, dict[str, str]]:
    """The internal tenant and its admin's session, signed in with a second factor."""
    wiring = app.services["identity"].state.wiring
    tenant, _ = BootstrapInternalTenant(wiring.unit_of_work, wiring.provider).run(
        "Example regulatory team", Contact(email=ADMIN_EMAIL)
    )
    token = client.post(
        f"{IDENTITY}/dev/provider-tokens", json={"email": ADMIN_EMAIL, "aal": "aal2"}
    )
    assert token.status_code == 200, token.text
    exchanged = client.post(
        f"{IDENTITY}/sessions", json={"provider_token": token.json()["provider_token"]}
    )
    assert exchanged.status_code == 200, exchanged.text
    return str(tenant.id), bearer(exchanged.json()["access_token"])


def register(client: httpx2.Client, owner: dict[str, str], name: str) -> str:
    """The entity's node id of a business registered by its GSTIN."""
    registered = client.post(
        "/v1/profile/registrations",
        json={"gstin": GSTINS[name], "name": f"{name} Bengaluru", "entity_name": name},
        headers=owner,
    )
    assert registered.status_code == 201, registered.text
    entity: str = registered.json()["parent_id"]
    return entity


def answer(
    client: httpx2.Client, owner: dict[str, str], node: str, *changes: dict[str, Any]
) -> Any:
    answered = client.put(
        f"/v1/profile/nodes/{node}/attributes", json={"changes": list(changes)}, headers=owner
    )
    assert answered.status_code == 200, answered.text
    return answered.json()


def failed_notification(app: CombinedApp, tenant: str) -> str:
    """A notification of ``tenant`` that failed for good, as the dispatcher leaves one."""
    store = app.services["notification"].state.wiring.unit_of_work
    assert isinstance(store, NotificationStore)
    notification = Notification(
        id=NotificationId.new(),
        tenant_id=TenantId.parse(tenant),
        business_id=BusinessId.new(),
        obligation_id=ObligationId.new(),
        recipient_id=None,
        channel=Channel.WHATSAPP,
        address=FIRST_PHONE,
        occasion=OccasionKind.REMINDER,
        template_key="obligation_due_soon",
        language="en",
        params={"title": "Example obligation"},
        dedupe_key=DedupeKey(uuid4().hex * 2),
        state=DeliveryState.FAILED,
        available_at=WHEN,
        created_at=WHEN,
        updated_at=WHEN,
        attempts=3,
        error="Example: the provider was down",
        failed_at=WHEN,
    )
    with store(TenantId.parse(tenant)) as unit:
        assert unit.notifications.add_if_absent(notification)
        unit.work.add(WorkEntry.of(notification))
    return str(notification.id)


def trail(client: httpx2.Client, headers: dict[str, str], action: str) -> list[dict[str, Any]]:
    page = client.get(AUDIT, params={"action": action, "limit": 50}, headers=headers)
    assert page.status_code == 200, page.text
    items: list[dict[str, Any]] = page.json()["items"]
    return items


def usage_of(
    client: httpx2.Client, owners: dict[str, dict[str, str]], nodes: dict[str, str]
) -> dict[tuple[str, str], int]:
    """What the usage should count: distinct nodes per (key, state), read node by node."""
    counts: dict[tuple[str, str], int] = {}
    for name, node in nodes.items():
        read = client.get(f"/v1/profile/nodes/{node}", headers=owners[name])
        assert read.status_code == 200, read.text
        for key, state in {(a["key"], a["state"]) for a in read.json()["attributes"]}:
            counts[(key, state)] = counts.get((key, state), 0) + 1
    return counts


def test_the_admin_reads_tenants_and_users_counts_usage_and_resends_once() -> None:
    with running_app(auth_mode="token") as app:
        public = f"http://127.0.0.1:{app.settings.mvp_public_port}"
        with httpx2.Client(base_url=public, timeout=30.0) as client:
            run_the_journey(app, client)


def share_the_audit_log(app: CombinedApp) -> None:
    """One audit log for the three stores, as the services share ``audit.event`` in Postgres."""
    identity_store = app.services["identity"].state.wiring.unit_of_work
    assert isinstance(identity_store, IdentityStore)
    for service, kind in (("profile", ProfileStore), ("notification", NotificationStore)):
        store = app.services[service].state.wiring.unit_of_work
        assert isinstance(store, kind)
        store.audit = identity_store.audit


def run_the_journey(app: CombinedApp, client: httpx2.Client) -> None:
    share_the_audit_log(app)
    traders = sign_up(client, FIRST_PHONE, "Example Traders")
    stores = sign_up(client, SECOND_PHONE, "Example Stores")
    owners = {
        "Example Traders": bearer(traders["session"]["access_token"]),
        "Example Stores": bearer(stores["session"]["access_token"]),
    }
    traders_id, stores_id = traders["tenant"]["id"], stores["tenant"]["id"]
    internal, admin = regulatory_admin(app, client)

    # The tenant list, one tenant, and a tenant's users read for a reason.
    listed = client.get(TENANTS, headers=admin)
    assert listed.status_code == 200, listed.text
    by_id = {item["id"]: item for item in listed.json()["items"]}
    assert set(by_id) == {traders_id, stores_id, internal}
    assert (
        by_id[traders_id]["kind"],
        by_id[traders_id]["users"],
        by_id[traders_id]["plan_key"],
    ) == (
        "business",
        1,
        None,
    )
    assert FIRST_PHONE not in listed.text, "no person's details in the list"
    one = client.get(f"{TENANTS}/{stores_id}", headers=admin)
    assert one.status_code == 200, one.text
    assert one.json()["name"] == "Example Stores"
    refused = client.get(f"{TENANTS}/{traders_id}/users", headers=admin)
    assert refused.status_code == 422, "no reason, no read"
    users = client.get(f"{TENANTS}/{traders_id}/users", headers={**admin, "x-reason": REASON})
    assert users.status_code == 200, users.text
    assert [(u["id"], u["roles"]) for u in users.json()["items"]] == [
        (traders["user"]["id"], ["owner"])
    ]
    for path in (TENANTS, f"{TENANTS}/{stores_id}", f"{TENANTS}/{stores_id}/users"):
        own = client.get(path, headers={**owners["Example Traders"], "x-reason": REASON})
        assert own.status_code == 403, path
    (read,) = trail(client, owners["Example Traders"], "tenant.users_read")
    assert (read["reason"], read["subject"]["id"], read["actor"]["label"]) == (
        REASON,
        traders_id,
        "admin",
    )
    assert read["after"] == {"users": 1}
    assert trail(client, owners["Example Stores"], "tenant.users_read") == [], "not theirs"
    assert trail(client, admin, "tenant.users_read") == [], "the tenant's trail, not the admin's"

    # The attribute usage across tenants matches what the two tenants' nodes hold.
    nodes = {name: register(client, owners[name], name) for name in owners}
    answer(
        client,
        owners["Example Traders"],
        nodes["Example Traders"],
        {"key": "employee_count", "value": 12},
        {"key": "turnover_band", "value": "2_crore_to_5_crore", "as_of_fy": "2026-27"},
    )
    answer(
        client,
        owners["Example Stores"],
        nodes["Example Stores"],
        {"key": "employee_count", "state": "not_applicable"},
        {"key": "turnover_band", "state": "unsure", "as_of_fy": "2026-27"},
    )
    usage = client.get(USAGE, headers=admin)
    assert usage.status_code == 200, usage.text
    counted = {(item["key"], item["state"]): item["count"] for item in usage.json()["items"]}
    assert counted == usage_of(client, owners, nodes)
    assert counted[("employee_count", "known")] == 1
    assert counted[("employee_count", "not_applicable")] == 1
    assert counted[("turnover_band", "unsure")] == 1
    assert traders_id not in usage.text, "no tenant named"
    assert client.get(USAGE, headers=owners["Example Traders"]).status_code == 403

    # A failed notification is resent once, for a reason; the retry is the same answer.
    notification_id = failed_notification(app, traders_id)
    path = f"/v1/notification/notifications/{notification_id}/resend"
    key = {"Idempotency-Key": uuid4().hex, "x-tenant-id": traders_id}
    body = {"reason": "Example: the provider was down for an hour"}
    first = client.post(path, json=body, headers={**admin, **key})
    assert first.status_code == 200, first.text
    assert (first.json()["state"], first.json()["attempts"]) == ("queued", 0)
    second = client.post(path, json=body, headers={**admin, **key})
    assert second.status_code == 200, second.text
    assert second.headers["idempotent-replayed"] == "true"
    assert second.json() == first.json()
    again = client.post(
        path,
        json=body,
        headers={**admin, "Idempotency-Key": uuid4().hex, "x-tenant-id": traders_id},
    )
    assert again.status_code == 409, "queued already"
    (resent,) = trail(client, owners["Example Traders"], "notification.resent")
    assert (resent["reason"], resent["subject"]["id"], resent["actor"]["label"]) == (
        body["reason"],
        notification_id,
        "admin",
    )
    assert FIRST_PHONE not in str(resent)

    # The April schedule, with the flag on and a frozen clock, opens each tenant's task once.
    profile_store = app.services["profile"].state.wiring.unit_of_work
    assert isinstance(profile_store, ProfileStore)
    ontology = ontology_package.load()
    off = ProfileSettings(_env_file=None, service_name="profile", profile_store="postgres")
    assert (
        fy_schedule(off, unit_of_work=profile_store, directory=MemoryTenantDirectory(profile_store))
        is None
    )
    on = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="postgres",
        profile_fy_schedule_enabled=True,
    )
    job = fy_schedule(
        on,
        unit_of_work=profile_store,
        directory=MemoryTenantDirectory(profile_store),
        ontology=ontology,
        clock=lambda: FIRST_MINUTE_OF_APRIL_IST,
    )
    assert job is not None
    assert job.name == FY_SCHEDULE_JOB
    run = job.fn()
    assert isinstance(run, ScheduleRun), "the job the worker hosts runs the schedule as wired"
    assert run.fy == FinancialYear(2027)
    assert run.tenants == 2
    assert {str(tenant) for tenant in run.opened} == {traders_id, stores_id}
    assert run.tasks_opened == 2
    rerun = job.fn()
    assert isinstance(rerun, ScheduleRun)
    assert (rerun.tenants, rerun.tasks_opened) == (2, 0), "once per tenant per year"
    tasks = {
        name: client.get(f"/v1/profile/nodes/{node}/review-tasks", headers=owners[name]).json()
        for name, node in nodes.items()
    }
    for name, open_tasks in tasks.items():
        confirm = [t for t in open_tasks if t["reason"] == "confirm_financial_year"]
        assert [(t["attribute_key"], t["as_of_fy"]) for t in confirm] == [
            ("turnover_band", "2027-28")
        ], name

    # An answer closes one tenant's task; the other owner resolves theirs.
    (traders_task,) = [
        t["id"] for t in tasks["Example Traders"] if t["reason"] == "confirm_financial_year"
    ]
    answered = answer(
        client,
        owners["Example Traders"],
        nodes["Example Traders"],
        {"key": "turnover_band", "value": "2_crore_to_5_crore", "as_of_fy": "2027-28"},
    )
    assert answered["closed_review_tasks"] == [traders_task]
    (stores_task,) = [
        t["id"] for t in tasks["Example Stores"] if t["reason"] == "confirm_financial_year"
    ]
    resolved = client.post(
        f"/v1/profile/nodes/{nodes['Example Stores']}/review-tasks/{stores_task}/resolve",
        json={"outcome": "dismissed", "note": "Example: dormant this year"},
        headers=owners["Example Stores"],
    )
    assert resolved.status_code == 200, resolved.text
    assert (resolved.json()["closed_by"], resolved.json()["outcome"]) == ("resolve", "dismissed")
    for name, node in nodes.items():
        still_open = client.get(f"/v1/profile/nodes/{node}/review-tasks", headers=owners[name])
        assert [
            t["reason"] for t in still_open.json() if t["reason"] == "confirm_financial_year"
        ] == []
    third = job.fn()
    assert isinstance(third, ScheduleRun)
    assert third.tasks_opened == 0, "closed tasks stay closed"
    closures = trail(client, owners["Example Stores"], "review_task.closed")
    assert [(c["subject"]["id"], c["after"]["closed_by"], c["reason"]) for c in closures] == [
        (stores_task, "resolve", "Example: dormant this year")
    ]
    snapshot = client.get(
        f"/v1/profile/nodes/{nodes['Example Traders']}/snapshot",
        params={"fy": "2027-28"},
        headers=owners["Example Traders"],
    ).json()
    assert snapshot["attributes"]["turnover_band"] == "2_crore_to_5_crore"
