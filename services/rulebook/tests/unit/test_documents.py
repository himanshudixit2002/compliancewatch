"""Registering and reading regulator documents on the memory store."""

import hashlib
import threading
from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, SourceId
from rulebook.application.documents import ReadDocument, RegisterDocument
from rulebook.domain.documents import (
    StoredDocument,
    as_parsed_document,
    metadata_differences,
    same_clauses,
    stored_clauses,
)
from rulebook.domain.errors import (
    DocumentConflictError,
    DocumentIdMismatchError,
    UnknownDocumentError,
)
from rulebook.infrastructure.memory import MemoryKnowledgeStore

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
FETCHED = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
CLAUSES = (
    Clause("en.p1", "Notification No. 01/2026 - Central Tax", page=1),
    Clause("en.p2", "In exercise of the powers conferred by section 39 ...", page=1),
)


def document(**overrides: object) -> StoredDocument:
    values: dict[str, object] = {
        "document_id": document_id_for(DIGEST),
        "source_id": SourceId(UUID(int=7)),
        "sha256": DIGEST,
        "regulator": "CBIC",
        "doc_type": DocumentType.NOTIFICATION,
        "url": "https://example.invalid/gst-ct-01-2026.pdf",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "fetched_at": FETCHED,
        "external_ref": "01/2026-Central Tax",
        "title": "Notification No. 01/2026 - Central Tax",
        "published_at": date(2026, 1, 16),
    }
    values.update(overrides)
    return StoredDocument(**values)  # type: ignore[arg-type]


@pytest.fixture
def store() -> MemoryKnowledgeStore:
    return MemoryKnowledgeStore()


def test_registering_stores_the_document_and_derives_clause_ids(
    store: MemoryKnowledgeStore,
) -> None:
    registration = RegisterDocument(store).run(document(), CLAUSES)
    doc_id = document_id_for(DIGEST)
    assert registration.created is True
    assert registration.document_id == doc_id
    assert registration.clause_ids == {
        "en.p1": clause_id_for(doc_id, "en.p1"),
        "en.p2": clause_id_for(doc_id, "en.p2"),
    }
    stored, clauses = ReadDocument(store).run(doc_id)
    assert stored == document()
    assert [(c.clause_ref, c.ordinal, c.page) for c in clauses] == [
        ("en.p1", 1, 1),
        ("en.p2", 2, 1),
    ]
    assert clauses[1].text == CLAUSES[1].text


def test_registering_the_same_parse_again_changes_nothing(store: MemoryKnowledgeStore) -> None:
    first = RegisterDocument(store).run(document(), CLAUSES)
    again = RegisterDocument(store).run(
        document(fetched_at=datetime(2026, 9, 29, tzinfo=UTC), raw_uri="s3://raw/x"), CLAUSES
    )
    assert again.created is False
    assert again.clause_ids == first.clause_ids
    assert again.metadata_differs == ()


def test_metadata_differences_are_reported_and_the_stored_row_wins(
    store: MemoryKnowledgeStore,
) -> None:
    RegisterDocument(store).run(document(), CLAUSES)
    again = RegisterDocument(store).run(document(title="Other title", regulator="GSTN"), CLAUSES)
    assert again.metadata_differs == ("regulator", "title")
    stored, _ = ReadDocument(store).run(document_id_for(DIGEST))
    assert stored.title == "Notification No. 01/2026 - Central Tax"


@pytest.mark.parametrize(
    "clauses",
    [
        (CLAUSES[0],),
        (CLAUSES[0], Clause("en.p2", "different text")),
        (CLAUSES[1], CLAUSES[0]),
        (CLAUSES[0], Clause("en.p2", CLAUSES[1].text, page=2)),
    ],
)
def test_a_different_parse_by_the_same_parser_is_refused(
    store: MemoryKnowledgeStore, clauses: Sequence[Clause]
) -> None:
    RegisterDocument(store).run(document(), CLAUSES)
    with pytest.raises(DocumentConflictError, match="by the same parser pdf@1"):
        RegisterDocument(store).run(document(), clauses)
    _, stored = ReadDocument(store).run(document_id_for(DIGEST))
    assert [c.text for c in stored] == [c.text for c in CLAUSES]


