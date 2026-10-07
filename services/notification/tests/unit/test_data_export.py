"""The tenant's data export: the use case on the memory store (only the asked tenant's rows, every
section present, pages joined) and ``GET /v1/notification/data-export`` in header and token
mode."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.ids import BusinessId, ObligationId, TenantId, UserId
from notification.application.export import EXPORT_PAGE_SIZE, ExportTenantData
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.domain.ids import RecipientId
from notification.domain.notification import Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ConsentSource, Suppression, SuppressionReason
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.repository import UnitOfWorkFactory, WorkEntry
from notification.infrastructure.memory import MemoryStore
from notification.main import build_app
from notification.testing import notification_settings
from notification.wiring import Wiring
from py_common.auth.testing import TestIssuer, bearer

TENANT = TenantId.new()
OTHER = TenantId.new()
BUSINESS = BusinessId.new()
WHEN = datetime(2000, 1, 3, 6, 30, tzinfo=UTC)
PHONE = "+919876543210"
OTHER_PHONE = "+919876543211"
STRANGER_PHONE = "+919876543212"
MAIL = "owner@example.com"
SECTIONS = {"recipients", "preferences", "notifications"}


def register(
    store: UnitOfWorkFactory,
    tenant: TenantId,
    addresses: list[tuple[Channel, str]],
    *,
    at: datetime = WHEN,
    recipient_id: RecipientId | None = None,
) -> RecipientId:
    recipient_id = recipient_id or RecipientId.new()
    RegisterRecipient(store, clock=lambda: at).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=recipient_id,
            role=RecipientRole.OWNER,
            user_id=UserId.new(),
            addresses=addresses,
            businesses=[BusinessLink(BUSINESS, "Example Traders")],
        )
    )
    return recipient_id


def notify(store: UnitOfWorkFactory, tenant: TenantId, n: int, *, at: datetime = WHEN) -> None:
    notification = Notification.queue(
        tenant_id=tenant,
        business_id=BUSINESS,
        obligation_id=ObligationId.new(),
        recipient_id=None,
        channel=Channel.WHATSAPP,
        address=PHONE,
        occasion=OccasionKind.REMINDER,
        template_key="obligation_due_soon",
        language="en",
        params={"title": f"Example obligation {n}", "steps": ["Reconcile", "File"]},
        dedupe_key=DedupeKey(f"{n:064x}"),
        now=at,
    )
    with store(tenant) as unit:
        assert unit.notifications.add_if_absent(notification)
        unit.work.add(WorkEntry.of(notification))


def fill(store: MemoryStore) -> None:
    """Two tenants: TENANT holds PHONE and MAIL, OTHER holds OTHER_PHONE and registered PHONE too;
    STRANGER_PHONE belongs to nobody. TENANT's user opted PHONE in on the web; MAIL was opted in
    through the API and OTHER_PHONE and STRANGER_PHONE by the WhatsApp keyword, which no tenant
    caused. PHONE also wrote to us and has a suppression."""
    register(store, TENANT, [(Channel.WHATSAPP, PHONE), (Channel.EMAIL, MAIL)])
    register(store, OTHER, [(Channel.WHATSAPP, OTHER_PHONE), (Channel.WHATSAPP, PHONE)])
    opt_in = SetOptIn(store, clock=lambda: WHEN)
    opt_in.run(
        Channel.WHATSAPP,
        PHONE,
        opted_in=True,
        source=ConsentSource.WEB_ONBOARDING,
        language="hi",
        set_for_tenant=TENANT,
    )
    opt_in.run(Channel.EMAIL, MAIL, opted_in=True, source=ConsentSource.API)
    for address in (OTHER_PHONE, STRANGER_PHONE):
        opt_in.run(Channel.WHATSAPP, address, opted_in=True, source=ConsentSource.WHATSAPP_KEYWORD)
    with store.shared() as unit:
        unit.preferences.record_inbound(Channel.WHATSAPP, PHONE, WHEN + timedelta(hours=1))
        unit.suppressions.add(
            Suppression(Channel.WHATSAPP, PHONE, SuppressionReason.MANUAL, WHEN, "test")
        )
    notify(store, TENANT, 1)
    notify(store, OTHER, 2)


def test_the_export_holds_only_the_tenants_rows_in_every_section() -> None:
    store = MemoryStore()
    fill(store)
    export = ExportTenantData(store, clock=lambda: WHEN).run(TENANT)
    assert (export.service, export.tenant_id, export.generated_at) == ("notification", TENANT, WHEN)
    assert set(export.sections) == SECTIONS
    [recipient] = export.sections["recipients"]
    assert recipient["tenant_id"] == str(TENANT.value)
    assert recipient["addresses"] == [
        {"channel": "whatsapp", "address": PHONE, "position": 0},
        {"channel": "email", "address": MAIL, "position": 1},
    ]
    assert recipient["businesses"] == [
        {"business_id": str(BUSINESS.value), "label": "Example Traders"}
    ]
    assert recipient["created_at"] == WHEN.isoformat()
    assert export.sections["preferences"] == [
        {
            "channel": "whatsapp",
            "address": PHONE,
            "opted_in": True,
            "language": "hi",
            "quiet_hours_start": "21:00",
            "quiet_hours_end": "08:00",
        }
    ], "only what the tenant's own web opt-in wrote; MAIL's came through the API"
    [notification] = export.sections["notifications"]
    assert notification["tenant_id"] == str(TENANT.value)
    assert notification["params"] == {
        "title": "Example obligation 1",
        "steps": ["Reconcile", "File"],
    }
    assert notification["state"] == "queued"
    assert "dedupe_key" not in notification
    text = repr(export.sections)
    assert str(OTHER.value) not in text
    assert OTHER_PHONE not in text
    assert STRANGER_PHONE not in text
    assert "suppress" not in text, "suppressions are not exported"


def test_another_tenant_holding_the_address_sees_no_preference_it_did_not_set() -> None:
    store = MemoryStore()
    fill(store)
    theirs = ExportTenantData(store, clock=lambda: WHEN).run(OTHER)
    held = [a["address"] for r in theirs.sections["recipients"] for a in r["addresses"]]
    assert sorted(held) == sorted([OTHER_PHONE, PHONE]), "its own recipient rows"
    assert theirs.sections["preferences"] == [], (
        "PHONE was set by TENANT's user and OTHER_PHONE by the keyword: neither is OTHER's"
    )
    text = repr(theirs.sections)
    assert "web_onboarding" not in text
    assert "whatsapp_keyword" not in text
    assert (WHEN + timedelta(hours=1)).isoformat() not in text, "when PHONE last wrote to us"


def test_a_keyword_opt_in_is_never_exported_to_a_tenant_that_registers_the_number() -> None:
    store = MemoryStore()
    SetOptIn(store, clock=lambda: WHEN).run(
        Channel.WHATSAPP,
        STRANGER_PHONE,
        opted_in=True,
        source=ConsentSource.WHATSAPP_KEYWORD,
        language="hi",
    )
    with store.shared() as unit:
        unit.preferences.record_inbound(Channel.WHATSAPP, STRANGER_PHONE, WHEN)
    register(store, OTHER, [(Channel.WHATSAPP, STRANGER_PHONE)])
    assert ExportTenantData(store).run(OTHER).sections["preferences"] == []


def test_an_empty_tenant_has_every_section_empty() -> None:
    store = MemoryStore()
    fill(store)
    export = ExportTenantData(store).run(TenantId.new())
    assert export.sections == {name: [] for name in SECTIONS}


def test_the_sections_are_read_a_page_at_a_time_and_joined_oldest_first() -> None:
    store = MemoryStore()
    phones = [f"+9198765432{n:02d}" for n in range(5)]
    for n, phone in enumerate(phones):
        register(store, TENANT, [(Channel.WHATSAPP, phone)], at=WHEN + timedelta(minutes=5 - n))
        SetOptIn(store, clock=lambda: WHEN).run(
            Channel.WHATSAPP,
            phone,
            opted_in=False,
            source=ConsentSource.WEB_SETTINGS,
            set_for_tenant=TENANT,
        )
        notify(store, TENANT, n, at=WHEN + timedelta(minutes=5 - n))
    assert EXPORT_PAGE_SIZE == 500
    export = ExportTenantData(store, page_size=2).run(TENANT)
    recipients = export.sections["recipients"]
    assert [r["addresses"][0]["address"] for r in recipients] == list(reversed(phones))
    assert [p["address"] for p in export.sections["preferences"]] == phones
    created = [n["created_at"] for n in export.sections["notifications"]]
    assert len(created) == 5
    assert created == sorted(created)
    assert export.sections == ExportTenantData(store).run(TENANT).sections


def test_a_page_size_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="page_size"):
        ExportTenantData(MemoryStore(), page_size=0)


# ---------------------------------------------------------------- the route

ROUTE = "/v1/notification/data-export"
ISSUER = TestIssuer()


def filled(client: TestClient) -> TestClient:
    wiring: Wiring = client.app.state.wiring  # type: ignore[attr-defined]
    assert isinstance(wiring.unit_of_work, MemoryStore)
    fill(wiring.unit_of_work)
    return client


@pytest.fixture
def header_mode() -> Iterator[TestClient]:
    with TestClient(build_app(notification_settings())) as client:
        yield filled(client)


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    settings = notification_settings(**ISSUER.settings_overrides("token"))
    with TestClient(build_app(settings)) as client:
        yield filled(client)


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def test_header_mode_exports_the_tenant_the_header_names(header_mode: TestClient) -> None:
    response = header_mode.get(ROUTE, headers={"x-tenant-id": str(TENANT)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["service"], body["tenant_id"]) == ("notification", str(TENANT.value))
    assert datetime.fromisoformat(body["generated_at"]).tzinfo is not None
    assert set(body["sections"]) == SECTIONS
    assert [p["address"] for p in body["sections"]["preferences"]] == [PHONE]
    missing = header_mode.get(ROUTE)
    assert (missing.status_code, problem(missing)) == (401, "notification-tenant-required")


def bound(tenant: TenantId, audience: str = "notification") -> str:
    """Identity's export token for ``tenant``, addressed to ``audience``."""
    return ISSUER.service("identity", [Scope.DATA_EXPORT], acts_for=tenant, audience=audience)


