"""The operations routes on the memory store: every source's crawl runs and documents, a retry of a
stored document (its stages, a person's type, its Idempotency-Key, what it refuses), and the
outbox's dead rows with their requeue; in header mode with the shared write token, and in token
mode, where only an admin writes."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role
from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId, TenantId, UserId
from pipeline.application.activities import ParseRequest
from pipeline.application.classify import ClassifyDocument
from pipeline.application.extraction import RULE_PROMPT_REF
from pipeline.domain.classification import RETRY, Relevance, TypeConfidence
from pipeline.domain.crawl import CrawlCounts, CrawlRun, CrawlRunId, CrawlTrigger
from pipeline.domain.errors import IngestUnavailableError
from pipeline.domain.events import DocumentClassified
from pipeline.domain.extraction import (
    ExtractionOutcome,
    RuleExtraction,
    candidate_id_for,
    extraction_workflow_id,
)
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.retry import retry_workflow_id
from pipeline.domain.tasks import TaskKind, TaskStatus
from pipeline.infrastructure.adapters import RegistryAdapterTypes, RegistryCatalog
from pipeline.infrastructure.http import PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.main import build_app
from pipeline.testing import WRITE_TOKEN, MemoryCrawls, MemoryIngests, pipeline_settings
from pipeline.workflows import IngestRequest
from py_common.auth.testing import TestIssuer, bearer
from py_common.outbox.relay import OutboxRelay, RelayConfig
from py_common.outbox.testing import FakeProducer
from py_common.settings import AuthMode

BASE = "/v1/pipeline"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
ISSUER = TestIssuer()
INTERNAL = TenantId.new()
ADMIN_ID = UserId.new()
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True, user_id=ADMIN_ID))
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True))
ACTOR = UUID(int=61)
REASON = "Example reason for the operations tests"
NOW = datetime(2000, 1, 3, 6, 0, tzinfo=UTC)


def page(title: str, text: str) -> bytes:
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{text}</p>"
        "</body></html>"
    ).encode()


NOTIFICATION = page(
    "Notification No. 1/2000-Central Tax",
    "Example: the return for January, 2000 is furnished by the twentieth day of February, 2000.",
)
GUIDE = page(
    "Notification No. 2/2000-Central Tax",
    "Example: the example return is furnished on the example portal by the registered person.",
)
CIRCULAR = page(
    "Circular No. 3/2000-GST",
    "Example clarification on Notification No. 1/2000 - Central Tax.",
)


class Ops:
    def __init__(self, client: TestClient, store: MemoryStore, raw: MemoryRawStore) -> None:
        self.client = client
        self.store = store
        self.raw = raw
        app = client.app
        assert isinstance(app, FastAPI)
        self.ingests: MemoryIngests = app.state.ingests

    def upload(
        self,
        content: bytes,
        *,
        key: str = "cbic_notifications",
        title: str = "Example notification",
        published_on: str = "2000-01-02",
        **fields: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"{BASE}/sources/{key}/uploads",
            files={"file": ("document.html", content, "text/html")},
            data={
                "actor_id": str(ACTOR),
                "reason": REASON,
                "title": title,
                "published_on": published_on,
                **fields,
            },
            headers=WRITE,
        )
        assert response.status_code == 202, response.text
        document: dict[str, Any] = response.json()["document"]
        return document

    def classify(self, document_id: str) -> str:
        """What the worker's ingest does with the uploaded document up to its classify step."""
        start = next(s for s in self.ingests.started if str(s.record.document_id) == document_id)
        request = IngestRequest.model_validate(ingest_payload(start))
        assert request.stored is not None
        parse = ParseRequest(
            document_id=request.stored.document_id,
            stored=request.stored,
            title=request.stored.title,
            published_at=request.stored.published_at,
        )
        with self.store() as unit:
            unit.documents.record_parse(DocumentId(UUID(document_id)), "html@1")
        chain = ParserChain(RegistryCatalog(PoliteClient()))
        classified = ClassifyDocument(chain, self.raw, self.store, extraction=True).classify(parse)
        return classified.route

    def retry(
        self,
        document_id: str,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        **body: Any,
    ) -> Any:
        sent = {"actor_id": str(ACTOR), "reason": REASON, "stage": "parse", **body}
        given = dict(WRITE if headers is None else headers)
        if key is not None:
            given["Idempotency-Key"] = key
        return self.client.post(f"{BASE}/documents/{document_id}/retry", json=sent, headers=given)

    def audit(self, action: str) -> list[Any]:
        return [entry for entry in self.store.audit if entry.action == action]


