from uuid import UUID

import pytest

from domain_kernel.documents import (
    PARSER_VERSION_PATTERN,
    Clause,
    DocumentType,
    ParsedDocument,
    clause_id_for,
    document_id_for,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
"""SHA-256 of the recorded 01/2026-Central Tax PDF (services/pipeline/tests/fixtures/cbic)."""


def test_document_id_is_the_first_half_of_the_digest() -> None:
    assert document_id_for(DIGEST) == DocumentId(UUID("51f5dbee-1615-f0ec-4725-6abddb11061a"))


@pytest.mark.parametrize(
    "digest",
    ["", DIGEST[:63], DIGEST + "0", DIGEST.upper(), "g" * 64, f" {DIGEST[1:]}"],
)
def test_document_id_rejects_anything_but_lowercase_hex_sha256(digest: str) -> None:
    with pytest.raises(InvariantViolationError, match="64 lowercase hex digits"):
        document_id_for(digest)


def test_document_id_rejects_non_text() -> None:
    with pytest.raises(InvariantViolationError, match="sha256 must be str"):
        document_id_for(b"x" * 64)  # type: ignore[arg-type]


def test_clause_id_known_answer() -> None:
    """Pinned: the rulebook, the pipeline and the vector index must all derive this id."""
    clause_id = clause_id_for(document_id_for(DIGEST), "en.p3")
    assert clause_id == ClauseId(UUID("b6ac336c-6439-560b-9882-fd49d19e8d81"))


def test_clause_ids_differ_by_document_and_ref() -> None:
    first, second = document_id_for(DIGEST), document_id_for("0" * 64)
    ids = {
        clause_id_for(first, "en.p1"),
        clause_id_for(first, "en.p2"),
        clause_id_for(second, "en.p1"),
        clause_id_for(first, "hi.p1"),
    }
    assert len(ids) == 4


@pytest.mark.parametrize(
    ("ref", "message"),
    [("", "must not be blank"), (" en.p1", "leading or trailing"), (1, "must be str")],
)
def test_clause_id_rejects_bad_refs(ref: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        clause_id_for(document_id_for(DIGEST), ref)  # type: ignore[arg-type]


def test_clause_id_rejects_other_id_kinds() -> None:
    with pytest.raises(InvariantViolationError, match="document_id must be DocumentId"):
        clause_id_for(ClauseId(UUID(int=1)), "en.p1")  # type: ignore[arg-type]


def _parsed(parser_version: object) -> ParsedDocument:
    return ParsedDocument(
        document_id=document_id_for(DIGEST),
        doc_type=DocumentType.NOTIFICATION,
        title="t",
        clauses=(Clause("en.p1", "text"),),
        parser_version=parser_version,  # type: ignore[arg-type]
    )


def test_parser_version_defaults_to_unknown() -> None:
    doc = ParsedDocument(
        document_id_for(DIGEST), DocumentType.NOTIFICATION, "t", (Clause("p1", "x"),)
    )
    assert doc.parser_version == ""


@pytest.mark.parametrize("version", ["pdf@1", "html@12", "fake@1", "gazette_ocr-v2@3"])
def test_parser_version_accepts_name_at_number(version: str) -> None:
    assert _parsed(version).parser_version == version
    assert PARSER_VERSION_PATTERN.startswith("^")


@pytest.mark.parametrize("version", ["pdf", "PDF@1", "pdf@", "@1", "pdf@1.2", " pdf@1", "1pdf@1"])
def test_parser_version_rejects_other_shapes(version: str) -> None:
    with pytest.raises(InvariantViolationError, match="parser_version must look like"):
        _parsed(version)


def test_parser_version_must_be_text() -> None:
    with pytest.raises(InvariantViolationError, match="parser_version must be str"):
        _parsed(1)
