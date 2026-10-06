"""A triage's resolution through the task routes, on the memory store in header mode.

A synthetic circular is uploaded to the CBIC notifications source and classified as the worker
would (``pipeline.classify_document``): its text names another type than its source publishes,
so a triage task opens. The analyst's decision resolves it: relevant with a type continues the
document through an ingest of the stored document; irrelevant sets it aside. The stored
document's own type is never changed."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.audit import AuditActor
from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId, UserId
from pipeline.application.activities import ParseRequest, Stored
from pipeline.application.classify import ClassifyDocument
from pipeline.application.sources import AdminAction
from pipeline.application.tasks import ResolveTask, triage_workflow_id
from pipeline.domain.classification import TRIAGE, Relevance, TriageDecision, TypeConfidence
from pipeline.domain.errors import TaskClosedError
from pipeline.domain.events import DocumentClassified
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.tasks import PipelineTask, TaskKind, TaskStatus
from pipeline.infrastructure.adapters import RegistryAdapterTypes, RegistryCatalog
from pipeline.infrastructure.http import PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.main import build_app
from pipeline.testing import (
    WRITE_TOKEN,
    LockRace,
    MemoryCrawls,
    MemoryIngests,
    pipeline_settings,
)
from pipeline.workflows import IngestRequest

BASE = "/v1/pipeline"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
ANALYST = UUID(int=99)
OTHER_ANALYST = UUID(int=98)
REASON = "Read the text for the tests: it clarifies the law"
FIELDS = {"actor_id": str(ANALYST), "reason": REASON}
NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
CIRCULAR = (
    b"<html><head><title>Circular No. 5/2026-GST</title></head><body>"
    b"<h1>Circular No. 5/2026-GST</h1>"
    b"<p>Subject: Example clarification on Notification No. 12/2024 - Central Tax.</p>"
    b"</body></html>"
)


class Triage:
    def __init__(self, client: TestClient, store: MemoryStore, raw: MemoryRawStore) -> None:
        self.client = client
        self.store = store
        self.raw = raw
        app = client.app
        assert isinstance(app, FastAPI)
        self.ingests: MemoryIngests = app.state.ingests

    def conflict(self) -> PipelineTask:
        """Upload the circular, then parse and classify it as the worker does."""
        uploaded = self.client.post(
            f"{BASE}/sources/cbic_notifications/uploads",
            files={"file": ("circular.html", CIRCULAR, "text/html")},
            data={**FIELDS, "title": "Circular No. 5/2026-GST"},
            headers=WRITE,
        )
        assert uploaded.status_code == 202, uploaded.text
        start = self.ingests.started[-1]
        request = IngestRequest.model_validate(ingest_payload(start))
        assert request.stored is not None
        with self.store() as unit:
            unit.documents.record_parse(start.record.document_id, "html@1")
        chain = ParserChain(RegistryCatalog(PoliteClient()))
        classify = ClassifyDocument(chain, self.raw, self.store, extraction=True)
        found = classify.classify(self.parse(request.stored))
        assert found.route == "triage"
        assert found.task_id is not None
        return next(iter(self.store.tasks.values()))

    @staticmethod
    def parse(stored: Stored) -> ParseRequest:
        return ParseRequest(document_id=stored.document_id, stored=stored)

    def resolve(self, task: PipelineTask, triage: Any, **body: Any) -> Any:
        return self.client.post(
            f"{BASE}/tasks/{task.id}/resolve",
            json={**FIELDS, "triage": triage, **body},
            headers=WRITE,
        )

    def classified(self) -> list[DocumentClassified]:
        return [e for e in self.store.events if isinstance(e, DocumentClassified)]

    def resolver(self) -> ResolveTask:
        """The resolution as the app wires it, on the store itself."""
        return ResolveTask(
            self.store, self.raw, self.ingests, RegistryAdapterTypes(), knowledge=True
        )

    def by_another(self, task: PipelineTask, decision: TriageDecision) -> Callable[[], object]:
        """Another analyst's request resolving ``task`` with ``decision``."""
        admin = AdminAction(actor=AuditActor.user(UserId(OTHER_ANALYST)), reason=REASON)
        return lambda: self.resolver().run(task.id, None, admin, triage=decision)


@contextmanager
def app_on(race: LockRace) -> Iterator[Triage]:
    raw, ingests = MemoryRawStore(), MemoryIngests()
    app = build_app(
        pipeline_settings(pipeline_knowledge_enabled=True),
        units=race,
        raw_store=raw,
        starter=MemoryCrawls(),
        adapter_types=RegistryAdapterTypes(),
        ingests=ingests,
    )
    app.state.ingests = ingests
    with TestClient(app) as client:
        yield Triage(client, race.store, raw)


