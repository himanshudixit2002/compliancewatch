"""The rulebook client: the request it sends and how it reads each kind of answer."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import UUID

import httpx2
import pytest

from domain_kernel.documents import (
    Clause,
    DocumentType,
    ParsedDocument,
    clause_id_for,
    document_id_for,
)
from domain_kernel.ids import SourceId
from pipeline.domain.embedding import ClauseVector
from pipeline.domain.errors import (
    RulebookConflictError,
    RulebookRejectedError,
    RulebookUnavailableError,
)
from pipeline.domain.knowledge import DocumentRecord
from pipeline.infrastructure.rulebook_client import HttpRulebook

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOCUMENT_ID = document_id_for(DIGEST)
RECORD = DocumentRecord(
    document=ParsedDocument(
        document_id=DOCUMENT_ID,
        doc_type=DocumentType.NOTIFICATION,
        title="Notification No. 01/2026",
        clauses=(Clause("en.p1", "first", page=1), Clause("en.p2", "second")),
        published_at=date(2026, 1, 16),
        parser_version="pdf@1",
    ),
    source_id=SourceId(UUID(int=7)),
    sha256=DIGEST,
    regulator="CBIC",
    url="https://example.invalid/n.pdf",
    media_type="application/pdf",
    fetched_at=datetime(2026, 9, 28, 6, tzinfo=UTC),
    external_ref="01/2026-Central Tax",
)
REGISTERED = {
    "document_id": str(DOCUMENT_ID),
    "created": True,
    "clause_ids": {
        "en.p1": str(clause_id_for(DOCUMENT_ID, "en.p1")),
        "en.p2": str(clause_id_for(DOCUMENT_ID, "en.p2")),
    },
    "metadata_differs": [],
}


def client(
    handler: Callable[[httpx2.Request], httpx2.Response], token: str | None = "t"
) -> HttpRulebook:
    transport = httpx2.MockTransport(handler)
    return HttpRulebook(
        token=token, client=httpx2.Client(base_url="http://rulebook.test", transport=transport)
    )


def test_it_puts_the_document_with_the_token_and_reads_the_ids() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(201, json=REGISTERED)

    rulebook = client(handler, token="secret")
    registered = rulebook.register_document(RECORD)
    rulebook.close()
    assert registered.created is True
    assert registered.document_id == DOCUMENT_ID
    assert registered.clause_ids["en.p2"] == clause_id_for(DOCUMENT_ID, "en.p2")
    request = seen[0]
    assert request.method == "PUT"
    assert request.url.path == f"/v1/rulebook/documents/{DOCUMENT_ID}"
    assert request.headers["x-cw-write-token"] == "secret"
    body = json.loads(request.content)
    assert body["parser_version"] == "pdf@1"
    assert body["published_at"] == "2026-01-16"
    assert body["fetched_at"] == "2026-09-28T06:00:00+00:00"
    assert body["clauses"] == [
        {"clause_ref": "en.p1", "text": "first", "page": 1},
        {"clause_ref": "en.p2", "text": "second", "page": None},
    ]


def test_without_a_token_no_header_is_sent() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={**REGISTERED, "created": False})

    assert client(handler, token=None).register_document(RECORD).created is False
    assert "x-cw-write-token" not in seen[0].headers


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (409, "rulebook-document-conflict", RulebookConflictError),
        (422, "rulebook-document-id-mismatch", RulebookRejectedError),
        (401, "rulebook-write-token-invalid", RulebookRejectedError),
        (503, "urn:compliancewatch:problem:rulebook-writes-disabled", RulebookRejectedError),
        (503, "upstream unavailable", RulebookUnavailableError),
        (500, "boom", RulebookUnavailableError),
    ],
)
def test_error_answers_map_to_pipeline_errors(
    status: int, body: str, error: type[Exception]
) -> None:
    rulebook = client(lambda _: httpx2.Response(status, text=body))
    with pytest.raises(error, match=str(status)):
        rulebook.register_document(RECORD)


def test_an_unreachable_rulebook_is_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(RulebookUnavailableError, match="unreachable"):
        client(handler).register_document(RECORD)


# ---------------------------------------------------------------- the clause search index

UNEMBEDDED = {
    "clause_id": str(clause_id_for(DOCUMENT_ID, "en.p2")),
    "document_id": str(DOCUMENT_ID),
    "clause_ref": "en.p2",
    "ordinal": 2,
    "page": None,
    "text": "second",
    "regulator": "CBIC",
    "doc_type": "notification",
    "external_ref": "01/2026-Central Tax",
    "title": "Notification No. 01/2026",
    "url": "https://example.invalid/n.pdf",
    "language": "en",
    "published_at": "2026-01-16",
}


def test_it_reads_unembedded_clauses_with_the_query_and_no_token() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=[UNEMBEDDED, {**UNEMBEDDED, "published_at": None}])

    after = clause_id_for(DOCUMENT_ID, "en.p1")
    first, undated = client(handler).unembedded_clauses(
        "voyage/voyage-3.5-lite", document_id=DOCUMENT_ID, limit=64, after=after
    )
    assert first.clause_id == clause_id_for(DOCUMENT_ID, "en.p2")
    assert first.document_id == DOCUMENT_ID
    assert (first.clause_ref, first.text, first.regulator) == ("en.p2", "second", "CBIC")
    assert first.doc_type is DocumentType.NOTIFICATION
    assert (first.external_ref, first.published_at) == ("01/2026-Central Tax", date(2026, 1, 16))
    assert undated.published_at is None
    request = seen[0]
    assert (request.method, request.url.path) == ("GET", "/v1/rulebook/clauses/unembedded")
    assert dict(request.url.params) == {
        "model": "voyage/voyage-3.5-lite",
        "limit": "64",
        "document_id": str(DOCUMENT_ID),
        "after": str(after),
    }
    assert "x-cw-write-token" not in request.headers
    client(handler).unembedded_clauses("m")
    assert dict(seen[1].url.params) == {"model": "m", "limit": "64"}


def test_it_puts_embeddings_with_the_token() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"stored": 1, "unchanged": 1})

    clause_id = clause_id_for(DOCUMENT_ID, "en.p1")
    report = client(handler, token="secret").put_embeddings(
        "fake/hash-ngram-512",
        512,
        [ClauseVector(clause_id, (0.5, -0.5)), ClauseVector(clause_id, (1.0, 0.0))],
    )
    assert (report.stored, report.unchanged) == (1, 1)
    request = seen[0]
    assert (request.method, request.url.path) == ("PUT", "/v1/rulebook/clauses/embeddings")
    assert request.headers["x-cw-write-token"] == "secret"
    assert json.loads(request.content) == {
        "model": "fake/hash-ngram-512",
        "dims": 512,
        "items": [
            {"clause_id": str(clause_id), "vector": [0.5, -0.5]},
            {"clause_id": str(clause_id), "vector": [1.0, 0.0]},
        ],
    }


def test_an_unknown_clause_is_a_rejection() -> None:
    rulebook = client(lambda _: httpx2.Response(422, text="rulebook-clause-unknown"))
    with pytest.raises(RulebookRejectedError, match="422"):
        rulebook.put_embeddings("m", 512, [ClauseVector(clause_id_for(DOCUMENT_ID, "x"), (0.0,))])
