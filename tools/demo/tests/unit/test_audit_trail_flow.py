"""The audit trail across services, read through identity with the roles that may read it.

Every service writes its audit entries to the one table, ``audit.event``; identity alone reads
it (``GET /v1/identity/audit``). Here the services run in one process on their memory stores, and
the stores share one audit log, as their units of work share the table: identity's (a consent),
profile's (a registration and an attribute change), the rulebook's (a publish, through its use
cases) and the engine's (the global fan-out hold, set and released). Identity, profile and the
engine run in token mode and trust the keys identity publishes.

The trail then answers each reader in their scope: the owner sees their tenant's consent and
profile changes and nothing of another tenant or of the platform; another tenant's owner sees
only theirs; the regulatory team's admin sees the publish and the fan-out controls, the
platform's entries, and no tenant's but their own. Nothing here reaches a real identity provider
or a regulator.
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Final
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from applicability_engine.infrastructure.memory import MemoryStore as EngineStore
from applicability_engine.main import build_app as build_engine
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import MemoryProfiles, MemoryRulebook
from applicability_engine.wiring import Readers
from domain_kernel.audit import AuditEntry
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import SourceId, UserId
from identity.application.bootstrap import BootstrapInternalTenant
from identity.domain.tenancy import Contact
from identity.infrastructure.memory import MemoryStore as IdentityStore
from identity.main import build_app as build_identity
from identity.testing import identity_settings
from profile_service.infrastructure.memory import MemoryStore as ProfileStore
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from py_common.auth.testing import bearer
from rulebook.application.documents import RegisterDocument
from rulebook.application.publication import (
    AddCitations,
    ApproveVersion,
    CitationInput,
    PublishVersion,
    SubmitForReview,
)
from rulebook.domain.documents import StoredDocument
from rulebook.infrastructure.memory import MemoryKnowledgeStore

IDENTITY: Final = "/v1/identity"
AUDIT: Final = f"{IDENTITY}/audit"
OWNER_PHONE: Final = "+919876543210"
OTHER_PHONE: Final = "+919812345678"
ADMIN_EMAIL: Final = "admin@example.org"
REGISTRATION: Final = {
    "gstin": "29ABCDE1234F1Z5",
    "name": "Example Traders Bengaluru",
    "entity_name": "Example Traders",
}
HOLD: Final = "/v1/applicability-engine/fan-out-hold"
TEXT: Final = "Example notice: the example monthly return for June 2000 is due on the 20th day."
QUOTE: Final = "the example monthly return for June 2000 is due on the 20th day"
ANALYST: Final = UserId(UUID(int=0xA1))
REVIEWER: Final = UserId(UUID(int=0xA2))


@pytest.fixture
def identity() -> Iterator[TestClient]:
    with TestClient(build_identity(identity_settings(auth_mode="token"))) as client:
        yield client


def store_of[S](client: TestClient, kind: type[S]) -> S:
    app = client.app
    assert isinstance(app, FastAPI)
    store = app.state.wiring.unit_of_work
    assert isinstance(store, kind)
    return store


def shared_log(identity: TestClient) -> list[AuditEntry]:
    """The one audit log: identity's, which every other store writes to as well."""
    log: list[AuditEntry] = store_of(identity, IdentityStore).audit
    return log


@pytest.fixture
def profile(identity: TestClient) -> Iterator[TestClient]:
    settings = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="memory",
        auth_mode="token",
        auth_jwks_json=SecretStr(identity.get(f"{IDENTITY}/.well-known/jwks.json").text),
    )
    with TestClient(build_profile(settings)) as client:
        store_of(client, ProfileStore).audit = shared_log(identity)
        yield client


@pytest.fixture
def engine(identity: TestClient) -> Iterator[TestClient]:
    settings = ApplicabilityEngineSettings(
        _env_file=None,
        service_name="applicability-engine",
        applicability_engine_store="memory",
        auth_mode="token",
        auth_jwks_json=SecretStr(identity.get(f"{IDENTITY}/.well-known/jwks.json").text),
    )
    readers = Readers(profiles=MemoryProfiles(), rulebook=MemoryRulebook())
    with TestClient(build_engine(settings, readers=readers)) as client:
        store_of(client, EngineStore).audit = shared_log(identity)
        yield client


def provider_token(identity: TestClient, **contact: str) -> str:
    issued = identity.post(f"{IDENTITY}/dev/provider-tokens", json=contact)
    assert issued.status_code == 200, issued.text
    token: str = issued.json()["provider_token"]
    return token


