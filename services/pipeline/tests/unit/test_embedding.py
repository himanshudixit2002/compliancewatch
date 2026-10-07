"""Clause embedding: the text sent, the stage's paging and checks, the activity and the backfill."""

import hashlib
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from domain_kernel.documents import Clause, DocumentType, ParsedDocument, document_id_for
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from domain_kernel.vectors import EMBEDDING_DIMS
from pipeline import embed
from pipeline.application.embedding import MODEL_PROBE, EmbeddingRun, EmbeddingStage
from pipeline.application.knowledge_activities import EmbedClauses, EmbedRequest
from pipeline.domain.embedding import (
    MAX_EMBEDDING_CHARS,
    ClauseToEmbed,
    ClauseVector,
    EmbeddingBatch,
    embedding_header,
    embedding_text,
)
from pipeline.domain.errors import EmbeddingContractError, RulebookRejectedError
from pipeline.domain.knowledge import DocumentRecord
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryRulebook, ScriptedEmbedder, hash_vector

CLAUSE = ClauseToEmbed(
    clause_id=ClauseId(UUID(int=1)),
    document_id=DocumentId(UUID(int=2)),
    clause_ref="en.p3",
    text="In exercise of the powers ...   the due date\nis extended till 21st April, 2026.",
    regulator="CBIC",
    doc_type=DocumentType.NOTIFICATION,
    external_ref="01/2026-Central Tax",
    title="Notification No. 01/2026 - Central Tax",
    published_at=date(2026, 1, 16),
)


def test_the_text_has_the_context_header_then_the_clause() -> None:
    assert embedding_text(CLAUSE) == (
        "CBIC | notification | 01/2026-Central Tax | 2026-01-16 | clause en.p3\n"
        "In exercise of the powers ... the due date is extended till 21st April, 2026."
    )


def test_the_title_stands_in_for_a_missing_number_and_absent_parts_are_left_out() -> None:
    clause = ClauseToEmbed(
        clause_id=CLAUSE.clause_id,
        document_id=CLAUSE.document_id,
        clause_ref="p1",
        text="Advisory text.",
        regulator="GSTN",
        doc_type=DocumentType.PRESS_RELEASE,
        title="  Advisory on\nGSTR-1A  ",
    )
    assert embedding_header(clause) == "GSTN | press release | Advisory on GSTR-1A | clause p1"
    untitled = ClauseToEmbed(
        CLAUSE.clause_id, CLAUSE.document_id, "p1", "x", "GSTN", DocumentType.CIRCULAR
    )
    assert embedding_text(untitled) == "GSTN | circular | clause p1\nx"


def test_a_long_clause_is_cut_at_max_chars_keeping_the_header() -> None:
    long = ClauseToEmbed(
        CLAUSE.clause_id, CLAUSE.document_id, "p9", "word " * 5_000, "CBIC", DocumentType.CIRCULAR
    )
    text = embedding_text(long)
    assert len(text) <= MAX_EMBEDDING_CHARS
    assert text.startswith("CBIC | circular | clause p9\nword word")
    assert not text.endswith(" ")
    assert len(embedding_text(long, max_chars=40)) <= 40
    with pytest.raises(ValueError, match="positive"):
        embedding_text(long, max_chars=0)


# ---------------------------------------------------------------- the stage

DIGEST = hashlib.sha256(b"notification 01/2026").hexdigest()


def stored(rulebook: MemoryRulebook, clauses: int, digest: str = DIGEST) -> DocumentId:
    document_id = document_id_for(digest)
    rulebook.register_document(
        DocumentRecord(
            document=ParsedDocument(
                document_id=document_id,
                doc_type=DocumentType.NOTIFICATION,
                title="Notification No. 01/2026 - Central Tax",
                clauses=tuple(Clause(f"en.p{n}", f"Clause {n} text.") for n in range(clauses)),
                published_at=date(2026, 1, 16),
            ),
            source_id=SourceId(UUID(int=11)),
            sha256=digest,
            regulator="CBIC",
            url="https://example.invalid/n.pdf",
            media_type="application/pdf",
            fetched_at=datetime(2026, 9, 28, tzinfo=UTC),
            external_ref="01/2026-Central Tax",
        )
    )
    return document_id