@pytest.fixture
def race() -> LockRace:
    return LockRace(MemoryStore())


@pytest.fixture
def triage(race: LockRace) -> Iterator[Triage]:
    with app_on(race) as wired:
        yield wired


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def test_a_relevant_triage_classifies_the_document_and_continues_it(triage: Triage) -> None:
    task = triage.conflict()
    response = triage.resolve(task, {"relevance": "relevant", "doc_type": "circular"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["task"]["status"], body["task"]["resolved_by"], body["task"]["note"]) == (
        "resolved",
        str(ANALYST),
        REASON,
    )
    assert body["task"]["resolution"] == {
        "relevance": "relevant",
        "doc_type": "circular",
        "route": "extract",
    }
    assert body["task"]["document"]["status"] == "classified"
    assert (body["workflow_id"], body["started"]) == (
        f"pipeline-triage-{task.id.value.hex}",
        True,
    )
    start = triage.ingests.started[-1]
    request = IngestRequest.model_validate(ingest_payload(start))
    assert (request.knowledge, request.regulator, request.transcript_key) == (True, "CBIC", "")
    assert request.stored is not None
    assert request.stored.duplicate
    document_id = DocumentId(task.document_id.value)
    decided = triage.store.classifications[document_id]
    assert (decided.classifier, decided.confidence, decided.decided_by, decided.task_id) == (
        TRIAGE,
        TypeConfidence.CERTAIN,
        ANALYST,
        task.id,
    )
    assert decided.reasons == ("an analyst triaged it as a circular", REASON)
    assert triage.store.documents[document_id].doc_type is None, "the uploader's type stays"
    conflict, resolved = triage.classified()
    assert (conflict.confidence, resolved.confidence, resolved.classifier) == (
        TypeConfidence.CONFLICT,
        TypeConfidence.CERTAIN,
        TRIAGE,
    )
    entry = triage.store.audit[-1]
    assert (entry.action, entry.subject_id) == ("pipeline.task.resolve", str(task.id))
    assert entry.after is not None
    assert entry.after["resolution"] == body["task"]["resolution"]

    again = triage.resolve(task, {"relevance": "relevant", "doc_type": "circular"})
    assert (again.status_code, again.json()["started"]) == (200, False), "the same, idempotent"
    assert len(triage.classified()) == 2
    other = triage.resolve(task, {"relevance": "relevant", "doc_type": "notification"})
    assert (other.status_code, problem(other)) == (409, "pipeline-task-closed")


def test_an_irrelevant_triage_sets_the_document_aside(triage: Triage) -> None:
    task = triage.conflict()
    starts = len(triage.ingests.started)
    response = triage.resolve(task, {"relevance": "irrelevant"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["workflow_id"], body["started"]) == ("", False)
    assert body["task"]["resolution"] == {
        "relevance": "irrelevant",
        "doc_type": None,
        "route": "irrelevant",
    }
    assert body["task"]["document"]["status"] == "irrelevant"
    assert len(triage.ingests.started) == starts, "nothing starts"
    decided = triage.store.classifications[DocumentId(task.document_id.value)]
    assert (decided.relevance, decided.doc_type.value) == (Relevance.IRRELEVANT, "circular")
    again = triage.resolve(task, {"relevance": "irrelevant"})
    assert (again.status_code, again.json()["workflow_id"]) == (200, "")


def test_a_statute_is_kept_for_reference_and_continued(triage: Triage) -> None:
    task = triage.conflict()
    response = triage.resolve(task, {"relevance": "relevant", "doc_type": "statute"})
    assert response.status_code == 200, response.text
    assert response.json()["task"]["resolution"]["route"] == "reference"
    assert response.json()["task"]["document"]["status"] == "reference"
    assert response.json()["started"] is True


@pytest.mark.parametrize(
    ("triage_body", "extra", "status", "kind"),
    [
        ({"relevance": "relevant"}, {}, 422, "request-invalid"),
        ({"relevance": "irrelevant", "doc_type": "circular"}, {}, 422, "request-invalid"),
        ({"relevance": "maybe"}, {}, 422, "request-invalid"),
        (
            {"relevance": "relevant", "doc_type": "circular"},
            {"transcript": {"blocks": [{"type": "heading", "text": "Example"}]}},
            422,
            "pipeline-task-resolution-invalid",
        ),
        (None, {}, 422, "pipeline-task-resolution-invalid"),
    ],
    ids=["relevant-without-type", "irrelevant-with-type", "unknown", "with-transcript", "none"],
)
def test_a_triage_resolution_that_does_not_fit_is_refused(
    triage: Triage, triage_body: Any, extra: dict[str, Any], status: int, kind: str
) -> None:
    task = triage.conflict()
    body = dict(extra)
    if triage_body is not None:
        body["triage"] = triage_body
    response = triage.client.post(
        f"{BASE}/tasks/{task.id}/resolve", json={**FIELDS, **body}, headers=WRITE
    )
    assert (response.status_code, problem(response)) == (status, kind)
    assert triage.store.tasks[task.id].status is TaskStatus.OPEN


def test_a_manual_parse_takes_no_triage_and_a_dismissed_triage_stays_held(
    triage: Triage,
) -> None:
    task = triage.conflict()
    with triage.store() as unit:
        record = unit.documents.get(task.document_id)
        assert record is not None
        manual = unit.tasks.open(
            PipelineTask.opened(TaskKind.MANUAL_PARSE, task.document_id, record.source_key, at=NOW)
        )
    refused = triage.resolve(manual, {"relevance": "relevant", "doc_type": "circular"})
    assert (refused.status_code, problem(refused)) == (422, "pipeline-task-resolution-invalid")
    dismissed = triage.client.post(
        f"{BASE}/tasks/{task.id}/dismiss",
        json={"actor_id": str(ANALYST), "reason": "Not ours to decide today"},
        headers=WRITE,
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["document"]["status"] == DocumentStatus.TRIAGE.value


def test_resolve_task_replays_the_decision_another_request_wrote_while_it_waited(
    triage: Triage, race: LockRace
) -> None:
    task = triage.conflict()
    decision = TriageDecision(Relevance.RELEVANT, DocumentType.CIRCULAR)
    resolve = ResolveTask(race, triage.raw, triage.ingests, RegistryAdapterTypes(), knowledge=True)
    admin = AdminAction(actor=AuditActor.user(UserId(ANALYST)), reason=REASON)
    race.let_in(triage.by_another(task, decision), before=2)
    replayed = resolve.run(task.id, None, admin, triage=decision)
    assert (replayed.workflow_id, replayed.started) == (triage_workflow_id(task.id), False)
    assert (replayed.task.task.status, replayed.task.task.resolved_by) == (
        TaskStatus.RESOLVED,
        OTHER_ANALYST,
    ), "the first request's resolution stands"
    started = [start.workflow_id for start in triage.ingests.started]
    assert started.count(triage_workflow_id(task.id)) == 1, "one ingest, the first request's"
    assert [entry.action for entry in triage.store.audit].count("pipeline.task.resolve") == 1
    assert len(triage.classified()) == 2, "the conflict's, then the first decision's"
    with pytest.raises(TaskClosedError):
        resolve.run(task.id, None, admin, triage=TriageDecision(Relevance.IRRELEVANT))


def test_the_same_decision_sent_twice_at_once_answers_both(triage: Triage, race: LockRace) -> None:
    task = triage.conflict()
    race.let_in(
        triage.by_another(task, TriageDecision(Relevance.RELEVANT, DocumentType.CIRCULAR)),
        before=2,
    )
    response = triage.resolve(task, {"relevance": "relevant", "doc_type": "circular"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["workflow_id"], body["started"]) == (triage_workflow_id(task.id), False)
    assert body["task"]["resolution"] == {
        "relevance": "relevant",
        "doc_type": "circular",
        "route": "extract",
    }
    assert body["task"]["resolved_by"] == str(OTHER_ANALYST), "the first request's resolution"
    assert body["task"]["document"]["status"] == "classified"
    started = [start.workflow_id for start in triage.ingests.started]
    assert started.count(triage_workflow_id(task.id)) == 1
    assert [entry.action for entry in triage.store.audit].count("pipeline.task.resolve") == 1
    assert len(triage.classified()) == 2


def test_another_decision_written_while_it_waited_is_refused(
    triage: Triage, race: LockRace
) -> None:
    task = triage.conflict()
    race.let_in(triage.by_another(task, TriageDecision(Relevance.IRRELEVANT)), before=2)
    response = triage.resolve(task, {"relevance": "relevant", "doc_type": "circular"})
    assert (response.status_code, problem(response)) == (409, "pipeline-task-closed")
    resolution = triage.store.tasks[task.id].resolution
    assert resolution is not None
    assert resolution["relevance"] == "irrelevant", "the first decision stands"
    assert len(triage.classified()) == 2
    assert [entry.action for entry in triage.store.audit].count("pipeline.task.resolve") == 1
