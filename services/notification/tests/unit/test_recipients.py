from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, TenantId, UserId
from notification.application.recipients import (
    GetRecipient,
    RecipientRegistration,
    RegisterRecipient,
    RemoveRecipient,
)
from notification.domain.errors import InvalidAddressError, RecipientNotFoundError
from notification.domain.ids import RecipientId
from notification.domain.recipients import BusinessLink, DigestMode, RecipientRole
from notification.domain.repository import DirectoryEntry
from notification.infrastructure.memory import MemoryStore
from notification.testing import NOON_IST

TENANT = TenantId.new()
OTHER = TenantId.new()
BUSINESS = BusinessId.new()
WA = Channel.WHATSAPP
EMAIL = Channel.EMAIL


def registration(**changes: object) -> RecipientRegistration:
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "recipient_id": RecipientId.new(),
        "role": RecipientRole.OWNER,
        "user_id": UserId.new(),
        "language": "hi",
        "addresses": [(WA, "+91 98765 43210"), (EMAIL, "Owner@Example.com")],
        "businesses": [BusinessLink(BUSINESS, "Acme Traders")],
    }
    values.update(changes)
    return RecipientRegistration(**values)  # type: ignore[arg-type]


def test_registering_normalises_orders_and_writes_the_directory() -> None:
    store = MemoryStore()
    request = registration(
        addresses=[(WA, "919876543210"), (EMAIL, "Owner@Example.com"), (WA, "+91 98765 43210")]
    )
    registered = RegisterRecipient(store, clock=lambda: NOON_IST).run(request)
    assert [(a.channel, a.address, a.position) for a in registered.addresses] == [
        (WA, "+919876543210", 0),
        (EMAIL, "owner@example.com", 1),
    ], "normalised, in the order given, a repeat dropped"
    assert GetRecipient(store).run(TENANT, request.recipient_id) == registered
    with store.shared() as unit:
        assert unit.directory.lookup(WA, "+919876543210") == [
            DirectoryEntry(TENANT, request.recipient_id)
        ]
    assert store.work_index.tenants() == [TENANT]


def test_registering_again_replaces_everything_but_the_creation_time() -> None:
    store = MemoryStore()
    request = registration()
    first = RegisterRecipient(store, clock=lambda: NOON_IST).run(request)
    later = NOON_IST + timedelta(days=1)
    other_business = BusinessId.new()
    second = RegisterRecipient(store, clock=lambda: later).run(
        registration(
            recipient_id=request.recipient_id,
            role=RecipientRole.CA_STAFF,
            digest_mode=DigestMode.DAILY,
            org_label="Sharma & Co",
            addresses=[(EMAIL, "desk@sharma.example")],
            businesses=[BusinessLink(other_business, "Client A")],
        )
    )
    assert (second.created_at, second.updated_at) == (first.created_at, later)
    assert second.by_digest
    assert [a.address for a in second.addresses] == ["desk@sharma.example"]
    with store(TENANT) as unit:
        assert unit.recipients.for_business(BUSINESS) == []
        assert unit.recipients.for_business(other_business) == [second]
    with store.shared() as unit:
        assert unit.directory.lookup(WA, "+919876543210") == [], "the old number routes nowhere"
        assert unit.directory.lookup(EMAIL, "desk@sharma.example") == [
            DirectoryEntry(TENANT, request.recipient_id)
        ]


def test_recipients_of_a_business_and_tenants_apart() -> None:
    store = MemoryStore()
    register = RegisterRecipient(store, clock=lambda: NOON_IST)
    owner, staff = register.run(registration()), register.run(registration())
    register.run(registration(businesses=[BusinessLink(BusinessId.new())]))
    same_id = register.run(registration(tenant_id=OTHER, recipient_id=owner.id))
    with store(TENANT) as unit:
        followers = unit.recipients.for_business(BUSINESS)
    assert sorted(r.id.value for r in followers) == sorted([owner.id.value, staff.id.value])
    assert GetRecipient(store).run(OTHER, owner.id) == same_id, "one id in two tenants"
    assert GetRecipient(store).run(TENANT, owner.id) == owner
    with store.shared() as unit:
        entries = unit.directory.lookup(WA, "+919876543210")
    assert DirectoryEntry(OTHER, owner.id) in entries
    assert len(entries) == 4
    with store(OTHER) as unit, pytest.raises(ValueError, match="another tenant"):
        unit.recipients.save(owner)