def test_the_scripted_vectors_are_deterministic_unit_vectors() -> None:
    vector = hash_vector("GSTR-3B")
    assert len(vector) == EMBEDDING_DIMS
    assert math.isclose(math.fsum(x * x for x in vector), 1.0)
    assert vector == hash_vector("GSTR-3B") != hash_vector("GSTR-1")
    assert len(hash_vector("x", 7)) == 7


def test_a_document_is_embedded_in_batches_under_the_probed_model() -> None:
    rulebook, embedder = MemoryRulebook(), ScriptedEmbedder()
    document_id = stored(rulebook, 150)
    other = stored(rulebook, 3, hashlib.sha256(b"other").hexdigest())
    run = EmbeddingStage(embedder, rulebook).embed_missing(
        document_id, metadata={"document_id": str(document_id)}
    )
    assert run == EmbeddingRun(ScriptedEmbedder.MODEL, embedded=150, unchanged=0)
    sizes = [len(texts) for texts, _, _ in embedder.requests]
    assert sizes == [1, 64, 64, 22]
    assert embedder.requests[0][0] == (MODEL_PROBE,)
    assert {model for _, model, _ in embedder.requests} == {None}
    assert embedder.requests[1][2] == {"document_id": str(document_id), "stage": "embedding"}
    assert embedder.requests[1][0][0].startswith("CBIC | notification | 01/2026-Central Tax |")
    assert len(rulebook.embeddings) == 150
    assert rulebook.unembedded_clauses(ScriptedEmbedder.MODEL, document_id=other)
    again = EmbeddingStage(embedder, rulebook).embed_missing(document_id)
    assert again == EmbeddingRun(ScriptedEmbedder.MODEL, 0, 0)


def test_every_document_with_a_limit_and_a_model_override() -> None:
    rulebook = MemoryRulebook()
    stored(rulebook, 5)
    stored(rulebook, 5, hashlib.sha256(b"other").hexdigest())
    embedder = ScriptedEmbedder()
    stage = EmbeddingStage(embedder, rulebook, batch_size=4)
    first = stage.embed_missing(None, limit=6, model="voyage/voyage-3.5-lite")
    assert first == EmbeddingRun("voyage/voyage-3.5-lite", 6, 0)
    assert [len(texts) for texts, _, _ in embedder.requests] == [1, 4, 2]
    assert {model for _, model, _ in embedder.requests} == {"voyage/voyage-3.5-lite"}
    rest = stage.embed_missing(None, model="voyage/voyage-3.5-lite")
    assert rest.embedded == 4
    assert stage.embed_missing(None).embedded == 10
    with pytest.raises(ValueError, match="positive"):
        stage.embed_missing(None, limit=0)
    with pytest.raises(ValueError, match="batch_size"):
        EmbeddingStage(embedder, rulebook, batch_size=65)


class RacingRulebook(MemoryRulebook):
    """Another run stores the vectors between this run's read and its write."""

    def unembedded_clauses(
        self,
        model: str,
        *,
        document_id: DocumentId | None = None,
        limit: int = 64,
        after: ClauseId | None = None,
    ) -> tuple[ClauseToEmbed, ...]:
        page = super().unembedded_clauses(model, document_id=document_id, limit=limit, after=after)
        for clause in page:
            self.embeddings[clause.clause_id, model] = hash_vector("earlier")
        return page


def test_clauses_another_run_embedded_first_count_as_unchanged() -> None:
    rulebook = RacingRulebook()
    document_id = stored(rulebook, 3)
    run = EmbeddingStage(ScriptedEmbedder(), rulebook).embed_missing(document_id)
    assert (run.embedded, run.unchanged) == (0, 3)


