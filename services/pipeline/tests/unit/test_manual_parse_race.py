"""Two resolutions of one manual parse at once, as the triage's got in M2-5: the second waits for
the task's row lock, then finds the task resolved. The same transcript replays the first
resolution (200, its ingest, started once); another transcript is refused (409). Both through the
use case and through the route, on the memory store with a ``LockRace`` that lets the other
request in just before the second unit of work opens, where the resolution locks the task."""

import hashlib
import io
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from domain_kernel.audit import AuditActor
from domain_kernel.ids import DocumentId, UserId
from pipeline.application.sources import AdminAction
from pipeline.application.tasks import ResolveTask, manual_parse_workflow_id
from pipeline.domain.errors import TaskClosedError
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.tasks import PipelineTask, TaskKind, TaskStatus
from pipeline.domain.transcripts import Transcript, read_transcript
from pipeline.infrastructure.adapters import RegistryAdapterTypes
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.main import build_app
from pipeline.testing import (
    WRITE_TOKEN,
    LockRace,
    MemoryCrawls,
    MemoryIngests,
    pipeline_settings,
)

BASE = "/v1/pipeline"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
ANALYST = UUID(int=71)
OTHER_ANALYST = UUID(int=72)
REASON = "Typed the example scan by hand for the tests"
NOW = datetime(2000, 1, 3, 6, 0, tzinfo=UTC)
TRANSCRIPT: dict[str, Any] = {
    "title": "Example statute",
    "blocks": [
        {"type": "heading", "text": "Example chapter"},
        {"type": "paragraph", "number": "1.", "text": "Example text of the first section."},
    ],
}
OTHER_TRANSCRIPT: dict[str, Any] = {**TRANSCRIPT, "title": "Another example statute"}


def scan() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class Scanned:
    """The app on a ``LockRace`` over its memory store, with a scan uploaded and its manual-parse
    task open, as the ingest leaves a document no parser reads."""

    def __init__(self, client: TestClient, race: LockRace, raw: MemoryRawStore) -> None:
        self.client = client
        self.race = race
        self.store = race.store
        self.raw = raw
        self.ingests: MemoryIngests = client.app.state.ingests  # type: ignore[attr-defined]
        uploaded = client.post(
            f"{BASE}/sources/cgst_rules/uploads",
            files={"file": ("scan.pdf", scan(), "application/pdf")},
            data={"actor_id": str(ANALYST), "reason": REASON},
            headers=WRITE,
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = DocumentId(UUID(hashlib.sha256(scan()).hexdigest()[:32]))
        with self.store() as unit:
            unit.documents.set_status(document_id, DocumentStatus.FAILED)
            self.task = unit.tasks.open(
                PipelineTask.opened(
                    TaskKind.MANUAL_PARSE,
                    document_id,
                    "cgst_rules",
                    at=NOW,
                    reason="pdf@1: UnparsedDocumentError: the PDF has no text layer",
                )
            )

    def resolver(self, units: Any = None) -> ResolveTask:
        return ResolveTask(
            units or self.store, self.raw, self.ingests, RegistryAdapterTypes(), knowledge=True
        )

    def by_another(self, transcript: dict[str, Any]) -> Callable[[], object]:
        """Another analyst's request resolving the task with ``transcript``, on the store."""
        admin = AdminAction(actor=AuditActor.user(UserId(OTHER_ANALYST)), reason=REASON)
        return lambda: self.resolver().run(self.task.id, read_transcript(transcript), admin)

    def resolves(self) -> int:
        return [entry.action for entry in self.store.audit].count("pipeline.task.resolve")

    def manual_starts(self) -> int:
        workflow_id = manual_parse_workflow_id(self.task.id)
        return [start.workflow_id for start in self.ingests.started].count(workflow_id)


@contextmanager
def scanned() -> Iterator[Scanned]:
    race, raw, ingests = LockRace(MemoryStore()), MemoryRawStore(), MemoryIngests()
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
        yield Scanned(client, race, raw)


@pytest.fixture
def wired() -> Iterator[Scanned]:
    with scanned() as found:
        yield found


def transcript_of(body: dict[str, Any]) -> Transcript:
    return read_transcript(body)


def test_the_use_case_replays_the_same_transcript_another_request_wrote_while_it_waited(
    wired: Scanned,
) -> None:
    admin = AdminAction(actor=AuditActor.user(UserId(ANALYST)), reason=REASON)
    wired.race.let_in(wired.by_another(TRANSCRIPT), before=2)
    replayed = wired.resolver(wired.race).run(wired.task.id, transcript_of(TRANSCRIPT), admin)
    assert (replayed.workflow_id, replayed.started) == (
        manual_parse_workflow_id(wired.task.id),
        False,
    )
    assert (replayed.task.task.status, replayed.task.task.resolved_by) == (
        TaskStatus.RESOLVED,
        OTHER_ANALYST,
    ), "the first request's resolution stands"
    assert wired.manual_starts() == 1, "one ingest, the first request's"
    assert wired.resolves() == 1, "one resolution written and audited"


def test_the_use_case_refuses_another_transcript_written_while_it_waited(wired: Scanned) -> None:
    admin = AdminAction(actor=AuditActor.user(UserId(ANALYST)), reason=REASON)
    wired.race.let_in(wired.by_another(OTHER_TRANSCRIPT), before=2)
    with pytest.raises(TaskClosedError, match="is resolved"):
        wired.resolver(wired.race).run(wired.task.id, transcript_of(TRANSCRIPT), admin)
    resolution = wired.store.tasks[wired.task.id].resolution
    assert resolution is not None
    other = hashlib.sha256(transcript_of(OTHER_TRANSCRIPT).encoded()).hexdigest()
    assert resolution["transcript_sha256"] == other, "the first transcript stands"
    assert (wired.resolves(), wired.manual_starts()) == (1, 1)


def post(wired: Scanned, transcript: dict[str, Any]) -> Any:
    return wired.client.post(
        f"{BASE}/tasks/{wired.task.id}/resolve",
        json={"actor_id": str(ANALYST), "reason": REASON, "transcript": transcript},
        headers=WRITE,
    )


def test_the_same_transcript_sent_twice_at_once_answers_both(wired: Scanned) -> None:
    wired.race.let_in(wired.by_another(TRANSCRIPT), before=2)
    response = post(wired, TRANSCRIPT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["workflow_id"], body["started"]) == (
        manual_parse_workflow_id(wired.task.id),
        False,
    )
    assert (body["task"]["status"], body["task"]["resolved_by"]) == (
        "resolved",
        str(OTHER_ANALYST),
    ), "the first request's resolution"
    assert body["task"]["resolution"]["parser_version"] == "manual@1"
    assert (wired.resolves(), wired.manual_starts()) == (1, 1)


def test_another_transcript_sent_while_the_first_is_written_is_a_409(wired: Scanned) -> None:
    wired.race.let_in(wired.by_another(OTHER_TRANSCRIPT), before=2)
    response = post(wired, TRANSCRIPT)
    assert response.status_code == 409, response.text
    assert response.json()["type"].rsplit(":", 1)[-1] == "pipeline-task-closed"
    assert (wired.resolves(), wired.manual_starts()) == (1, 1)