@pytest.mark.parametrize(
    "clauses",
    [
        (CLAUSES[0],),
        (CLAUSES[0], Clause("en.p2", "different text"), Clause("en.p3", "a table row | 5%")),
        CLAUSES,
    ],
)
def test_a_parse_by_another_parser_is_answered_with_the_first_one(
    store: MemoryKnowledgeStore, clauses: Sequence[Clause]
) -> None:
    first = RegisterDocument(store).run(document(), CLAUSES)
    again = RegisterDocument(store).run(document(parser_version="pdf-tables@1"), clauses)
    assert (again.created, again.parser_version) == (False, "pdf@1")
    assert again.clause_ids == first.clause_ids
    assert again.metadata_differs == ("parser_version",)
    stored, kept = ReadDocument(store).run(document_id_for(DIGEST))
    assert stored.parser_version == "pdf@1"
    assert [c.text for c in kept] == [c.text for c in CLAUSES]
    assert first.parser_version == "pdf@1"


def test_reading_an_unknown_document_is_a_lookup_error(store: MemoryKnowledgeStore) -> None:
    with pytest.raises(UnknownDocumentError, match="is not stored"):
        ReadDocument(store).run(DocumentId(UUID(int=1)))


def test_a_failed_unit_of_work_leaves_nothing_behind(store: MemoryKnowledgeStore) -> None:
    doc = document()

    def fail_midway() -> None:
        with store() as uow:
            uow.documents.add(doc)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        fail_midway()
    with store() as uow:
        assert uow.documents.get(doc.document_id) is None


def test_document_id_must_come_from_the_digest() -> None:
    with pytest.raises(DocumentIdMismatchError, match="not the first half"):
        document(document_id=DocumentId(UUID(int=1)))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("regulator", " ", "regulator must not be blank"),
        ("url", "", "url must not be blank"),
        ("language", "", "language must not be blank"),
        ("media_type", " ", "media_type must not be blank"),
        ("parser_version", "", "parser_version must name the parser"),
        ("fetched_at", datetime(2026, 9, 28), "fetched_at must be timezone-aware"),
    ],
)
def test_stored_documents_need_their_provenance(field: str, value: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        document(**{field: value})


def test_stored_clauses_number_in_order_and_hash_the_text() -> None:
    doc_id = document_id_for(DIGEST)
    stored = stored_clauses(doc_id, CLAUSES)
    assert [c.ordinal for c in stored] == [1, 2]
    assert stored[0].text_sha256 == hashlib.sha256(CLAUSES[0].text.encode()).hexdigest()
    assert stored[0].as_clause() == CLAUSES[0]
    assert same_clauses(stored, stored_clauses(doc_id, CLAUSES))


def test_stored_clauses_need_at_least_one_unique_ref() -> None:
    doc_id = document_id_for(DIGEST)
    with pytest.raises(InvariantViolationError, match="at least one clause"):
        stored_clauses(doc_id, ())
    with pytest.raises(InvariantViolationError, match=r"duplicate clause_ref 'en\.p1'"):
        stored_clauses(doc_id, (CLAUSES[0], CLAUSES[0]))


def test_metadata_differences_ignore_fetch_time_and_raw_location() -> None:
    later = document(fetched_at=datetime(2027, 1, 1, tzinfo=UTC), raw_uri="s3://raw/y")
    assert metadata_differences(document(), later) == ()
    assert metadata_differences(document(), document(language="hi")) == ("language",)


def test_a_stored_document_reads_back_as_the_kernel_parsed_document() -> None:
    doc = document()
    parsed = as_parsed_document(doc, stored_clauses(doc.document_id, CLAUSES))
    assert parsed.document_id == doc.document_id
    assert parsed.clauses == CLAUSES
    assert parsed.parser_version == "pdf@1"
    assert parsed.published_at == date(2026, 1, 16)


def test_overlapping_units_of_work_do_not_lose_writes(store: MemoryKnowledgeStore) -> None:
    first, second = document(), document(sha256="0" * 64, document_id=document_id_for("0" * 64))
    done = threading.Event()

    def register_second() -> None:
        RegisterDocument(store).run(second, CLAUSES)
        done.set()

    with store() as uow:
        uow.documents.add(first)
        thread = threading.Thread(target=register_second)
        thread.start()
        assert not done.wait(0.05), "a second unit of work ran inside the first"
    thread.join(timeout=5)
    with store() as uow:
        assert uow.documents.get(first.document_id) is not None
        assert uow.documents.get(second.document_id) is not None