class WrongEmbedder(ScriptedEmbedder):
    def __init__(self, *, drop: int = 0, served: Mapping[int, str] | None = None) -> None:
        super().__init__()
        self._drop = drop
        self._served = dict(served or {})

    def embed(
        self,
        inputs: Sequence[str],
        *,
        model: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingBatch:
        batch = super().embed(inputs, model=model, metadata=metadata)
        call = len(self.requests)
        vectors = batch.vectors[: len(batch.vectors) - self._drop] if call > 1 else batch.vectors
        return EmbeddingBatch(self._served.get(call, batch.model), batch.dims, vectors)


@pytest.mark.parametrize(
    ("embedder", "message"),
    [
        (ScriptedEmbedder(dims=256), "256-dimensional vectors; the rulebook stores 512"),
        (WrongEmbedder(drop=1), "answered 2 vectors for 3 texts"),
        (WrongEmbedder(served={2: "other/model"}), "served 'other/model' in a run pinned to"),
    ],
)
def test_an_answer_the_rulebook_cannot_store_is_a_contract_error(
    embedder: ScriptedEmbedder, message: str
) -> None:
    rulebook = MemoryRulebook()
    document_id = stored(rulebook, 3)
    with pytest.raises(EmbeddingContractError, match=message):
        EmbeddingStage(embedder, rulebook).embed_missing(document_id)
    assert rulebook.embeddings == {}


def test_the_memory_index_refuses_what_the_rulebook_refuses() -> None:
    rulebook = MemoryRulebook()
    stored(rulebook, 1)
    (clause,) = rulebook.unembedded_clauses("m")
    with pytest.raises(RulebookRejectedError, match="512 components"):
        rulebook.put_embeddings("m", 256, [ClauseVector(clause.clause_id, (1.0,) * 256)])
    with pytest.raises(RulebookRejectedError, match="not stored"):
        rulebook.put_embeddings("m", 512, [ClauseVector(ClauseId(UUID(int=5)), hash_vector("x"))])
    assert rulebook.unembedded_clauses("m", after=clause.clause_id) == ()


# ---------------------------------------------------------------- the activity


async def test_the_activity_embeds_the_document_and_reports_the_model() -> None:
    rulebook, embedder = MemoryRulebook(), ScriptedEmbedder()
    document_id = stored(rulebook, 3)
    activity = EmbedClauses(EmbeddingStage(embedder, rulebook), enabled=True)
    report = await activity.run(EmbedRequest(document_id=document_id.value, regulator="CBIC"))
    assert (report.embedded, report.unchanged, report.model) == (3, 0, ScriptedEmbedder.MODEL)
    assert report.skipped is False
    assert embedder.requests[1][2] == {
        "document_id": str(document_id),
        "regulator": "CBIC",
        "stage": "embedding",
    }


async def test_disabled_the_activity_makes_no_call() -> None:
    rulebook, embedder = MemoryRulebook(), ScriptedEmbedder()
    activity = EmbedClauses(EmbeddingStage(embedder, rulebook), enabled=False)
    report = await activity.run(EmbedRequest(document_id=UUID(int=1)))
    assert report.skipped is True
    assert embedder.requests == []
    unwired = await EmbedClauses(None, enabled=False).run(EmbedRequest(document_id=UUID(int=1)))
    assert unwired.skipped is True
    with pytest.raises(ValueError, match="needs its stage"):
        EmbedClauses(None, enabled=True)


def test_the_activity_does_not_retry_what_a_retry_cannot_fix() -> None:
    policy = EmbedClauses.retry_policy
    assert set(policy.non_retryable_error_types or ()) == {
        "RulebookRejectedError",
        "EmbeddingContractError",
        "ModelResidencyRefusedError",
    }


# ---------------------------------------------------------------- pipeline-embed


class ClosingRulebook(MemoryRulebook):
    closed = False

    def close(self) -> None:
        self.closed = True


class ClosingEmbedder(ScriptedEmbedder):
    closed = False

    def close(self) -> None:
        self.closed = True


def test_the_backfill_embeds_every_document(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rulebook, embedder = ClosingRulebook(), ClosingEmbedder()
    stored(rulebook, 4)
    stored(rulebook, 2, hashlib.sha256(b"other").hexdigest())
    monkeypatch.setattr(
        embed,
        "PipelineSettings",
        lambda service_name: PipelineSettings(_env_file=None, service_name=service_name),
    )
    monkeypatch.setattr(embed, "HttpRulebook", lambda url, **_: rulebook)
    monkeypatch.setattr(embed, "GatewayEmbedder", lambda url, **_: embedder)
    assert embed.main(["--limit", "5"]) == 0
    assert capsys.readouterr().out == f"{ScriptedEmbedder.MODEL}: embedded 5, unchanged 0\n"
    assert embed.main(["--model", "voyage/voyage-3.5-lite"]) == 0
    assert capsys.readouterr().out == "voyage/voyage-3.5-lite: embedded 6, unchanged 0\n"
    assert embedder.requests[-1][2] == {"run": "pipeline-embed", "stage": "embedding"}
    assert (rulebook.closed, embedder.closed) == (True, True)
    with pytest.raises(SystemExit):
        embed.main(["--limit", "0"])
