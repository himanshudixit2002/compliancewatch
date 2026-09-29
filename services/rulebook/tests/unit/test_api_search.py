"""The search routes over HTTP: the write token on embeddings, route order, bodies and problem
types."""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from domain_kernel.documents import clause_id_for, document_id_for
from domain_kernel.vectors import EMBEDDING_DIMS
from rulebook.main import build_app
from rulebook.testing import WRITE_TOKEN, rulebook_settings

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOC = document_id_for(DIGEST)
BASE = "/v1/rulebook"
AUTH = {"x-cw-write-token": WRITE_TOKEN}
MODEL = "fake/hash-ngram-512"
P1 = "The due date for furnishing the return in FORM GSTR-3B is extended"
P2 = "The rate of tax on the supply of goods is revised"
P1_ID = clause_id_for(DOC, "en.p1").value


def unit(index: int) -> list[float]:
    return [1.0 if i == index else 0.0 for i in range(EMBEDDING_DIMS)]


def embeddings(*items: tuple[UUID, int], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": MODEL,
        "dims": EMBEDDING_DIMS,
        "items": [{"clause_id": str(clause), "vector": unit(index)} for clause, index in items],
    }
    body.update(overrides)
    return body


@pytest.fixture
def registered(client: TestClient) -> TestClient:
    body = {
        "source_id": str(UUID(int=7)),
        "sha256": DIGEST,
        "regulator": "CBIC",
        "doc_type": "notification",
        "external_ref": "01/2026-Central Tax",
        "title": "Due date extended",
        "url": "https://example.invalid/n.pdf",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "published_at": "2026-03-28",
        "fetched_at": "2026-09-28T06:00:00Z",
        "clauses": [{"clause_ref": "en.p1", "text": P1}, {"clause_ref": "en.p2", "text": P2}],
    }
    assert client.put(f"{BASE}/documents/{DOC}", json=body, headers=AUTH).status_code == 201
    return client


def test_embeddings_are_stored_then_left_alone(registered: TestClient) -> None:
    p1 = clause_id_for(DOC, "en.p1").value
    url = f"{BASE}/clauses/embeddings"
    first = registered.put(url, json=embeddings((p1, 0)), headers=AUTH)
    assert first.status_code == 200
    assert first.json() == {"stored": 1, "unchanged": 0}
    again = registered.put(url, json=embeddings((p1, 1)), headers=AUTH)
    assert again.json() == {"stored": 0, "unchanged": 1}


def test_unembedded_clauses_are_listed_before_the_clause_route(registered: TestClient) -> None:
    p1 = clause_id_for(DOC, "en.p1")
    registered.put(f"{BASE}/clauses/embeddings", json=embeddings((p1.value, 0)), headers=AUTH)
    response = registered.get(f"{BASE}/clauses/unembedded", params={"model": MODEL})
    assert response.status_code == 200
    assert [(c["clause_ref"], c["published_at"]) for c in response.json()] == [
        ("en.p2", "2026-03-28")
    ]
    assert registered.get(f"{BASE}/clauses/unembedded").status_code == 422
    assert registered.get(f"{BASE}/clauses/{p1}").json()["clause_ref"] == "en.p1"


@pytest.mark.parametrize(
    ("overrides", "slug"),
    [
        (
            {"dims": 1024, "items": [{"clause_id": str(P1_ID), "vector": unit(0)}]},
            "rulebook-embedding-dimension",
        ),
        ({"items": [{"clause_id": str(UUID(int=9)), "vector": unit(0)}]}, "clause-not-found"),
        ({"items": [{"clause_id": str(UUID(int=9)), "vector": [1.0]}]}, "request-invalid"),
        ({"items": []}, "request-invalid"),
        ({"model": ""}, "request-invalid"),
    ],
)
def test_bad_embeddings_are_422(
    registered: TestClient, overrides: dict[str, Any], slug: str
) -> None:
    response = registered.put(
        f"{BASE}/clauses/embeddings", json=embeddings(**overrides), headers=AUTH
    )
    assert response.status_code == 422
    assert response.json()["type"].endswith(slug)


def test_a_repeated_clause_is_422(registered: TestClient) -> None:
    p1 = clause_id_for(DOC, "en.p1").value
    response = registered.put(
        f"{BASE}/clauses/embeddings", json=embeddings((p1, 0), (p1, 1)), headers=AUTH
    )
    assert response.status_code == 422


def test_storing_embeddings_needs_the_token(registered: TestClient) -> None:
    body = embeddings((clause_id_for(DOC, "en.p1").value, 0))
    assert registered.put(f"{BASE}/clauses/embeddings", json=body).status_code == 401
    with TestClient(build_app(rulebook_settings(rulebook_write_token=None))) as closed:
        assert closed.put(f"{BASE}/clauses/embeddings", json=body).status_code == 503


def test_search_returns_fused_hits(registered: TestClient) -> None:
    p1, p2 = clause_id_for(DOC, "en.p1").value, clause_id_for(DOC, "en.p2").value
    registered.put(f"{BASE}/clauses/embeddings", json=embeddings((p1, 0), (p2, 1)), headers=AUTH)
    response = registered.post(
        f"{BASE}/search",
        json={"text": "due date extended", "vector": unit(1), "model": MODEL, "k": 5},
    )
    assert response.status_code == 200
    hits = response.json()
    assert [hit["clause_ref"] for hit in hits] == ["en.p1", "en.p2"]
    assert (hits[0]["lexical_rank"], hits[0]["vector_rank"]) == (1, 2)
    assert (hits[1]["lexical_rank"], hits[1]["vector_rank"]) == (None, 1)
    assert set(hits[0]) == {
        "clause_id",
        "document_id",
        "clause_ref",
        "text",
        "regulator",
        "doc_type",
        "external_ref",
        "title",
        "published_at",
        "score",
        "lexical_rank",
        "vector_rank",
        "cited_by",
        "out_of_force",
    }
    assert hits[0]["external_ref"] == "01/2026-Central Tax"
    assert hits[0]["title"] == "Due date extended"
    assert (hits[0]["cited_by"], hits[0]["out_of_force"]) == ([], False)
    lexical_only = registered.post(f"{BASE}/search", json={"text": "due date"})
    assert [hit["clause_ref"] for hit in lexical_only.json()] == ["en.p1"]
    before = registered.post(f"{BASE}/search", json={"text": "due date", "as_of": "2026-03-27"})
    assert before.json() == []


@pytest.mark.parametrize(
    "body",
    [
        {"text": "due date", "vector": unit(0)},
        {"text": "due date", "vector": [1.0], "model": MODEL},
        {"text": ""},
        {"text": "due date", "k": 51},
        {"text": "due date", "doc_types": ["gazette"]},
        {"text": "due date", "unexpected": True},
    ],
)
def test_bad_searches_are_422(registered: TestClient, body: dict[str, Any]) -> None:
    assert registered.post(f"{BASE}/search", json=body).status_code == 422