def wired(mode: AuthMode) -> Iterator[Ops]:
    store, raw, ingests = MemoryStore(), MemoryRawStore(), MemoryIngests()
    app = build_app(
        pipeline_settings(pipeline_knowledge_enabled=True, **ISSUER.settings_overrides(mode)),
        units=store,
        raw_store=raw,
        starter=MemoryCrawls(),
        adapter_types=RegistryAdapterTypes(),
        ingests=ingests,
    )
    app.state.ingests = ingests
    with TestClient(app) as client:
        yield Ops(client, store, raw)


@pytest.fixture
def ops() -> Iterator[Ops]:
    yield from wired("header")


@pytest.fixture
def token() -> Iterator[Ops]:
    yield from wired("token")


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


# ---------------------------------------------------------------- runs


def run(key: str, minutes: int, trigger: CrawlTrigger | None, *, failed: bool = False) -> CrawlRun:
    started = NOW + timedelta(minutes=minutes)
    found = CrawlRun(
        id=CrawlRunId.new(),
        source_key=key,
        started_at=started,
        trigger=trigger,
        workflow_id="" if trigger is None else f"pipeline-crawl-{key}-{minutes}",
    )
    return found.finish(
        started + timedelta(minutes=1),
        CrawlCounts(listed=3, stored=1),
        error="Example: the listing failed" if failed else "",
    )


def test_runs_list_the_latest_first_with_their_trigger_and_filters(ops: Ops) -> None:
    with ops.store() as unit:
        for found in (
            run("cbic_notifications", 1, None),
            run("cbic_notifications", 2, CrawlTrigger.SCHEDULE),
            run("gstn_advisories", 3, CrawlTrigger.MANUAL, failed=True),
            run("cbic_notifications", 4, CrawlTrigger.BACKFILL),
        ):
            unit.crawl_runs.add(found)
    every = ops.client.get(f"{BASE}/runs").json()
    assert [(item["source_key"], item["trigger"]) for item in every["items"]] == [
        ("cbic_notifications", "backfill"),
        ("gstn_advisories", "manual"),
        ("cbic_notifications", "schedule"),
        ("cbic_notifications", None),
    ]
    first = every["items"][0]
    assert first["workflow_id"] == "pipeline-crawl-cbic_notifications-4"
    assert (first["status"], first["listed"], first["stored"]) == ("completed", 3, 1)
    assert every["items"][3]["workflow_id"] is None, "a run kept before it had none"
    failed = ops.client.get(f"{BASE}/runs", params={"status": "failed"}).json()["items"]
    assert [(item["source_key"], item["error"]) for item in failed] == [
        ("gstn_advisories", "Example: the listing failed")
    ]
    backfills = ops.client.get(f"{BASE}/runs", params={"trigger": "backfill"}).json()["items"]
    assert len(backfills) == 1
    of_cbic = ops.client.get(
        f"{BASE}/runs", params={"source_key": "cbic_notifications", "limit": 2}
    ).json()
    assert len(of_cbic["items"]) == 2
    rest = ops.client.get(
        f"{BASE}/runs",
        params={"source_key": "cbic_notifications", "limit": 2, "cursor": of_cbic["next_cursor"]},
    ).json()
    assert [item["trigger"] for item in rest["items"]] == [None]
    assert rest["next_cursor"] is None
    other = ops.client.get(f"{BASE}/runs", params={"cursor": of_cbic["next_cursor"]})
    assert (other.status_code, problem(other)) == (422, "pagination-cursor-invalid")


# ---------------------------------------------------------------- documents


