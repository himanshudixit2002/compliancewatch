"""The pipeline's rulebook client against the rulebook app, in process: what one sends the other
accepts, and both derive the same clause ids. Runs the recorded 01/2026-Central Tax PDF (English
and Hindi) through the real parser, so the contract covers real clause text, and fills the
clause search index through the embedding stage."""

import base64
import dataclasses
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from domain_kernel.documents import DocumentRef, RawDocument, clause_id_for
from domain_kernel.ids import SourceId
from pipeline.application.embedding import EmbeddingStage
from pipeline.domain.embedding import embedding_text
from pipeline.domain.errors import RulebookConflictError, RulebookRejectedError
from pipeline.domain.knowledge import DocumentRecord
from pipeline.infrastructure.parsers import PdfParser
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.testing import ScriptedEmbedder, hash_vector
from rulebook.main import build_app
from rulebook.testing import WRITE_TOKEN, rulebook_settings

FIXTURES = Path(__file__).resolve().parents[4] / "services" / "pipeline" / "tests" / "fixtures"
SOURCE = SourceId(UUID(int=11))


def recorded(name: str) -> DocumentRecord:
    wrapper = json.loads((FIXTURES / "cbic" / name).read_text(encoding="utf-8"))
    ref = DocumentRef(SOURCE, f"https://example.invalid/{name}", "01/2026-Central Tax")
    raw = RawDocument.from_bytes(
        ref,
        base64.b64decode(wrapper["data"]),
        "application/pdf",
        fetched_at=datetime(2026, 9, 28, tzinfo=UTC),
    )
    return DocumentRecord(
        document=PdfParser().parse(raw),
        source_id=SOURCE,
        sha256=raw.sha256,
        regulator="CBIC",
        url=ref.url,
        media_type=raw.media_type,
        fetched_at=raw.fetched_at,
        external_ref=ref.external_ref,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_app(rulebook_settings())) as test_client:
        yield test_client


@pytest.mark.parametrize("name", ["gst-ct-01-2026.pdf.json", "gst-ct-01h-2026.pdf.json"])
def test_a_recorded_notification_registers_and_reads_back(client: TestClient, name: str) -> None:
    record = recorded(name)
    rulebook = HttpRulebook(token=WRITE_TOKEN, client=client)
    first = rulebook.register_document(record)
    again = rulebook.register_document(record)
    assert (first.created, again.created) == (True, False)
    document = record.document
    assert first.clause_ids == {
        clause.clause_ref: clause_id_for(document.document_id, clause.clause_ref)
        for clause in document.clauses
    }
    stored = client.get(f"/v1/rulebook/documents/{document.document_id}").json()
    assert [c["text"] for c in stored["clauses"]] == [c.text for c in document.clauses]
    assert stored["parser_version"] == "pdf@1"


def test_a_different_parse_of_the_same_bytes_is_a_conflict(client: TestClient) -> None:
    record = recorded("gst-ct-01-2026.pdf.json")
    rulebook = HttpRulebook(token=WRITE_TOKEN, client=client)
    rulebook.register_document(record)
    fewer = dataclasses.replace(record.document, clauses=record.document.clauses[:2])
    with pytest.raises(RulebookConflictError, match="409"):
        rulebook.register_document(dataclasses.replace(record, document=fewer))


def test_a_wrong_token_is_rejected(client: TestClient) -> None:
    with pytest.raises(RulebookRejectedError, match="401"):
        HttpRulebook(token="wrong", client=client).register_document(
            recorded("gst-ct-01-2026.pdf.json")
        )


def test_the_embedding_stage_fills_the_search_index(client: TestClient) -> None:
    record = recorded("gst-ct-01-2026.pdf.json")
    rulebook = HttpRulebook(token=WRITE_TOKEN, client=client)
    rulebook.register_document(record)
    document = record.document
    waiting = rulebook.unembedded_clauses(ScriptedEmbedder.MODEL, document_id=document.document_id)
    assert [c.clause_ref for c in sorted(waiting, key=lambda c: c.clause_ref)] == sorted(
        c.clause_ref for c in document.clauses
    )
    assert {(c.regulator, c.external_ref) for c in waiting} == {("CBIC", "01/2026-Central Tax")}
    stage = EmbeddingStage(ScriptedEmbedder(), rulebook, batch_size=2)
    run = stage.embed_missing(document.document_id)
    assert (run.embedded, run.unchanged) == (len(document.clauses), 0)
    assert rulebook.unembedded_clauses(ScriptedEmbedder.MODEL) == ()
    third = next(c for c in waiting if c.clause_ref == document.clauses[2].clause_ref)
    body = {
        "text": "GSTR-3B",
        "vector": list(hash_vector(embedding_text(third))),
        "model": ScriptedEmbedder.MODEL,
        "k": 3,
    }
    hits = client.post("/v1/rulebook/search", json=body).json()
    nearest = next(hit for hit in hits if hit["vector_rank"] == 1)
    assert nearest["clause_id"] == str(third.clause_id)
