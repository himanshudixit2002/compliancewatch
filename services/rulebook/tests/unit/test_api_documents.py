"""The documents API: write-token handling, idempotent registration, conflicts and reads."""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from domain_kernel.documents import clause_id_for, document_id_for
from rulebook.main import build_app
from rulebook.testing import WRITE_TOKEN, rulebook_settings

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOCUMENT_ID = document_id_for(DIGEST)
URL = f"/v1/rulebook/documents/{DOCUMENT_ID}"
AUTH = {"x-cw-write-token": WRITE_TOKEN}


def body(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "source_id": str(UUID(int=7)),
        "sha256": DIGEST,
        "regulator": "CBIC",
        "doc_type": "notification",
        "external_ref": "01/2026-Central Tax",
        "url": "https://example.invalid/gst-ct-01-2026.pdf",
        "title": "Notification No. 01/2026 - Central Tax",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "published_at": "2026-01-16",
        "fetched_at": "2026-09-28T06:00:00Z",
        "clauses": [
            {"clause_ref": "en.p1", "text": "Notification No. 01/2026 - Central Tax", "page": 1},
            {"clause_ref": "en.p2", "text": "In exercise of the powers ...", "page": 1},
        ],
    }
    values.update(overrides)
    return values


def test_register_then_register_again(client: TestClient) -> None:
    created = client.put(URL, json=body(), headers=AUTH)
    assert created.status_code == 201
    assert created.json() == {
        "document_id": str(DOCUMENT_ID),
        "created": True,
        "clause_ids": {
            "en.p1": str(clause_id_for(DOCUMENT_ID, "en.p1")),
            "en.p2": str(clause_id_for(DOCUMENT_ID, "en.p2")),
        },
        "metadata_differs": [],
        "parser_version": "pdf@1",
    }
    again = client.put(URL, json=body(title="Renamed"), headers=AUTH)
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["metadata_differs"] == ["title"]


def test_read_returns_the_clauses_in_order(client: TestClient) -> None:
    client.put(URL, json=body(), headers=AUTH)
    response = client.get(URL)
    assert response.status_code == 200
    document = response.json()
    assert document["parser_version"] == "pdf@1"
    assert document["published_at"] == "2026-01-16"
    assert [(c["clause_ref"], c["ordinal"]) for c in document["clauses"]] == [
        ("en.p1", 1),
        ("en.p2", 2),
    ]
    assert document["clauses"][0]["clause_id"] == str(clause_id_for(DOCUMENT_ID, "en.p1"))


def test_reading_an_unknown_document_is_404(client: TestClient) -> None:
    response = client.get(f"/v1/rulebook/documents/{UUID(int=1)}")
    assert response.status_code == 404
    assert response.json()["type"].endswith("rulebook-document-not-found")


def test_a_different_parse_by_the_same_parser_is_409(client: TestClient) -> None:
    client.put(URL, json=body(), headers=AUTH)
    changed = body(clauses=[{"clause_ref": "en.p1", "text": "other text"}])
    response = client.put(URL, json=changed, headers=AUTH)
    assert response.status_code == 409
    assert response.json()["type"].endswith("rulebook-document-conflict")


def test_a_parse_by_a_newer_parser_is_answered_with_the_stored_one(client: TestClient) -> None:
    first = client.put(URL, json=body(), headers=AUTH).json()
    newer = body(
        parser_version="pdf-tables@1",
        clauses=[{"clause_ref": "en.p1", "text": "S. No. | Example item | 5%"}],
    )
    response = client.put(URL, json=newer, headers=AUTH)
    assert response.status_code == 200
    answer = response.json()
    assert (answer["created"], answer["parser_version"]) == (False, "pdf@1")
    assert answer["clause_ids"] == first["clause_ids"]
    assert answer["metadata_differs"] == ["parser_version"]
    assert client.get(URL).json()["parser_version"] == "pdf@1"


def test_a_path_id_that_is_not_the_digest_is_422(client: TestClient) -> None:
    response = client.put(f"/v1/rulebook/documents/{UUID(int=1)}", json=body(), headers=AUTH)
    assert response.status_code == 422
    assert response.json()["type"].endswith("rulebook-document-id-mismatch")


@pytest.mark.parametrize(
    "overrides",
    [
        {"clauses": []},
        {"clauses": [{"clause_ref": "section 1", "text": "x"}]},
        {"clauses": [{"clause_ref": "en.p1", "text": ""}]},
        {"parser_version": "pdf"},
        {"parser_version": "p" * 39 + "@1"},
        {"sha256": DIGEST.upper()},
        {"fetched_at": "2026-09-28T06:00:00"},
        {"doc_type": "gazette"},
        {"unexpected": "field"},
    ],
)
def test_malformed_bodies_are_422(client: TestClient, overrides: dict[str, Any]) -> None:
    response = client.put(URL, json=body(**overrides), headers=AUTH)
    assert response.status_code == 422


def test_duplicate_clause_refs_are_422(client: TestClient) -> None:
    twice = [{"clause_ref": "en.p1", "text": "a"}, {"clause_ref": "en.p1", "text": "b"}]
    response = client.put(URL, json=body(clauses=twice), headers=AUTH)
    assert response.status_code == 422


@pytest.mark.parametrize("headers", [{}, {"x-cw-write-token": "wrong"}])
def test_writes_need_the_token(client: TestClient, headers: dict[str, str]) -> None:
    response = client.put(URL, json=body(), headers=headers)
    assert response.status_code == 401
    assert response.json()["type"].endswith("rulebook-write-token-invalid")
    assert client.get(URL).status_code == 404


@pytest.mark.parametrize("token", [None, ""])
def test_without_a_configured_token_writes_fail_closed(token: str | None) -> None:
    with TestClient(build_app(rulebook_settings(rulebook_write_token=token))) as client:
        response = client.put(URL, json=body(), headers=AUTH)
    assert response.status_code == 503
    assert response.json()["type"].endswith("rulebook-writes-disabled")


def test_reads_need_no_token(client: TestClient) -> None:
    client.put(URL, json=body(), headers=AUTH)
    assert client.get(URL, headers={}).status_code == 200
