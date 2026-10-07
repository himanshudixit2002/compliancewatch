"""The audit trail: the entries identity writes, the route that reads them in the caller's scope,
and ``identity-admin audit-export``."""

import base64
import hashlib
import io
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Principal, Role
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId, UserId
from identity.admin import main as admin_main
from identity.api.audit import CURSOR_SCOPE
from identity.application.audit import ExportAuditTrail, ReadAuditTrail, settled_until
from identity.application.bootstrap import BootstrapInternalTenant
from identity.domain.audit import AuditQuery, AuditScope, readable
from identity.domain.repository import UnitOfWork
from identity.domain.tenancy import Contact, Tenant, TenantKind, User
from identity.infrastructure.memory import MemoryAuditReader, MemoryStore
from identity.main import build_app
from identity.testing import DEV_CLIENT_SECRET, identity_settings
from py_common.audit.testing import audit_entry
from py_common.auth.errors import AuthForbiddenError
from py_common.auth.testing import bearer
from py_common.pagination import CURSOR_VERSION

AUDIT = "/v1/identity/audit"
OWNER_PHONE = "+919876543210"
OTHER_OWNER_PHONE = "+919811111111"
STAFF_PHONE = "+919812345678"
ADMIN_EMAIL = "admin@example.org"
AT = datetime(2000, 1, 3, 9, 0, tzinfo=UTC)


def provider_token(client: TestClient, *, phone: str = "", email: str = "", aal: str = "") -> str:
    body: dict[str, str] = {"phone": phone} if phone else {"email": email}
    if aal:
        body["aal"] = aal
    response = client.post("/v1/identity/dev/provider-tokens", json=body)
    assert response.status_code == 200, response.text
    token: str = response.json()["provider_token"]
    return token