def test_removing_a_recipient_clears_its_directory_entries() -> None:
    store = MemoryStore()
    registered = RegisterRecipient(store, clock=lambda: NOON_IST).run(registration())
    with pytest.raises(RecipientNotFoundError):
        RemoveRecipient(store).run(OTHER, registered.id)
    RemoveRecipient(store).run(TENANT, registered.id)
    with pytest.raises(RecipientNotFoundError):
        GetRecipient(store).run(TENANT, registered.id)
    with pytest.raises(RecipientNotFoundError):
        RemoveRecipient(store).run(TENANT, registered.id)
    with store.shared() as unit:
        assert unit.directory.lookup(WA, "+919876543210") == []


def test_an_address_that_is_not_one_registers_nothing() -> None:
    store = MemoryStore()
    request = registration(addresses=[(WA, "+919876543210"), (EMAIL, "nobody")])
    with pytest.raises(InvalidAddressError):
        RegisterRecipient(store).run(request)
    with pytest.raises(RecipientNotFoundError):
        GetRecipient(store).run(TENANT, request.recipient_id)


def body(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "user_id": str(uuid4()),
        "role": "owner",
        "language": "hi",
        "addresses": [
            {"channel": "whatsapp", "address": "+91 98765 43210"},
            {"channel": "email", "address": "owner@example.com"},
        ],
        "businesses": [{"business_id": str(BUSINESS), "label": "Acme Traders"}],
    }
    values.update(changes)
    return values


def test_the_recipient_routes_round_trip(client: TestClient) -> None:
    tenant = {"x-tenant-id": str(TENANT)}
    other = {"x-tenant-id": str(OTHER)}
    path = f"/v1/notification/recipients/{uuid4()}"
    put = client.put(path, json=body(), headers=tenant)
    assert put.status_code == 200, put.text
    stored = put.json()
    assert [a["address"] for a in stored["addresses"]] == ["+919876543210", "owner@example.com"]
    assert (stored["role"], stored["by_digest"], stored["digest_mode"]) == ("owner", False, "off")
    assert stored["businesses"] == [{"business_id": str(BUSINESS), "label": "Acme Traders"}]
    assert client.get(path, headers=tenant).json() == stored
    assert client.get(path, headers=other).status_code == 404, "another tenant sees nothing"
    assert client.delete(path, headers=other).status_code == 404
    updated = client.put(path, json=body(role="ca_admin", org_label="Sharma & Co"), headers=tenant)
    assert updated.json()["by_digest"] is True
    assert updated.json()["created_at"] == stored["created_at"]
    deleted = client.delete(path, headers=tenant)
    assert deleted.status_code == 204
    assert deleted.content == b""
    missing = client.get(path, headers=tenant)
    assert missing.status_code == 404
    assert missing.json()["type"].endswith(":notification-recipient-not-found")


def test_the_recipient_routes_refuse_what_they_cannot_store(client: TestClient) -> None:
    tenant = {"x-tenant-id": str(TENANT)}
    path = f"/v1/notification/recipients/{uuid4()}"
    for route in (("PUT", body()), ("GET", None), ("DELETE", None)):
        response = client.request(route[0], path, json=route[1])
        assert response.status_code == 401, route[0]
    bad_address = client.put(
        path, json=body(addresses=[{"channel": "email", "address": "nobody"}]), headers=tenant
    )
    assert bad_address.status_code == 422
    assert bad_address.json()["type"].endswith(":notification-address-invalid")
    twice = client.put(
        path,
        json=body(businesses=[{"business_id": str(BUSINESS)}, {"business_id": str(BUSINESS)}]),
        headers=tenant,
    )
    assert twice.status_code == 422
    assert client.put(path, json=body(role="auditor"), headers=tenant).status_code == 422
