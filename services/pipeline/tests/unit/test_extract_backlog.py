"""The classified backlog and its command: the documents that wait as classified with no extraction
for the current prompt, counted per source, and the sweep that extracts them, refused while the
extraction is off."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from domain_kernel.documents import DocumentType, document_id_for
from pipeline.application.backlog import MAX_BATCH, ExtractionBacklog
from pipeline.application.extraction import RULE_PROMPT_REF
from pipeline.application.sources import SyncSources
from pipeline.domain.classification import Classification, Relevance, TypeConfidence
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction, candidate_id_for
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source
from pipeline.extract_backlog import run, sweep_workflow_id
from pipeline.infrastructure.adapters import SOURCES, RegistryAdapterTypes
from pipeline.infrastructure.memory import MemoryStore
from pipeline.testing import pipeline_settings
from pipeline.workflows import BacklogRequest

NOW = datetime(2000, 1, 3, 6, 0, tzinfo=UTC)
TYPES = RegistryAdapterTypes()


def stored(content: bytes, key: str = "cbic_notifications", minutes: int = 0) -> RawDocumentRecord:
    digest = hashlib.sha256(content).hexdigest()
    return RawDocumentRecord(
        document_id=document_id_for(digest),
        source_key=key,
        source_url=f"upload://{key}/{digest}",
        fetched_at=NOW + timedelta(minutes=minutes),
        content_type="application/pdf",
        size=len(content),
        sha256=digest,
        storage_key=f"{digest[:2]}/{digest}",
        external_ref=f"Example {minutes}/2000",
        status=DocumentStatus.CLASSIFIED,
        parser_version="pdf@1",
    )


def classified(record: RawDocumentRecord, doc_type: DocumentType) -> Classification:
    return Classification(
        document_id=record.document_id,
        doc_type=doc_type,
        relevance=Relevance.RELEVANT,
        confidence=TypeConfidence.CERTAIN,
        reasons=("Example reason",),
        classified_at=NOW,
    )


def extracted(record: RawDocumentRecord) -> RuleExtraction:
    return RuleExtraction(
        document_id=record.document_id,
        prompt_version=RULE_PROMPT_REF,
        candidate_id=candidate_id_for(record.document_id, RULE_PROMPT_REF),
        outcome=ExtractionOutcome.UNPARSEABLE,
        model="fake/echo",
        attempts=2,
        source_key=record.source_key,
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


def backlog_store() -> tuple[MemoryStore, list[RawDocumentRecord]]:
    """Two notifications and a circular waiting, one notification extracted though still
    classified, and a press release kept for reference."""
    store = MemoryStore()
    SyncSources(store, [spec.definition() for spec in SOURCES.values()]).run()
    first = stored(b"%PDF example one", minutes=1)
    second = stored(b"%PDF example two", minutes=2)
    circular = stored(b"%PDF example circular", key="cbic_circulars", minutes=3)
    done = stored(b"%PDF example done", minutes=4)
    reference = stored(b"%PDF example press", key="gstn_advisories", minutes=5)
    with store() as unit:
        for record in (first, second, circular, done):
            unit.documents.add(record)
            unit.classifications.add(
                classified(
                    record,
                    DocumentType.CIRCULAR if record is circular else DocumentType.NOTIFICATION,
                )
            )
        unit.documents.add(reference)
        unit.documents.set_status(reference.document_id, DocumentStatus.REFERENCE)
        unit.extractions.add(extracted(done))
        unit.documents.set_status(done.document_id, DocumentStatus.CLASSIFIED)
    return store, [first, second, circular]


def test_the_backlog_counts_per_source_and_asks_as_the_ingest_would() -> None:
    store, (first, second, circular) = backlog_store()
    backlog = ExtractionBacklog(store, TYPES).run()
    assert dict(backlog.waiting) == {"cbic_notifications": 2, "cbic_circulars": 1}
    assert backlog.total == 3, "the extracted one and the reference are not waiting"
    assert [r.document_id for r in backlog.requests] == [
        first.document_id.value,
        second.document_id.value,
        circular.document_id.value,
    ], "the first fetched first"
    request = backlog.requests[2]
    assert (request.source_key, request.regulator, request.doc_type, request.own_ref) == (
        "cbic_circulars",
        "CBIC",
        DocumentType.CIRCULAR,
        "Example 3/2000",
    )
    one = ExtractionBacklog(store, TYPES).run(source_key="cbic_circulars", limit=MAX_BATCH + 5)
    assert (dict(one.waiting), len(one.requests)) == ({"cbic_circulars": 1}, 1)
    capped = ExtractionBacklog(store, TYPES).run(limit=1)
    assert (capped.total, len(capped.requests)) == (3, 1)


def test_a_document_of_a_source_the_code_cannot_read_is_left_out() -> None:
    store, _ = backlog_store()
    with store() as unit:
        unit.sources.add(
            Source(
                key="retired",
                adapter_type="gone",
                parameters={},
                cadence=timedelta(hours=1),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        orphan = stored(b"%PDF example orphan", key="retired", minutes=9)
        unit.documents.add(orphan)
        unit.classifications.add(classified(orphan, DocumentType.NOTIFICATION))
    backlog = ExtractionBacklog(store, TYPES).run()
    assert backlog.waiting["retired"] == 1
    assert orphan.document_id.value not in [r.document_id for r in backlog.requests]


class Starter:
    def __init__(self, fails: Exception | None = None) -> None:
        self.started: list[tuple[str, dict[str, object]]] = []
        self.fails = fails

    def start(self, workflow_id: str, payload: dict[str, object]) -> bool:
        if self.fails is not None:
            raise self.fails
        self.started.append((workflow_id, payload))
        return True


def command(
    *args: str, enabled: bool = True, store: Any = None, starter: Starter | None = None
) -> tuple[int, Starter]:
    used = starter or Starter()
    code = run(
        list(args),
        settings=pipeline_settings(pipeline_extraction_enabled=enabled),
        units=store if store is not None else backlog_store()[0],
        types=TYPES,
        starter=used,
        request_ids=lambda: UUID(int=5),
    )
    return code, used


def test_a_dry_run_counts_whatever_the_flag(capsys: pytest.CaptureFixture[str]) -> None:
    code, starter = command("--dry-run", enabled=False)
    assert (code, starter.started) == (0, [])
    out = capsys.readouterr().out
    assert "| cbic_notifications | 2 |" in out
    assert "3 document(s) wait as classified; the extraction is off" in out


def test_the_sweep_is_refused_while_the_extraction_is_off(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, starter = command(enabled=False)
    assert (code, starter.started) == (2, [])
    assert "refused: CW_PIPELINE_EXTRACTION_ENABLED is off" in capsys.readouterr().err


def test_the_sweep_starts_with_every_waiting_document(capsys: pytest.CaptureFixture[str]) -> None:
    code, starter = command("--concurrency", "2")
    assert code == 0
    ((workflow_id, payload),) = starter.started
    assert (
        workflow_id
        == sweep_workflow_id(UUID(int=5))
        == f"pipeline-extract-backlog-{UUID(int=5).hex}"
    )
    request = BacklogRequest.model_validate(payload)
    assert (len(request.documents), request.concurrency) == (3, 2)
    assert f"started {workflow_id}: 3 document(s), 2 at a time" in capsys.readouterr().out


def test_the_command_answers_in_json(capsys: pytest.CaptureFixture[str]) -> None:
    store, _ = backlog_store()
    capsys.readouterr()
    code, _ = command("--json", "--source", "cbic_notifications", store=store)
    assert code == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["waiting"] == {"cbic_notifications": 2}
    assert answer["sweep"]["documents"] == 2
    assert answer["prompt_version"] == RULE_PROMPT_REF


def test_nothing_waiting_starts_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    empty = MemoryStore()
    code, starter = command(store=empty)
    assert (code, starter.started) == (0, [])
    assert "nothing waits: no sweep started" in capsys.readouterr().out


def test_a_store_or_temporal_that_does_not_answer_is_exit_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Away:
        def __call__(self) -> Any:
            raise ConnectionError("example database away")

    code, _ = command(store=Away())
    assert code == 1
    assert "cannot read the store" in capsys.readouterr().err
    code, _ = command(starter=Starter(fails=RuntimeError("example temporal away")))
    assert code == 1
    assert "the sweep did not start" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--limit", "0"], ["--concurrency", "11"]])
def test_bounds_are_checked(args: list[str]) -> None:
    with pytest.raises(SystemExit):
        command(*args)
