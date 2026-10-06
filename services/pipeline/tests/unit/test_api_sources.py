"""The source manager's routes on the memory store, in header, dual and token mode: who may read
and write, what each route answers, and the audit entries the writes leave."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.audit import AuditActorKind
from domain_kernel.documents import document_id_for
from domain_kernel.ids import TenantId, UserId
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.infrastructure.adapters import RegistryAdapterTypes
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore, storage_key_for
from pipeline.main import PROBLEM_STATUS, build_app
from pipeline.testing import WRITE_TOKEN, MemoryCrawls, pipeline_settings, recorded_types
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
BASE = "/v1/pipeline"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
INTERNAL = TenantId.new()
ADMIN_ID = UserId.new()
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True, user_id=ADMIN_ID))
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True))
OWNER = bearer(ISSUER.user(TenantId.new(), [Role.OWNER]))
SERVICE = bearer(ISSUER.service("pipeline", [Scope.RULEBOOK_WRITE]))
ASSERTED = UUID(int=99)
REASON = "Recorded notifications for the tests"
NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
NEW_SOURCE = {
    "actor_id": str(ASSERTED),
    "reason": REASON,
    "key": "recorded_cbic",
    "name": "Recorded CBIC notifications",
    "adapter_type": "recorded",
    "parameters": {"numbers": ["01/2026-Central Tax"]},
    "cadence_seconds": 7200,
}
ACT = {"actor_id": str(ASSERTED), "reason": REASON}


class Wired:
    def __init__(self, client: TestClient, store: MemoryStore, raw: MemoryRawStore) -> None:
        self.client = client
        self.store = store
        self.raw = raw
        app = client.app
        assert isinstance(app, FastAPI)
        self.starter: MemoryCrawls = app.state.starter


def wired(mode: AuthMode, **overrides: Any) -> Iterator[Wired]:
    store, raw, starter = MemoryStore(), MemoryRawStore(), MemoryCrawls()
    values: dict[str, Any] = {"pipeline_crawl_enabled": True, **ISSUER.settings_overrides(mode)}
    values.update(overrides)
    app = build_app(
        pipeline_settings(**values),
        units=store,
        raw_store=raw,
        starter=starter,
        adapter_types=RegistryAdapterTypes(recorded_types()),
    )
    app.state.starter = starter
    with TestClient(app) as client:
        yield Wired(client, store, raw)


@pytest.fixture
def header() -> Iterator[Wired]:
    yield from wired("header")


@pytest.fixture
def dual() -> Iterator[Wired]:
    yield from wired("dual")


@pytest.fixture
def token() -> Iterator[Wired]:
    yield from wired("token")


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def keep(
    store: MemoryStore, raw: MemoryRawStore, content: bytes, **overrides: Any
) -> RawDocumentRecord:
    digest = hashlib.sha256(content).hexdigest()
    values: dict[str, Any] = {
        "document_id": document_id_for(digest),
        "source_key": "cbic_notifications",
        "source_url": f"https://example.invalid/{digest[:6]}.pdf",
        "fetched_at": NOW,
        "content_type": "application/pdf",
        "size": len(content),
        "sha256": digest,
        "storage_key": storage_key_for(digest),
        "external_ref": "01/2026-Central Tax",
        "title": "Seeks to amend",
        "published_on": date(2026, 4, 21),
    }
    values.update(overrides)
    record = RawDocumentRecord(**values)
    with store() as unit:
        unit.documents.add(record)
    raw.files[record.storage_key] = content
    return record


# ---------------------------------------------------------------- header mode


def test_the_built_in_sources_are_listed_with_how_each_stands(header: Wired) -> None:
    response = header.client.get(f"{BASE}/sources")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["key"] for item in items] == [
        "cbic_circulars",
        "cbic_notifications",
        "cgst_act",
        "cgst_rules",
        "gstcouncil_press",
        "gstn_advisories",
        "igst_act",
        "mahagst_notifications",
    ]
    cbic = items[1]
    statute = items[3]
    assert (statute["name"], statute["doc_type"], statute["regulator"], statute["site"]) == (
        "The Central Goods and Services Tax Rules, 2017",
        "statute",
        "CBIC",
        "upload",
    )
    assert (statute["listable"], cbic["listable"]) == (False, True)
    assert (cbic["name"], cbic["regulator"], cbic["doc_type"], cbic["site"]) == (
        "CBIC Central Tax notifications",
        "CBIC",
        "notification",
        "taxinformation.cbic.gov.in",
    )
    assert (cbic["status"], cbic["cadence_seconds"], cbic["document_count"]) == (
        "healthy",
        7200,
        0,
    )
    assert cbic["freshness"] == {
        "state": "never",
        "age_seconds": None,
        "cadence_seconds": 7200,
        "cadences": None,
    }
    assert (cbic["last_fetch_at"], cbic["latest_run"], cbic["watermark"]) == (None, None, None)


def test_an_admin_adds_a_source_with_the_write_token_and_it_is_audited(header: Wired) -> None:
    response = header.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=WRITE)
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["key"], body["adapter_type"], body["parameters"]) == (
        "recorded_cbic",
        "recorded",
        {"numbers": ["01/2026-Central Tax"]},
    )
    (entry,) = header.store.audit
    assert (entry.action, entry.subject_id, entry.reason) == (
        "pipeline.source.add",
        "recorded_cbic",
        REASON,
    )
    assert (entry.actor.kind, entry.actor.id) == (AuditActorKind.USER, str(ASSERTED))
    again = header.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=WRITE)
    assert (again.status_code, problem(again)) == (409, "pipeline-source-exists")


@pytest.mark.parametrize(
    ("changes", "status", "slug"),
    [
        ({"adapter_type": "nowhere"}, 422, "pipeline-source-invalid"),
        ({"parameters": {"numbers": ["99/2026-Central Tax"]}}, 422, "pipeline-source-invalid"),
        ({"key": "Not A Key"}, 422, "request-invalid"),
        ({"reason": "short"}, 422, "request-invalid"),
        ({"cadence_seconds": 30}, 422, "request-invalid"),
        ({"surprise": True}, 422, "request-invalid"),
    ],
)
def test_a_source_that_does_not_check_out_is_refused(
    header: Wired, changes: dict[str, Any], status: int, slug: str
) -> None:
    response = header.client.post(f"{BASE}/sources", json={**NEW_SOURCE, **changes}, headers=WRITE)
    assert (response.status_code, problem(response)) == (status, slug)
    assert header.store.audit == []


def test_writes_need_the_write_token_in_header_mode(header: Wired) -> None:
    missing = header.client.post(f"{BASE}/sources", json=NEW_SOURCE)
    assert (missing.status_code, problem(missing)) == (401, "pipeline-write-token-invalid")
    wrong = header.client.post(
        f"{BASE}/sources", json=NEW_SOURCE, headers={"x-cw-write-token": "guess"}
    )
    assert (wrong.status_code, problem(wrong)) == (401, "pipeline-write-token-invalid")
    patched = header.client.patch(f"{BASE}/sources/gstn_advisories", json={**ACT, "paused": True})
    assert patched.status_code == 401
    fetched = header.client.post(f"{BASE}/sources/gstn_advisories/fetch", json=ACT)
    assert fetched.status_code == 401


def test_with_no_write_token_configured_writes_fail_closed() -> None:
    for each in wired("header", rulebook_write_token=None):
        response = each.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=WRITE)
        assert (response.status_code, problem(response)) == (503, "pipeline-writes-disabled")
    for each in wired("dual", rulebook_write_token=None):
        response = each.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=WRITE)
        assert (response.status_code, problem(response)) == (401, "auth-token-required")


def test_an_admin_edits_a_source(header: Wired) -> None:
    response = header.client.patch(
        f"{BASE}/sources/cbic_circulars",
        json={**ACT, "paused": True, "cadence_seconds": 43200, "name": "CGST circulars"},
        headers=WRITE,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["paused"], body["status"], body["cadence_seconds"], body["name"]) == (
        True,
        "paused",
        43200,
        "CGST circulars",
    )
    (entry,) = header.store.audit
    assert entry.action == "pipeline.source.edit"
    assert entry.before is not None
    assert entry.before["paused"] is False
    bad = header.client.patch(
        f"{BASE}/sources/cbic_circulars",
        json={**ACT, "parameters": {"listing": "circulars", "category": "Cess"}},
        headers=WRITE,
    )
    assert (bad.status_code, problem(bad)) == (422, "pipeline-source-invalid")
    missing = header.client.patch(f"{BASE}/sources/nowhere", json=ACT, headers=WRITE)
    assert (missing.status_code, problem(missing)) == (404, "pipeline-source-not-found")


def test_an_admin_starts_a_crawl_and_gets_its_run_at_once(header: Wired) -> None:
    response = header.client.post(f"{BASE}/sources/gstn_advisories/fetch", json=ACT, headers=WRITE)
    assert response.status_code == 202, response.text
    body = response.json()
    (start,) = header.starter.started
    assert body == {
        "run_id": str(start.run_id),
        "workflow_id": start.workflow_id,
        "source_key": "gstn_advisories",
        "trigger": "manual",
    }
    listed = {item["key"]: item for item in header.client.get(f"{BASE}/sources").json()["items"]}
    gstn = listed["gstn_advisories"]
    assert gstn["status"] == "fetching"
    assert gstn["latest_run"]["run_id"] == str(start.run_id)
    assert gstn["latest_run"]["status"] == "running"
    again = header.client.post(f"{BASE}/sources/gstn_advisories/fetch", json=ACT, headers=WRITE)
    assert (again.status_code, problem(again)) == (409, "pipeline-crawl-running")
    (entry,) = header.store.audit
    assert entry.action == "pipeline.source.fetch"
    missing = header.client.post(f"{BASE}/sources/nowhere/fetch", json=ACT, headers=WRITE)
    assert missing.status_code == 404


def test_with_crawling_off_a_fetch_is_refused_and_nothing_starts() -> None:
    for each in wired("header", pipeline_crawl_enabled=False):
        response = each.client.post(
            f"{BASE}/sources/gstn_advisories/fetch", json=ACT, headers=WRITE
        )
        assert (response.status_code, problem(response)) == (503, "pipeline-crawl-disabled")
        assert each.starter.started == []
        assert each.store.crawl_runs == {}
        assert each.store.audit == []


def test_when_temporal_does_not_answer_the_fetch_is_a_503_and_the_run_says_why(
    header: Wired,
) -> None:
    header.starter.fail = ConnectionError("temporal:7233 refused the connection")
    response = header.client.post(f"{BASE}/sources/gstn_advisories/fetch", json=ACT, headers=WRITE)
    assert (response.status_code, problem(response)) == (503, "pipeline-crawl-unavailable")
    listed = {item["key"]: item for item in header.client.get(f"{BASE}/sources").json()["items"]}
    run = listed["gstn_advisories"]["latest_run"]
    assert run["status"] == "failed"
    assert "refused the connection" in run["error"]


def test_a_sources_documents_come_a_page_at_a_time(header: Wired) -> None:
    first = keep(header.store, header.raw, b"%PDF first", published_on=date(2026, 4, 21))
    second = keep(header.store, header.raw, b"%PDF second", published_on=date(2025, 10, 18))
    page = header.client.get(f"{BASE}/sources/cbic_notifications/documents", params={"limit": 1})
    assert page.status_code == 200
    body = page.json()
    assert [item["document_id"] for item in body["items"]] == [str(first.document_id)]
    assert body["items"][0]["raw_path"] == f"/v1/pipeline/documents/{first.document_id}/raw"
    rest = header.client.get(
        f"{BASE}/sources/cbic_notifications/documents",
        params={"limit": 1, "cursor": body["next_cursor"]},
    ).json()
    assert [item["document_id"] for item in rest["items"]] == [str(second.document_id)]
    assert rest["next_cursor"] is None
    other = header.client.get(
        f"{BASE}/sources/gstn_advisories/documents", params={"cursor": body["next_cursor"]}
    )
    assert (other.status_code, problem(other)) == (422, "pagination-cursor-invalid")
    missing = header.client.get(f"{BASE}/sources/nowhere/documents")
    assert (missing.status_code, problem(missing)) == (404, "pipeline-source-not-found")


def test_a_document_and_its_bytes(header: Wired) -> None:
    content = b"%PDF-1.7 recorded"
    record = keep(header.store, header.raw, content)
    read = header.client.get(f"{BASE}/documents/{record.document_id}")
    assert read.status_code == 200
    assert (read.json()["sha256"], read.json()["status"]) == (record.sha256, "discovered")
    raw = header.client.get(f"{BASE}/documents/{record.document_id}/raw")
    assert raw.status_code == 200
    assert raw.content == content
    assert raw.headers["content-type"] == "application/pdf"
    assert raw.headers["etag"] == f'"{record.sha256}"'
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert raw.headers["content-security-policy"] == "sandbox"
    assert raw.headers["content-disposition"] == f'inline; filename="{record.document_id}.pdf"'
    missing = header.client.get(f"{BASE}/documents/{UUID(int=4)}")
    assert (missing.status_code, problem(missing)) == (404, "pipeline-document-not-found")
    header.raw.files[record.storage_key] = b"%PDF-1.7 altered"
    altered = header.client.get(f"{BASE}/documents/{record.document_id}/raw")
    assert (altered.status_code, problem(altered)) == (502, "pipeline-raw-document-unreadable")


# ---------------------------------------------------------------- dual and token mode


def test_in_dual_mode_an_admins_token_writes_and_is_the_actor(dual: Wired) -> None:
    response = dual.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=ADMIN)
    assert response.status_code == 201, response.text
    (entry,) = dual.store.audit
    assert (entry.actor.kind, entry.actor.id, entry.actor.label) == (
        AuditActorKind.USER,
        str(ADMIN_ID),
        "admin",
    )
    with_token = dual.client.post(f"{BASE}/sources/recorded_cbic/fetch", json=ACT, headers=WRITE)
    assert with_token.status_code == 202, "the shared token still opens it without a bearer"


def test_an_analyst_reads_but_does_not_write(dual: Wired) -> None:
    assert dual.client.get(f"{BASE}/sources", headers=ANALYST).status_code == 200
    refused = dual.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=ANALYST)
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    both = dual.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers={**ANALYST, **WRITE})
    assert both.status_code == 403, "a bearer without the role is refused whatever token it sends"


def test_token_mode_takes_the_bearer_alone(token: Wired) -> None:
    anonymous = token.client.get(f"{BASE}/sources")
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
    shared = token.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=WRITE)
    assert shared.status_code == 401
    assert token.client.get(f"{BASE}/sources", headers=ANALYST).status_code == 200
    for outsider in (OWNER, SERVICE):
        assert token.client.get(f"{BASE}/sources", headers=outsider).status_code == 403
        record = token.client.get(f"{BASE}/documents/{UUID(int=4)}/raw", headers=outsider)
        assert record.status_code == 403
    created = token.client.post(f"{BASE}/sources", json=NEW_SOURCE, headers=ADMIN)
    assert created.status_code == 201


def test_every_problem_the_service_answers_has_its_status() -> None:
    assert set(PROBLEM_STATUS.values()) <= {401, 404, 409, 422, 502, 503}