def sign_up(client: TestClient, phone: str, name: str) -> dict[str, Any]:
    created = client.post(
        "/v1/identity/tenants",
        json={
            "kind": "business",
            "name": name,
            "provider_token": provider_token(client, phone=phone),
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def session(client: TestClient, **contact: str) -> dict[str, str]:
    exchanged = client.post(
        "/v1/identity/sessions", json={"provider_token": provider_token(client, **contact)}
    )
    assert exchanged.status_code == 200, exchanged.text
    return bearer(exchanged.json()["access_token"])


def store_of(app: FastAPI) -> MemoryStore:
    store = app.state.wiring.unit_of_work
    assert isinstance(store, MemoryStore)
    return store


def actions(page: dict[str, Any]) -> list[str]:
    return [item["action"] for item in page["items"]]


@pytest.fixture
def app() -> FastAPI:
    return build_app(identity_settings(auth_mode="token"))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------- what identity writes


def test_a_team_and_a_consent_write_their_entries_and_the_owner_reads_them(
    client: TestClient,
) -> None:
    created = sign_up(client, OWNER_PHONE, "Example Traders")
    tenant, owner_id = created["tenant"]["id"], created["user"]["id"]
    owner = bearer(created["session"]["access_token"])
    staff = client.post(
        "/v1/identity/users", json={"phone": STAFF_PHONE, "roles": ["staff"]}, headers=owner
    ).json()
    roles = client.put(
        f"/v1/identity/users/{staff['id']}/roles",
        json={"roles": ["compliance_lead", "staff"]},
        headers=owner,
    )
    assert roles.status_code == 200, roles.text
    assert (
        client.post(f"/v1/identity/users/{staff['id']}/disable", headers=owner).status_code == 200
    )
    consent = client.post(
        "/v1/identity/consents",
        json={
            "subject": owner_id,
            "purpose": "whatsapp_reminders",
            "granted": True,
            "source": "web_settings",
            "notice_version": "2000-01",
        },
        headers=owner,
    )
    assert consent.status_code == 201, consent.text

    page = client.get(AUDIT, headers=owner)
    assert page.status_code == 200, page.text
    body = page.json()
    assert actions(body) == [
        "consent.recorded",
        "user.disabled",
        "user.roles_changed",
        "user.invited",
        "tenant.created",
    ], "newest first"
    assert {item["tenant_id"] for item in body["items"]} == {tenant}
    by_action = {item["action"]: item for item in body["items"]}
    created_entry = by_action["tenant.created"]
    assert created_entry["subject"] == {"type": "tenant", "id": tenant}
    assert created_entry["actor"] == {"kind": "user", "id": owner_id, "label": "owner"}
    assert created_entry["after"]["first_user_roles"] == ["owner"]
    assert by_action["user.invited"]["after"] == {"roles": ["staff"], "status": "active"}
    assert by_action["user.invited"]["actor"]["id"] == owner_id
    assert (
        by_action["user.roles_changed"]["before"],
        by_action["user.roles_changed"]["after"],
    ) == (
        {"roles": ["staff"]},
        {"roles": ["compliance_lead", "staff"]},
    )
    assert by_action["user.disabled"]["after"] == {"status": "disabled"}
    recorded = by_action["consent.recorded"]
    assert recorded["after"]["purpose"] == "whatsapp_reminders"
    assert recorded["after"]["granted"] is True
    assert recorded["after"]["subject"] == owner_id
    assert all(STAFF_PHONE not in json.dumps(item) for item in body["items"]), "no contact"
    assert body["next_cursor"] is None


def test_a_consent_for_a_phone_number_keeps_it_masked(client: TestClient) -> None:
    created = sign_up(client, OWNER_PHONE, "Example Traders")
    owner = bearer(created["session"]["access_token"])
    client.post(
        "/v1/identity/consents",
        json={
            "subject": "+919800000001",
            "purpose": "whatsapp_reminders",
            "granted": False,
            "source": "web_settings",
        },
        headers=owner,
    )
    item = client.get(AUDIT, params={"action": "consent.recorded"}, headers=owner).json()
    assert item["items"][0]["after"]["subject"] == "[PHONE]"


# ---------------------------------------------------------------- who reads what


def bootstrap_admin(app: FastAPI) -> TenantId:
    wiring = app.state.wiring
    tenant, _ = BootstrapInternalTenant(wiring.unit_of_work, wiring.provider).run(
        "Example regulatory team", Contact(email=ADMIN_EMAIL)
    )
    return tenant.id


def test_tenants_never_see_each_other_or_the_platform_and_the_regulatory_team_sees_both(
    app: FastAPI, client: TestClient
) -> None:
    first = sign_up(client, OWNER_PHONE, "Example Traders")
    second = sign_up(client, OTHER_OWNER_PHONE, "Example Stores")
    internal = bootstrap_admin(app)
    platform = audit_entry(
        tenant_id=None,
        action="rule_version.published",
        subject_type="rule_version",
        actor=AuditActor.system("rulebook"),
        occurred_at=datetime.now(UTC),
    )
    with store_of(app)(None) as uow:
        uow.audit.write(platform)

    owner = bearer(first["session"]["access_token"])
    seen = client.get(AUDIT, headers=owner).json()["items"]
    assert {item["tenant_id"] for item in seen} == {first["tenant"]["id"]}
    assert second["tenant"]["id"] not in json.dumps(seen)
    assert (
        client.get(AUDIT, params={"subject_type": "rule_version"}, headers=owner).json()["items"]
        == []
    ), "a tenant role never reads a platform row"

    admin = session(client, email=ADMIN_EMAIL, aal="aal2")
    regulatory = client.get(AUDIT, headers=admin).json()["items"]
    assert {item["tenant_id"] for item in regulatory} == {None, str(internal)}
    assert str(platform.entry_id) in {item["id"] for item in regulatory}
    assert {first["tenant"]["id"], second["tenant"]["id"]}.isdisjoint(
        {item["tenant_id"] for item in regulatory}
    )


def test_staff_services_and_callers_without_a_token_are_refused(client: TestClient) -> None:
    created = sign_up(client, OWNER_PHONE, "Example Traders")
    owner = bearer(created["session"]["access_token"])
    client.post(
        "/v1/identity/users", json={"phone": STAFF_PHONE, "roles": ["staff"]}, headers=owner
    )
    staff = session(client, phone=STAFF_PHONE)
    refused = client.get(AUDIT, headers=staff)
    assert refused.status_code == 403
    assert refused.json()["type"].endswith(":auth-forbidden")

    issued = client.post(
        "/v1/identity/service-tokens",
        json={"client_id": "obligation", "client_secret": DEV_CLIENT_SECRET},
    )
    service = bearer(issued.json()["access_token"])
    as_service = client.get(AUDIT, headers={**service, "x-tenant-id": created["tenant"]["id"]})
    assert as_service.status_code == 403
    assert client.get(AUDIT).status_code == 401


def test_a_revoked_session_reads_nothing(client: TestClient) -> None:
    created = sign_up(client, OWNER_PHONE, "Example Traders")
    owner = bearer(created["session"]["access_token"])
    second = client.post(
        "/v1/identity/users", json={"phone": STAFF_PHONE, "roles": ["owner"]}, headers=owner
    ).json()
    as_second = session(client, phone=STAFF_PHONE)
    client.put(
        f"/v1/identity/users/{created['user']['id']}/roles",
        json={"roles": ["staff"]},
        headers=as_second,
    )
    assert second["roles"] == ["owner"]
    assert client.get(AUDIT, headers=owner).status_code == 401


def test_header_mode_reads_the_named_tenant_and_dual_mode_needs_a_token() -> None:
    header_app = build_app(identity_settings())
    with TestClient(header_app) as client:
        created = sign_up(client, OWNER_PHONE, "Example Traders")
        tenant = created["tenant"]["id"]
        with store_of(header_app)(None) as uow:
            uow.audit.write(audit_entry(tenant_id=None, occurred_at=datetime.now(UTC)))
        page = client.get(AUDIT, headers={"x-tenant-id": tenant})
        assert page.status_code == 200, page.text
        assert actions(page.json()) == ["tenant.created"], "never the platform's entries"
        assert client.get(AUDIT).status_code == 401, "no tenant named"
    with TestClient(build_app(identity_settings(auth_mode="dual"))) as dual:
        created = sign_up(dual, OWNER_PHONE, "Example Traders")
        anonymous = dual.get(AUDIT, headers={"x-tenant-id": created["tenant"]["id"]})
        assert anonymous.status_code == 401


# ---------------------------------------------------------------- pages and filters


def test_pages_filters_and_problems(app: FastAPI, client: TestClient) -> None:
    created = sign_up(client, OWNER_PHONE, "Example Traders")
    tenant = TenantId.parse(created["tenant"]["id"])
    owner = bearer(created["session"]["access_token"])
    written = [
        audit_entry(
            tenant_id=tenant,
            action="example.thing.change",
            subject_id=f"thing-{index}",
            occurred_at=AT + timedelta(hours=index),
        )
        for index in range(5)
    ]
    with store_of(app)(tenant) as uow:
        for entry in written:
            uow.audit.write(entry)

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"action": "example.thing.change", "limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = client.get(AUDIT, params=params, headers=owner).json()
        seen += [item["subject"]["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"thing-{index}" for index in reversed(range(5))]

    ranged = client.get(
        AUDIT,
        params={
            "from": (AT + timedelta(hours=1)).isoformat(),
            "to": (AT + timedelta(hours=3)).isoformat(),
        },
        headers=owner,
    ).json()
    assert [item["subject"]["id"] for item in ranged["items"]] == ["thing-2", "thing-1"]
    one = client.get(
        AUDIT, params={"subject_type": "thing", "subject_id": "thing-3"}, headers=owner
    ).json()
    assert [item["subject"]["id"] for item in one["items"]] == ["thing-3"]

    problems: tuple[dict[str, str | int], ...] = (
        {"cursor": "not-a-cursor"},
        {"from": AT.isoformat(), "to": AT.isoformat()},
        {"from": "2000-01-03T09:00:00"},
        {"limit": 201},
    )
    for problem in problems:
        refused = client.get(AUDIT, params=problem, headers=owner)
        assert refused.status_code == 422, problem


def test_the_memory_reader_holds_the_policies_rule() -> None:
    tenant, other = TenantId.new(), TenantId.new()
    mine, theirs, platform = (
        audit_entry(tenant_id=tenant),
        audit_entry(tenant_id=other),
        audit_entry(tenant_id=None),
    )
    assert [readable(AuditScope.TENANT, tenant, e) for e in (mine, theirs, platform)] == [
        True,
        False,
        False,
    ]
    assert [readable(AuditScope.REGULATORY, tenant, e) for e in (mine, theirs, platform)] == [
        True,
        False,
        True,
    ]
    assert all(readable(AuditScope.EXPORT, None, e) for e in (mine, theirs, platform))
    assert not readable(AuditScope.TENANT, None, mine)
    store = MemoryStore()
    reader = MemoryAuditReader(store)
    store.audit += [mine, theirs, platform]
    assert set(reader.page(AuditScope.REGULATORY, tenant, AuditQuery())) == {mine, platform}
    assert reader.page(AuditScope.TENANT, other, AuditQuery()) == [theirs]
    with pytest.raises(InvariantViolationError, match="limit"):
        AuditQuery(limit=0)


# ---------------------------------------------------------------- the export


def run_admin(store: MemoryStore, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = admin_main(list(argv), unit_of_work=store, reader=MemoryAuditReader(store), out=out)
    return code, out.getvalue()


def test_audit_export_writes_ndjson_with_its_manifest_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = MemoryStore()
    tenant = TenantId.new()
    inside = [
        audit_entry(tenant_id=tenant, occurred_at=AT),
        audit_entry(tenant_id=None, occurred_at=AT + timedelta(days=1)),
    ]
    outside = audit_entry(tenant_id=tenant, occurred_at=AT + timedelta(days=40))
    store.audit += [inside[1], outside, inside[0]]
    out = tmp_path / "export"

    code, printed = run_admin(
        store, "audit-export", "--from", "2000-01-01", "--to", "2000-02-01", "--out", str(out)
    )
    assert code == 0, capsys.readouterr().err
    assert "object-locked bucket" in capsys.readouterr().err
    raw = (out / "audit-events.ndjson").read_bytes()
    lines = [json.loads(line) for line in raw.decode().splitlines()]
    assert [line["id"] for line in lines] == [str(entry.entry_id) for entry in inside]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest == json.loads(printed)
    assert manifest["sha256"] == hashlib.sha256(raw).hexdigest()
    assert (manifest["count"], manifest["range"]) == (
        2,
        {"from": "2000-01-01T00:00:00+00:00", "to": "2000-02-01T00:00:00+00:00"},
    )
    exported = [entry for entry in store.audit if entry.action == "audit.exported"]
    assert len(exported) == 1
    assert (exported[0].tenant_id, exported[0].actor.label) == (None, "system:identity-admin")
    assert exported[0].after == {"count": 2, "sha256": manifest["sha256"]}

    again, _ = run_admin(
        store, "audit-export", "--from", "2000-01-01", "--to", "2000-02-01", "--out", str(out)
    )
    assert again == 1, "an existing export is never overwritten"
    backwards, _ = run_admin(
        store,
        "audit-export",
        "--from",
        "2000-02-01",
        "--to",
        "2000-01-01",
        "--out",
        str(tmp_path / "other"),
    )
    assert backwards == 1


def test_audit_export_takes_instants_with_or_without_a_zone(tmp_path: Path) -> None:
    store = MemoryStore()
    entry = audit_entry(tenant_id=None, occurred_at=AT)
    store.audit.append(entry)
    manifest = ExportAuditTrail(MemoryAuditReader(store), store).run(
        AT, AT + timedelta(seconds=1), tmp_path
    )
    assert manifest.count == 1
    code, printed = run_admin(
        store,
        "audit-export",
        "--from",
        "2000-01-03T09:00:00",
        "--to",
        "2000-01-03T16:00:00+05:30",
        "--out",
        str(tmp_path / "zoned"),
    )
    assert code == 0
    assert json.loads(printed)["range"]["to"] == "2000-01-03T16:00:00+05:30"
    with pytest.raises(SystemExit):
        run_admin(store, "audit-export", "--from", "yesterday", "--to", "2000-01-01", "--out", "x")


def test_service_clients_created_and_revoked_by_the_cli_are_audited() -> None:
    store = MemoryStore()
    assert (
        run_admin(store, "service-client", "create", "--id", "example", "--scope", "llm:call")[0]
        == 0
    )
    assert run_admin(store, "service-client", "revoke", "--id", "example")[0] == 0
    assert run_admin(store, "service-client", "revoke", "--id", "example")[0] == 0
    entries: list[AuditEntry] = store.audit
    assert [(e.action, e.tenant_id, e.subject_id, e.actor.label) for e in entries] == [
        ("service_client.created", None, "example", "system:identity-admin"),
        ("service_client.revoked", None, "example", "system:identity-admin"),
    ], "a second revoke changes nothing and writes nothing"
    assert entries[0].after == {"scopes": ("llm:call",)}


# ---------------------------------------------------------------- review findings


def test_a_cursor_with_a_time_of_no_zone_is_a_bad_cursor(client: TestClient) -> None:
    created = sign_up(client, OWNER_PHONE, "Example Traders")
    owner = bearer(created["session"]["access_token"])
    payload = {
        "k": {"at": "2000-01-03T09:00:00", "id": str(uuid4())},
        "s": CURSOR_SCOPE,
        "v": CURSOR_VERSION,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    refused = client.get(AUDIT, params={"cursor": cursor}, headers=owner)
    assert refused.status_code == 422
    assert refused.json()["type"].endswith("pagination-cursor-invalid")


def test_the_regulatory_scope_needs_the_internal_tenant_as_well_as_the_role() -> None:
    store = MemoryStore()
    reading = ReadAuditTrail(MemoryAuditReader(store), store)

    def member(kind: TenantKind, roles: set[Role]) -> tuple[Principal, TenantId]:
        tenant = Tenant(TenantId.new(), kind, "Example Tenant", AT)
        user = User(
            UserId.new(),
            tenant.id,
            "example-provider",
            f"subject-{len(store.users)}",
            Contact(email=f"person{len(store.users)}@example.com"),
            frozenset(roles),
            AT,
            AT,
        )
        store.tenants[tenant.id] = tenant
        store.users[user.id] = user
        return Principal.user(user.id, tenant.id, roles), tenant.id

    assert reading.scope_for(*member(TenantKind.INTERNAL, {Role.ADMIN})) is AuditScope.REGULATORY
    # A customer tenant whose user somehow holds a regulatory role never reads the platform's rows.
    assert (
        reading.scope_for(*member(TenantKind.BUSINESS, {Role.ADMIN, Role.OWNER}))
        is AuditScope.TENANT
    )
    with pytest.raises(AuthForbiddenError):
        reading.scope_for(*member(TenantKind.BUSINESS, {Role.ANALYST}))


class FailingReader:
    """A reader whose export breaks after its first entry, as a dropped connection would."""

    def __init__(self, entry: AuditEntry) -> None:
        self._entry = entry

    def page(self, scope: AuditScope, tenant_id: TenantId | None, query: AuditQuery) -> list[Any]:
        return []

    def export(self, since: datetime, until: datetime) -> Iterator[AuditEntry]:
        yield self._entry
        raise RuntimeError("the connection dropped")


def test_a_failed_read_leaves_no_files_and_no_entry(tmp_path: Path) -> None:
    store = MemoryStore()
    out = tmp_path / "export"
    export = ExportAuditTrail(FailingReader(audit_entry(tenant_id=None, occurred_at=AT)), store)
    with pytest.raises(RuntimeError, match="dropped"):
        export.run(AT, AT + timedelta(days=1), out)
    assert list(out.iterdir()) == []
    assert store.audit == []
    retried = ExportAuditTrail(MemoryAuditReader(store), store).run(AT, AT + timedelta(days=1), out)
    assert retried.count == 0, "the empty directory takes the export again"


def test_a_failed_audit_entry_leaves_no_files(tmp_path: Path) -> None:
    store = MemoryStore()
    store.audit.append(audit_entry(tenant_id=None, occurred_at=AT))

    def database_down(tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]:
        raise RuntimeError("the database is down")

    out = tmp_path / "export"
    with pytest.raises(RuntimeError, match="database is down"):
        ExportAuditTrail(MemoryAuditReader(store), database_down).run(
            AT, AT + timedelta(days=1), out
        )
    assert list(out.iterdir()) == [], "no export without its audit.exported entry"


def test_the_export_refuses_any_file_and_never_overwrites_a_partial_one(tmp_path: Path) -> None:
    store = MemoryStore()
    export = ExportAuditTrail(MemoryAuditReader(store), store)
    used = tmp_path / "used"
    used.mkdir()
    (used / "notes.txt").write_text("an operator's note\n")
    with pytest.raises(InvariantViolationError, match="not empty"):
        export.run(AT, AT + timedelta(days=1), used)

    # Another export racing into the same directory holds the partial file already.
    racing = tmp_path / "racing"
    racing.mkdir()
    real_iterdir = Path.iterdir

    def empty_then_taken(path: Path) -> Iterator[Path]:
        if path == racing:
            (racing / "audit-events.ndjson.partial").write_bytes(b"theirs\n")
            return iter(())
        return real_iterdir(path)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "iterdir", empty_then_taken)
        with pytest.raises(FileExistsError):
            export.run(AT, AT + timedelta(days=1), racing)
    assert (racing / "audit-events.ndjson.partial").read_bytes() == b"theirs\n"
    assert sorted(path.name for path in racing.iterdir()) == ["audit-events.ndjson.partial"]
    assert store.audit == []


def test_the_default_cut_waits_two_days_for_late_rows() -> None:
    assert settled_until(datetime(2000, 2, 3, 0, 30, tzinfo=UTC)) == datetime(
        2000, 2, 1, tzinfo=UTC
    ), "on the 3rd the month before is settled"
    assert settled_until(datetime(2000, 2, 2, 23, 59, tzinfo=UTC)) == datetime(
        2000, 1, 31, tzinfo=UTC
    ), "on the 2nd its last day is not"
    assert settled_until(
        datetime(2000, 2, 3, 3, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    ) == datetime(2000, 1, 31, tzinfo=UTC), "the cut is taken in UTC"