def test_token_mode_exports_to_a_tenant_admin_or_a_service_with_data_export(
    token_mode: TestClient,
) -> None:
    as_tenant = {"x-tenant-id": str(TENANT)}
    allowed = (
        bearer(ISSUER.user(TENANT, [Role.OWNER])),
        bearer(ISSUER.user(TENANT, [Role.CA_ADMIN], mfa=True)),
        {**bearer(bound(TENANT)), **as_tenant},
        bearer(bound(TENANT)),
    )
    for headers in allowed:
        response = token_mode.get(ROUTE, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["tenant_id"] == str(TENANT.value)
        assert len(response.json()["sections"]["recipients"]) == 1
    refused = (
        bearer(ISSUER.user(TENANT, [Role.STAFF])),
        {**bearer(ISSUER.service("identity", [Scope.TENANT_ACT])), **as_tenant},
        {**bearer(ISSUER.service("worker", [Scope.DATA_EXPORT, Scope.TENANT_ACT])), **as_tenant},
        {**bearer(bound(TENANT, "profile")), **as_tenant},
    )
    for headers in refused:
        response = token_mode.get(ROUTE, headers=headers)
        assert (response.status_code, problem(response)) == (403, "auth-forbidden")
    other = token_mode.get(
        ROUTE, headers={**bearer(ISSUER.user(TENANT, [Role.OWNER])), "x-tenant-id": str(OTHER)}
    )
    assert (other.status_code, problem(other)) == (403, "auth-tenant-mismatch")
    replayed = token_mode.get(ROUTE, headers={**bearer(bound(TENANT)), "x-tenant-id": str(OTHER)})
    assert (replayed.status_code, problem(replayed)) == (403, "auth-tenant-mismatch")
    unnamed = token_mode.get(ROUTE, headers=bearer(ISSUER.service("identity", [Scope.TENANT_ACT])))
    assert (unnamed.status_code, problem(unnamed)) == (401, "notification-tenant-required")