def test_documents_list_every_source_the_latest_fetch_first_with_how_each_reads(ops: Ops) -> None:
    notification = ops.upload(NOTIFICATION, published_on="2000-01-02")
    guide = ops.upload(
        GUIDE, title="Example user guide for the return portal", published_on="2000-01-05"
    )
    statute = ops.upload(
        page("Example Act", "Example section 1. Example text of the Act."),
        key="cgst_act",
        published_on="2000-01-10",
    )
    assert ops.classify(notification["document_id"]) == "extract"
    assert ops.classify(guide["document_id"]) == "irrelevant"

    listed = ops.client.get(f"{BASE}/documents").json()["items"]
    assert [item["document_id"] for item in listed] == [
        statute["document_id"],
        guide["document_id"],
        notification["document_id"],
    ], "the latest first fetch first"
    by_id = {item["document_id"]: item for item in listed}
    read = by_id[notification["document_id"]]
    assert (read["status"], read["read_as"]) == ("classified", "notification")
    assert read["classification"]["route"] == "extract"
    assert read["classification"]["classifier"] == "detector@1"
    assert read["extraction"] is None
    assert by_id[statute["document_id"]]["read_as"] == "statute", "its source's type"
    assert by_id[statute["document_id"]]["classification"] is None

    def ids(**params: Any) -> list[str]:
        items = ops.client.get(f"{BASE}/documents", params=params).json()["items"]
        return [item["document_id"] for item in items]

    assert ids(status="irrelevant") == [guide["document_id"]]
    assert ids(source_key="cgst_act") == [statute["document_id"]]
    assert ids(doc_type="statute") == [statute["document_id"]], "by its source's type"
    assert set(ids(doc_type="notification")) == {
        notification["document_id"],
        guide["document_id"],
    }
    assert ids(published_from="2000-01-03", published_to="2000-01-06") == [guide["document_id"]]
    first = ops.client.get(f"{BASE}/documents", params={"limit": 2}).json()
    rest = ops.client.get(
        f"{BASE}/documents", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert [item["document_id"] for item in rest["items"]] == [notification["document_id"]]
    assert rest["next_cursor"] is None

    detail = ops.client.get(f"{BASE}/documents/{notification['document_id']}").json()
    assert (detail["read_as"], detail["retries"]) == ("notification", [])
    assert detail["raw_path"] == f"{BASE}/documents/{notification['document_id']}/raw"


def test_a_document_shows_its_extraction_by_the_current_prompt(ops: Ops) -> None:
    uploaded = ops.upload(NOTIFICATION)
    ops.classify(uploaded["document_id"])
    document_id = DocumentId(UUID(uploaded["document_id"]))
    with ops.store() as unit:
        unit.extractions.add(
            RuleExtraction(
                document_id=document_id,
                prompt_version=RULE_PROMPT_REF,
                candidate_id=candidate_id_for(document_id, RULE_PROMPT_REF),
                outcome=ExtractionOutcome.UNPARSEABLE,
                model="fake/echo",
                attempts=2,
                source_key="cbic_notifications",
                doc_type=DocumentType.NOTIFICATION,
                regulator="CBIC",
                issues=(),
                citation_count=0,
                confidence=0.0,
                needs_review=True,
                answer="",
                ontology_version="1",
                extracted_at=NOW,
            )
        )
    detail = ops.client.get(f"{BASE}/documents/{uploaded['document_id']}").json()
    assert detail["extraction"]["outcome"] == "unparseable"
    assert detail["extraction"]["candidate_id"] == str(
        candidate_id_for(document_id, RULE_PROMPT_REF)
    )


# ---------------------------------------------------------------- retries


def test_a_document_set_aside_comes_back_with_a_persons_type(ops: Ops) -> None:
    guide = ops.upload(GUIDE, title="Example user guide for the return portal")
    document_id = guide["document_id"]
    assert ops.classify(document_id) == "irrelevant"
    response = ops.retry(document_id, "example-key-1", stage="classify", doc_type="notification")
    assert response.status_code == 202, response.text
    assert "Idempotent-Replayed" not in response.headers
    body = response.json()
    workflow_id = retry_workflow_id(DocumentId(UUID(document_id)), 1)
    assert (body["workflow_id"], body["started"], body["reclassified"]) == (
        workflow_id,
        True,
        True,
    )
    assert (body["retry"]["attempt"], body["retry"]["stage"], body["retry"]["doc_type"]) == (
        1,
        "classify",
        "notification",
    )
    assert body["retry"]["requested_by"] == str(ACTOR)
    document = body["document"]
    assert (document["status"], document["read_as"]) == ("classified", "notification")
    classification = document["classification"]
    assert (classification["classifier"], classification["relevance"]) == (RETRY, "relevant")
    assert (classification["confidence"], classification["decided_by"]) == ("certain", str(ACTOR))
    assert [retry["attempt"] for retry in document["retries"]] == [1]

    start = ops.ingests.started[-1]
    assert (start.workflow_id, start.duplicate, start.reclassify) == (workflow_id, True, False)
    assert (start.knowledge, start.regulator) == (True, "CBIC")
    request = IngestRequest.model_validate(ingest_payload(start))
    assert request.stored is not None
    assert not request.reclassify
    classified = [e for e in ops.store.events if isinstance(e, DocumentClassified)]
    assert [(e.classifier, e.relevance.value) for e in classified] == [
        ("detector@1", "irrelevant"),
        (RETRY, "relevant"),
    ]
    (entry,) = ops.audit("pipeline.document.retry")
    assert (entry.subject_type, entry.subject_id, entry.reason) == (
        "raw_document",
        document_id,
        REASON,
    )
    assert entry.before is not None
    assert entry.after is not None
    assert entry.before["status"] == "irrelevant"
    assert (entry.after["status"], entry.after["attempt"]) == ("classified", 1)


def test_the_same_request_replays_its_attempt_and_another_body_is_refused(ops: Ops) -> None:
    document_id = ops.upload(NOTIFICATION)["document_id"]
    ops.classify(document_id)
    first = ops.retry(document_id, "example-key-2", stage="parse")
    assert first.status_code == 202, first.text
    again = ops.retry(document_id, "example-key-2", stage="parse")
    assert again.status_code == 202, again.text
    assert again.headers["Idempotent-Replayed"] == "true"
    assert (again.json()["retry"]["attempt"], again.json()["started"]) == (1, False)
    assert len(ops.audit("pipeline.document.retry")) == 1
    reused = ops.retry(document_id, "example-key-2", stage="classify")
    assert (reused.status_code, problem(reused)) == (422, "idempotency-key-reused")
    missing = ops.retry(document_id, None)
    assert (missing.status_code, problem(missing)) == (428, "idempotency-key-required")


def test_a_retry_waits_for_the_ingest_of_its_document_to_end(ops: Ops) -> None:
    document_id = ops.upload(NOTIFICATION)["document_id"]
    ops.classify(document_id)
    assert ops.retry(document_id, "example-key-3").status_code == 202
    busy = ops.retry(document_id, "example-key-4", stage="classify")
    assert (busy.status_code, problem(busy)) == (409, "pipeline-ingest-running")
    assert retry_workflow_id(DocumentId(UUID(document_id)), 1) in busy.json()["detail"]
    ops.ingests.finish()
    extraction = extraction_workflow_id(UUID(document_id), RULE_PROMPT_REF)
    ops.ingests.running_ids.add(extraction)
    waiting = ops.retry(document_id, "example-key-4", stage="classify")
    assert (waiting.status_code, problem(waiting)) == (409, "pipeline-ingest-running")
    assert extraction in waiting.json()["detail"]
    ops.ingests.running_ids.clear()
    second = ops.retry(document_id, "example-key-4", stage="classify")
    assert second.status_code == 202, second.text
    assert (second.json()["retry"]["attempt"], second.json()["reclassified"]) == (2, False)
    assert ops.ingests.started[-1].reclassify, "the classify stage reads the document again"
    assert [r["attempt"] for r in second.json()["document"]["retries"]] == [1, 2]


def test_a_retry_temporal_does_not_start_is_started_by_the_same_request(ops: Ops) -> None:
    document_id = ops.upload(NOTIFICATION)["document_id"]
    ops.classify(document_id)
    ops.ingests.running_fails = IngestUnavailableError("example: temporal is away")
    away = ops.retry(document_id, "example-key-5")
    assert (away.status_code, problem(away)) == (503, "pipeline-ingest-unavailable")
    assert ops.audit("pipeline.document.retry") == [], "nothing recorded before the check"
    ops.ingests.fail = IngestUnavailableError("example: temporal is away")
    failed = ops.retry(document_id, "example-key-5")
    assert (failed.status_code, problem(failed)) == (503, "pipeline-ingest-unavailable")
    assert len(ops.audit("pipeline.document.retry")) == 1, "the attempt stays recorded"
    again = ops.retry(document_id, "example-key-5")
    assert again.status_code == 202, again.text
    assert (again.json()["retry"]["attempt"], again.json()["started"]) == (1, True)
    assert again.headers["Idempotent-Replayed"] == "true"


def test_a_replayed_retry_never_runs_an_ingest_that_failed_again(ops: Ops) -> None:
    """The fake starter keeps Temporal's policies: an upload's failed ingest may run again under
    its id, but a retry's attempt is used once, so the same request sent after its ingest failed
    replays the attempt and starts nothing; a new request is a new attempt."""
    document_id = ops.upload(NOTIFICATION)["document_id"]
    ops.classify(document_id)
    (upload,) = ops.ingests.started
    assert not ops.ingests.start(upload), "the upload's ingest runs"
    ops.ingests.fail_runs(upload.workflow_id)
    assert ops.ingests.start(upload), "a failed ingest of an upload may run again"
    ops.ingests.finish(upload.workflow_id)
    assert not ops.ingests.start(upload), "a completed one may not"

    first = ops.retry(document_id, "example-key-13")
    assert first.status_code == 202, first.text
    workflow_id = first.json()["workflow_id"]
    assert first.json()["started"] is True
    assert ops.ingests.started[-1].once, "a retry's attempt uses its id once"
    ops.ingests.fail_runs(workflow_id)
    again = ops.retry(document_id, "example-key-13")
    assert again.status_code == 202, again.text
    assert again.headers["Idempotent-Replayed"] == "true"
    assert (again.json()["retry"]["attempt"], again.json()["started"]) == (1, False)
    assert [s.workflow_id for s in ops.ingests.started].count(workflow_id) == 1
    assert len(ops.audit("pipeline.document.retry")) == 1
    second = ops.retry(document_id, "example-key-14")
    assert second.status_code == 202, second.text
    assert (second.json()["retry"]["attempt"], second.json()["started"]) == (2, True)


def test_a_held_document_and_nothing_to_extract_are_refused(ops: Ops) -> None:
    circular = ops.upload(CIRCULAR, title="Circular No. 3/2000-GST")["document_id"]
    assert ops.classify(circular) == "triage"
    held = ops.retry(circular, "example-key-6", doc_type="circular")
    assert (held.status_code, problem(held)) == (409, "pipeline-retry-refused")
    assert "waits for its triage" in held.json()["detail"]
    (task,) = [t for t in ops.store.tasks.values() if t.kind is TaskKind.TRIAGE]
    dismissed = ops.client.post(
        f"{BASE}/tasks/{task.id}/dismiss",
        json={"actor_id": str(ACTOR), "reason": "Example: not ours to decide today"},
        headers=WRITE,
    )
    assert dismissed.status_code == 200
    assert ops.store.tasks[task.id].status is TaskStatus.DISMISSED
    back = ops.retry(circular, "example-key-6", doc_type="circular")
    assert back.status_code == 202, back.text
    assert back.json()["document"]["status"] == "classified", "a dismissed triage comes back"

    guide = ops.upload(GUIDE, title="Example user guide for the return portal")["document_id"]
    ops.classify(guide)
    nothing = ops.retry(guide, "example-key-7", stage="extract")
    assert (nothing.status_code, problem(nothing)) == (409, "pipeline-retry-refused")
    assert "is irrelevant" in nothing.json()["detail"]
    invalid = ops.retry(guide, "example-key-8", stage="extract", doc_type="press_release")
    assert (invalid.status_code, problem(invalid)) == (422, "pipeline-retry-invalid")
    unknown = ops.retry(str(uuid4()), "example-key-9")
    assert (unknown.status_code, problem(unknown)) == (404, "pipeline-document-not-found")
    short = ops.retry(guide, "example-key-10", reason="short")
    assert short.status_code == 422


def extracted(ops: Ops, document_id: str) -> None:
    """The document's extraction by the current prompt, stored as the worker would, with its
    status."""
    stored = DocumentId(UUID(document_id))
    with ops.store() as unit:
        unit.extractions.add(
            RuleExtraction(
                document_id=stored,
                prompt_version=RULE_PROMPT_REF,
                candidate_id=candidate_id_for(stored, RULE_PROMPT_REF),
                outcome=ExtractionOutcome.UNPARSEABLE,
                model="fake/echo",
                attempts=2,
                source_key="cbic_notifications",
                doc_type=DocumentType.NOTIFICATION,
                regulator="CBIC",
                issues=(),
                citation_count=0,
                confidence=0.0,
                needs_review=True,
                answer="",
                ontology_version="1",
                extracted_at=NOW,
            )
        )
        unit.documents.set_status(stored, DocumentStatus.EXTRACTED)


def test_an_extracted_document_has_nothing_left_to_extract(ops: Ops) -> None:
    document_id = ops.upload(NOTIFICATION)["document_id"]
    ops.classify(document_id)
    extract = ops.retry(document_id, "example-key-11", stage="extract")
    assert extract.status_code == 202, extract.text
    ops.ingests.finish()
    extracted(ops, document_id)
    again = ops.retry(document_id, "example-key-12", stage="extract")
    assert (again.status_code, problem(again)) == (409, "pipeline-retry-refused")
    assert "is extracted already" in again.json()["detail"]


def test_a_type_given_to_an_extracted_document_keeps_it_extracted_on_that_route(
    ops: Ops,
) -> None:
    """Its extraction's id is used, so no extraction would set it extracted again: a type that
    still leads to the extraction leaves it extracted, one kept for reference moves it."""
    document_id = ops.upload(NOTIFICATION)["document_id"]
    ops.classify(document_id)
    extracted(ops, document_id)
    circular = ops.retry(document_id, "example-key-15", doc_type="circular")
    assert circular.status_code == 202, circular.text
    assert circular.json()["reclassified"] is True
    assert circular.json()["document"]["status"] == "extracted"
    ops.ingests.finish()
    reference = ops.retry(document_id, "example-key-16", doc_type="press_release")
    assert reference.status_code == 202, reference.text
    assert reference.json()["document"]["status"] == "reference"


def test_in_token_mode_an_admin_retries_and_an_analyst_reads(token: Ops) -> None:
    uploaded = token.client.post(
        f"{BASE}/sources/cbic_notifications/uploads",
        files={"file": ("document.html", NOTIFICATION, "text/html")},
        data={"actor_id": str(ACTOR), "reason": REASON, "title": "Example notification"},
        headers=ADMIN,
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["document"]["document_id"]
    refused = token.retry(document_id, "example-key-13", headers=ANALYST)
    assert refused.status_code == 403
    nobody = token.retry(document_id, "example-key-13", headers={})
    assert nobody.status_code == 401
    retried = token.retry(document_id, "example-key-13", headers=ADMIN)
    assert retried.status_code == 202, retried.text
    assert retried.json()["retry"]["requested_by"] == str(ADMIN_ID)
    (entry,) = token.audit("pipeline.document.retry")
    assert entry.actor.id == str(ADMIN_ID)
    for path in ("/runs", "/documents", "/outbox/dead", f"/documents/{document_id}"):
        assert token.client.get(f"{BASE}{path}", headers=ANALYST).status_code == 200, path
        assert token.client.get(f"{BASE}{path}").status_code == 401, path


# ---------------------------------------------------------------- the outbox


def dead_letter_everything(ops: Ops, *, at: datetime) -> FakeProducer:
    """The relay's pass with a broker that refuses every send, once with one attempt allowed:
    every pending row goes dead (its copy to <topic>.dlq)."""
    producer = FakeProducer()
    for topic in {row.message.topic for row in ops.store.outbox.rows.values()}:
        producer.fail_times[topic] = 1_000
    relay = OutboxRelay(
        store=ops.store.outbox,
        producer=producer,
        config=RelayConfig(max_attempts=1),
        clock=lambda: at,
    )
    asyncio.run(relay.run_once())
    return producer


def test_dead_rows_list_the_newest_first_without_their_bodies(ops: Ops) -> None:
    later = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=1)
    first = ops.upload(NOTIFICATION)
    dead_letter_everything(ops, at=later)
    second = ops.upload(CIRCULAR)
    dead_letter_everything(ops, at=later + timedelta(hours=1))
    items = ops.client.get(f"{BASE}/outbox/dead").json()["items"]
    assert [item["summary"]["document_id"] for item in items] == [
        second["document_id"],
        first["document_id"],
    ]
    newest = items[0]
    assert (newest["topic"], newest["status"], newest["attempts"]) == (
        "document.discovered",
        "dead",
        1,
    )
    assert newest["dead_at"] == (later + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert "broker unavailable" in newest["last_error"]
    assert (newest["summary"]["regulator"], newest["summary"]["external_ref"]) == ("CBIC", "")
    assert "title" not in newest["summary"], "a summary keeps no text of the document"
    assert newest["payload_bytes"] > 0
    assert newest["key"] == newest["summary"]["source_id"]
    page_one = ops.client.get(f"{BASE}/outbox/dead", params={"limit": 1}).json()
    page_two = ops.client.get(
        f"{BASE}/outbox/dead", params={"limit": 1, "cursor": page_one["next_cursor"]}
    ).json()
    assert [item["event_id"] for item in page_two["items"]] == [items[1]["event_id"]]
    none = ops.client.get(f"{BASE}/outbox/dead", params={"topic": "document.parsed"}).json()
    assert none["items"] == []
    bad = ops.client.get(f"{BASE}/outbox/dead", params={"topic": "Not a topic"})
    assert bad.status_code == 422


def test_a_dead_row_is_requeued_once_audited_and_relayed(ops: Ops) -> None:
    ops.upload(NOTIFICATION)
    dead_letter_everything(ops, at=datetime.now(UTC) + timedelta(minutes=1))
    (item,) = ops.client.get(f"{BASE}/outbox/dead").json()["items"]
    event_id = item["event_id"]
    body = {"actor_id": str(ACTOR), "reason": "Example: the broker is back"}
    requeued = ops.client.post(f"{BASE}/outbox/{event_id}/requeue", json=body, headers=WRITE)
    assert requeued.status_code == 200, requeued.text
    answer = requeued.json()
    assert answer["requeued"]
    assert (answer["event"]["status"], answer["event"]["attempts"]) == ("pending", 0)
    assert answer["event"]["dead_at"] is None
    assert "broker unavailable" in answer["event"]["last_error"], "kept until a send succeeds"
    (entry,) = ops.audit("pipeline.outbox.requeue")
    assert (entry.subject_type, entry.subject_id) == ("outbox_event", event_id)
    assert entry.before is not None
    assert entry.after is not None
    assert (entry.before["status"], entry.after["status"]) == ("dead", "pending")
    assert ops.client.get(f"{BASE}/outbox/dead").json()["items"] == []

    again = ops.client.post(f"{BASE}/outbox/{event_id}/requeue", json=body, headers=WRITE)
    assert (again.status_code, again.json()["requeued"]) == (200, False)
    assert len(ops.audit("pipeline.outbox.requeue")) == 1, "nothing written twice"

    producer = FakeProducer()
    relay = OutboxRelay(
        store=ops.store.outbox,
        producer=producer,
        clock=lambda: datetime.now(UTC) + timedelta(days=1),
    )
    asyncio.run(relay.run_once())
    assert producer.topics() == ["document.discovered"]
    row = ops.store.outbox.rows[UUID(event_id)]
    assert (row.status, row.last_error) == ("published", "")
    published = ops.client.post(f"{BASE}/outbox/{event_id}/requeue", json=body, headers=WRITE)
    assert (published.json()["requeued"], published.json()["event"]["status"]) == (
        False,
        "published",
    )
    unknown = ops.client.post(f"{BASE}/outbox/{uuid4()}/requeue", json=body, headers=WRITE)
    assert (unknown.status_code, problem(unknown)) == (404, "pipeline-outbox-event-not-found")
    no_token = ops.client.post(f"{BASE}/outbox/{event_id}/requeue", json=body)
    assert no_token.status_code == 401


def test_a_persons_type_is_kept_as_the_documents_classification(ops: Ops) -> None:
    """The type a person gave is the classification, the stored document is unchanged."""
    document_id = ops.upload(GUIDE, title="Example user guide for the return portal")["document_id"]
    ops.classify(document_id)
    ops.retry(document_id, "example-key-14", stage="parse", doc_type="circular")
    stored = ops.store.classifications[DocumentId(UUID(document_id))]
    assert (stored.relevance, stored.confidence, stored.classifier) == (
        Relevance.RELEVANT,
        TypeConfidence.CERTAIN,
        RETRY,
    )
    assert ops.store.documents[DocumentId(UUID(document_id))].status is DocumentStatus.CLASSIFIED
    assert ops.store.documents[DocumentId(UUID(document_id))].doc_type is None, (
        "the stored document's own type stays the uploader's"
    )
    assert date(2000, 1, 2) == ops.store.documents[DocumentId(UUID(document_id))].published_on
