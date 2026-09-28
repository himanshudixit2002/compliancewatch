"""Registering parsed documents with the rulebook: the flag, idempotence and the id check."""

import dataclasses
import hashlib
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from domain_kernel.documents import clause_id_for, document_id_for
from pipeline.application.activities import Fetched, ParseRequest
from pipeline.application.knowledge_activities import RegisterDocument, RegisterRequest
from pipeline.domain.errors import KnowledgeContractError, RulebookConflictError
from pipeline.domain.knowledge import DocumentRecord, RegisteredDocument
from pipeline.infrastructure.fakes import SAMPLE_TEXT, FakePlainTextParser
from pipeline.testing import MemoryRulebook

CONTENT = SAMPLE_TEXT.encode()


def request(content: bytes = CONTENT, **overrides: object) -> RegisterRequest:
    fetched = Fetched(
        source_id=UUID(int=1),
        url="https://example.invalid/notifications/17-2026",
        external_ref="17/2026-Central Tax",
        media_type="text/plain",
        sha256=hashlib.sha256(content).hexdigest(),
        fetched_at=datetime(2026, 9, 28, tzinfo=UTC),
        content=content,
    )
    values: dict[str, object] = {
        "document_id": document_id_for(fetched.sha256).value,
        "fetched": fetched,
        "title": "Notification No. 17/2026 - Central Tax",
        "published_at": date(2026, 9, 1),
    }
    values.update(overrides)
    return RegisterRequest(parse=ParseRequest.model_validate(values), regulator="CBIC")


async def test_disabled_it_skips_without_calling_the_rulebook() -> None:
    rulebook = MemoryRulebook()
    outcome = await RegisterDocument(FakePlainTextParser(), rulebook, enabled=False).run(request())
    assert outcome.skipped is True
    assert outcome.created is False
    assert rulebook.calls == 0


async def test_enabled_it_registers_once_and_then_finds_it_stored() -> None:
    rulebook = MemoryRulebook()
    activity = RegisterDocument(FakePlainTextParser(), rulebook, enabled=True)
    first = await activity.run(request())
    again = await activity.run(request())
    assert (first.created, first.skipped, first.clause_count) == (True, False, 3)
    assert (again.created, again.skipped) == (False, False)
    record = rulebook.records[document_id_for(request().parse.fetched.sha256)]
    assert record.regulator == "CBIC"
    assert record.document.parser_version == "fake@1"
    assert record.document.title == "Notification No. 17/2026 - Central Tax"
    assert record.document.published_at == date(2026, 9, 1)
    assert record.external_ref == "17/2026-Central Tax"


async def test_the_parsed_title_is_kept_when_the_listing_has_none() -> None:
    rulebook = MemoryRulebook()
    await RegisterDocument(FakePlainTextParser(), rulebook, enabled=True).run(
        request(title="", published_at=None)
    )
    (record,) = rulebook.records.values()
    assert record.document.title == "Notification No. 17/2026 - Central Tax"
    assert record.document.published_at is None


class WrongIds:
    def register_document(self, record: DocumentRecord) -> RegisteredDocument:
        doc_id = record.document.document_id
        return RegisteredDocument(doc_id, True, {"p1": clause_id_for(doc_id, "p2")})


async def test_ids_that_differ_from_the_kernel_are_a_contract_error() -> None:
    with pytest.raises(KnowledgeContractError, match="differ from the kernel"):
        await RegisterDocument(FakePlainTextParser(), WrongIds(), enabled=True).run(request())


async def test_a_conflict_is_passed_on() -> None:
    rulebook = MemoryRulebook()
    activity = RegisterDocument(FakePlainTextParser(), rulebook, enabled=True)
    await activity.run(request())
    stored = next(iter(rulebook.records.values()))
    shorter = dataclasses.replace(stored.document, clauses=stored.document.clauses[:1])
    rulebook.records[stored.document.document_id] = dataclasses.replace(stored, document=shorter)
    with pytest.raises(RulebookConflictError):
        await activity.run(request())


def test_the_activity_declares_what_a_retry_cannot_fix() -> None:
    policy = RegisterDocument.retry_policy
    assert set(policy.non_retryable_error_types or ()) == {
        "RulebookConflictError",
        "RulebookRejectedError",
        "KnowledgeContractError",
        "UnsupportedDocumentError",
    }