def sign_up(identity: TestClient, phone: str, name: str) -> dict[str, Any]:
    created = identity.post(
        f"{IDENTITY}/tenants",
        json={
            "kind": "business",
            "name": name,
            "provider_token": provider_token(identity, phone=phone),
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def regulatory_admin(identity: TestClient) -> tuple[str, dict[str, str]]:
    """The internal tenant, set up as ``identity-admin bootstrap-internal`` does, and its admin's
    session, signed in with a second factor."""
    app = identity.app
    assert isinstance(app, FastAPI)
    wiring = app.state.wiring
    tenant, _ = BootstrapInternalTenant(wiring.unit_of_work, wiring.provider).run(
        "Example regulatory team", Contact(email=ADMIN_EMAIL)
    )
    exchanged = identity.post(
        f"{IDENTITY}/sessions",
        json={"provider_token": provider_token(identity, email=ADMIN_EMAIL, aal="aal2")},
    )
    assert exchanged.status_code == 200, exchanged.text
    return str(tenant.id), bearer(exchanged.json()["access_token"])


def publish_a_rule(log: list[AuditEntry]) -> str:
    """A synthetic rule version cited, submitted, approved and published by two people of the
    regulatory team, through the rulebook's use cases on a store writing to ``log``."""
    store = MemoryKnowledgeStore(audit=log)
    digest = hashlib.sha256(b"example-notice").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="EXAMPLE",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/example-notice.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=datetime(2000, 6, 1, tzinfo=UTC),
            published_at=date(2000, 6, 1),
        ),
        [Clause("en.p1", TEXT)],
    )
    _, version = store.add_rule(
        "example_monthly_return",
        title="Example monthly return",
        specification={"attribute": "registration_type", "operator": "eq", "value": "regular"},
        effective_from=date(2000, 7, 1),
    )
    AddCitations(store).run(version, [CitationInput(clause_id_for(document_id, "en.p1"), QUOTE)])
    SubmitForReview(store).run(version, actor_id=ANALYST)
    ApproveVersion(store).run(version, actor_id=REVIEWER)
    PublishVersion(store, enabled=True).run(version, actor_id=REVIEWER)
    return str(version)


def trail(identity: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    page = identity.get(AUDIT, params={"limit": 200}, headers=headers)
    assert page.status_code == 200, page.text
    items: list[dict[str, Any]] = page.json()["items"]
    return items


def test_each_service_writes_the_trail_and_each_reader_sees_only_their_scope(
    identity: TestClient, profile: TestClient, engine: TestClient
) -> None:
    owner_signed_up = sign_up(identity, OWNER_PHONE, "Example Traders")
    tenant = owner_signed_up["tenant"]["id"]
    owner = bearer(owner_signed_up["session"]["access_token"])
    other_signed_up = sign_up(identity, OTHER_PHONE, "Example Stores")
    other = bearer(other_signed_up["session"]["access_token"])
    internal, admin = regulatory_admin(identity)

    # A consent (identity), a registration and an attribute change (profile).
    consent = identity.post(
        f"{IDENTITY}/consents",
        json={
            "subject": owner_signed_up["user"]["id"],
            "purpose": "whatsapp_reminders",
            "granted": True,
            "source": "web_settings",
            "notice_version": "2000-01",
        },
        headers=owner,
    )
    assert consent.status_code == 201, consent.text
    registered = profile.post("/v1/profile/registrations", json=REGISTRATION, headers=owner)
    assert registered.status_code == 201, registered.text
    node = registered.json()["id"]
    changed = profile.put(
        f"/v1/profile/nodes/{node}/attributes",
        json={"changes": [{"key": "registration_type", "value": "regular"}]},
        headers=owner,
    )
    assert changed.status_code == 200, changed.text

    # A publish (rulebook) and a fan-out control (engine), both of the platform.
    version = publish_a_rule(shared_log(identity))
    held = engine.put(
        HOLD,
        json={"held": True, "reason": "Example hold before a publish (synthetic)"},
        headers=admin,
    )
    assert held.status_code == 200, held.text
    released = engine.put(HOLD, json={"held": False}, headers=admin)
    assert released.status_code == 200, released.text

    # The owner: their tenant's consent and profile changes, nothing else.
    mine = trail(identity, owner)
    actions = [item["action"] for item in mine]
    assert "consent.recorded" in actions
    assert "profile_node.registered" in actions
    attributes = [item for item in mine if item["action"] == "profile_node.attributes_changed"]
    assert [item["subject"]["id"] for item in attributes] == [node]
    assert attributes[0]["actor"] == {
        "kind": "user",
        "id": owner_signed_up["user"]["id"],
        "label": "owner",
    }
    assert {item["tenant_id"] for item in mine} == {tenant}, "no other tenant, no platform row"

    # The other tenant's owner: their own sign-up only.
    theirs = trail(identity, other)
    assert [item["action"] for item in theirs] == ["tenant.created"]
    assert {item["tenant_id"] for item in theirs} == {other_signed_up["tenant"]["id"]}

    # The regulatory admin: the platform's entries and the internal tenant's, no customer's.
    platform = trail(identity, admin)
    published = [item for item in platform if item["action"] == "rule_version.published"]
    assert [item["subject"] for item in published] == [{"type": "rule_version", "id": version}]
    assert published[0]["actor"]["id"] == str(REVIEWER)
    controls = [item["action"] for item in platform if item["action"].startswith("applicability.")]
    assert controls == ["applicability.fanout.release", "applicability.fanout.hold"]
    assert {item["tenant_id"] for item in platform} <= {None, internal}
    assert tenant not in {item["tenant_id"] for item in platform}

    # A tenant role filtering for the platform's subjects still reads nothing of them.
    asked = identity.get(AUDIT, params={"subject_type": "rule_version"}, headers=owner)
    assert asked.json()["items"] == []
