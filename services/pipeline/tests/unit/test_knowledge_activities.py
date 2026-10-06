"""Registering parsed documents with the rulebook: the flag, idempotence and the id check."""

import dataclasses
import hashlib
import json
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from domain_kernel.documents import DocumentRef, RawDocument, clause_id_for, document_id_for
from domain_kernel.ids import DocumentId, SourceId
from domain_kernel.knowledge import EntityType
from pipeline.application.activities import Fetched, ParseRequest, Stored
from pipeline.application.knowledge_activities import (
    ExtractMentions,
    MentionsRequest,
    ProposeRelations,
    RegisterDocument,
    RegisterRequest,
    RelationsRequest,
    SubmitRelations,
)
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.domain.errors import (
    KnowledgeContractError,
    RawObjectMissingError,
    RawStoreError,
    RulebookConflictError,
)
from pipeline.domain.issues import Issue
from pipeline.domain.knowledge import DocumentRecord, RegisteredDocument, RuleKey
from pipeline.domain.prompt import PromptText
from pipeline.infrastructure.fakes import SAMPLE_TEXT, FakePlainTextParser
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.testing import MemoryRulebook, ScriptedProvider
from pipeline.workflows import IngestRequest

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
    record = rulebook.records[document_id_for(request().parse.sha256)]
    assert record.regulator == "CBIC"
    assert record.document.parser_version == "fake@1"
    assert record.document.title == "Notification No. 17/2026 - Central Tax"
    assert record.document.published_at == date(2026, 9, 1)
    assert record.external_ref == "17/2026-Central Tax"


def stored_request(raw_store: MemoryRawStore, content: bytes = CONTENT) -> RegisterRequest:
    """The request of a workflow started since the store: the bytes are in the raw store."""
    ref = DocumentRef(SourceId(UUID(int=1)), "https://example.invalid/notifications/17-2026")
    raw = RawDocument.from_bytes(ref, content, "text/plain", datetime(2026, 9, 28, tzinfo=UTC))
    key = raw_store.put(raw)
    stored = Stored(
        document_id=document_id_for(raw.sha256).value,
        source_id=UUID(int=1),
        source_key="sample",
        regulator="CBIC",
        url=ref.url,
        external_ref="17/2026-Central Tax",
        media_type=raw.media_type,
        sha256=raw.sha256,
        size=len(content),
        fetched_at=raw.fetched_at,
        storage_key=key,
        raw_uri=raw_store.uri(key),
    )
    parse = ParseRequest(document_id=stored.document_id, stored=stored, title="Notification")
    return RegisterRequest(parse=parse, regulator="CBIC")


async def test_a_stored_document_is_read_back_from_the_raw_store() -> None:
    rulebook, raw_store = MemoryRulebook(), MemoryRawStore()
    activity = RegisterDocument(FakePlainTextParser(), rulebook, enabled=True, raw_store=raw_store)
    outcome = await activity.run(stored_request(raw_store))
    assert (outcome.created, outcome.clause_count) == (True, 3)
    (record,) = rulebook.records.values()
    assert record.raw_uri == raw_store.uri(stored_request(raw_store).parse.stored.storage_key)  # type: ignore[union-attr]
    assert record.external_ref == "17/2026-Central Tax"
    raw_store.files.clear()
    with pytest.raises(RawObjectMissingError):
        await activity.run(stored_request(MemoryRawStore()))
    without = RegisterDocument(FakePlainTextParser(), rulebook, enabled=True)
    with pytest.raises(RawStoreError, match="no raw store"):
        await without.run(stored_request(MemoryRawStore()))


def test_a_parse_request_names_its_bytes_once() -> None:
    fetched = request().parse.fetched
    with pytest.raises(ValidationError, match="exactly one of fetched and stored"):
        ParseRequest(document_id=UUID(int=2))
    stored = stored_request(MemoryRawStore()).parse.stored
    with pytest.raises(ValidationError, match="exactly one of fetched and stored"):
        ParseRequest(document_id=UUID(int=2), fetched=fetched, stored=stored)


async def test_the_parsed_title_is_kept_when_the_listing_has_none() -> None:
    rulebook = MemoryRulebook()
    await RegisterDocument(FakePlainTextParser(), rulebook, enabled=True).run(
        request(title="", published_at=None)
    )
    (record,) = rulebook.records.values()
    assert record.document.title == "Notification No. 17/2026 - Central Tax"
    assert record.document.published_at is None


class WrongIds(MemoryRulebook):
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
        "RawObjectMissingError",
        "RawObjectCorruptError",
    }


def test_knowledge_needs_a_regulator_up_front() -> None:
    since = datetime(2026, 9, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="regulator is required"):
        IngestRequest(source_id=UUID(int=1), since=since, knowledge=True)
    with pytest.raises(ValidationError, match="regulator is required"):
        IngestRequest(source_id=UUID(int=1), since=since, knowledge=True, regulator=" ")
    assert IngestRequest(source_id=UUID(int=1), since=since).regulator == ""
    assert IngestRequest(source_id=UUID(int=1), since=since, knowledge=True, regulator="CBIC")


# ---------------------------------------------------------------- mentions and relations


RELATION_ANSWER = json.dumps(
    {
        "relations": [
            {
                "relation": "extends_deadline",
                "target_mention": "M2",
                "rule_key": None,
                "evidence_clause_ref": "p2",
                "evidence_quote": "extends the due date for furnishing FORM GSTR-3B",
                "period": None,
                "new_due_date": None,
                "confidence": 0.9,
            }
        ]
    }
)


async def registered(rulebook: MemoryRulebook) -> DocumentId:
    await RegisterDocument(FakePlainTextParser(), rulebook, enabled=True).run(request())
    return document_id_for(request().parse.sha256)


def relation_stage(answer: str = RELATION_ANSWER) -> tuple[RelationStage, ScriptedProvider]:
    provider = ScriptedProvider({}, default=answer)
    prompt = PromptText("extraction.rule_relations", "1", "regulatory-intelligence", "Relate.")
    return RelationStage(LlmRelationExtractor(provider, prompt)), provider


async def test_mentions_are_found_and_handed_to_alignment() -> None:
    rulebook = MemoryRulebook(entities={(EntityType.FORM, "GSTR-3B")})
    doc_id = await registered(rulebook)
    activity = ExtractMentions(rulebook, rulebook, enabled=True)
    report = await activity.run(MentionsRequest(document_id=doc_id.value, own_ref="17/2026-CT"))
    (submission,) = rulebook.mentions
    assert submission.extractor == "grammar@1"
    names = [(m.entity_type, m.proposed_name, m.self_ref) for m in submission.mentions]
    assert (EntityType.FORM, "GSTR-3B", False) in names
    assert (EntityType.NOTIFICATION, "17/2026-central tax", True) in names
    assert (EntityType.SECTION, "39@cgst-act", False) in names
    assert (report.found, report.aligned) == (len(names), 1)
    assert report.queued == len(names) - 1
    disabled = await ExtractMentions(rulebook, rulebook, enabled=False).run(
        MentionsRequest(document_id=doc_id.value)
    )
    assert disabled.skipped is True


async def test_relations_are_proposed_then_submitted() -> None:
    rulebook = MemoryRulebook(rules=(RuleKey("gstr3b_monthly", "GSTR-3B"),))
    doc_id = await registered(rulebook)
    stage, provider = relation_stage()
    batch = await ProposeRelations(rulebook, stage, enabled=True).run(
        RelationsRequest(document_id=doc_id.value, own_ref="17/2026-Central Tax", regulator="CBIC")
    )
    assert batch.extractor == "extraction.rule_relations@1"
    assert batch.model == "scripted/golden"
    (candidate,) = batch.candidates
    assert (candidate.relation, candidate.target.proposed_name) == ("extends_deadline", "GSTR-3B")
    assert "gstr3b_monthly: GSTR-3B" in provider.requests[0].user
    assert rulebook.relations == []

    report = await SubmitRelations(rulebook, enabled=True).run(batch)
    assert (report.outcome, report.created, report.unchanged) == (batch.outcome, 1, 0)
    (submission,) = rulebook.relations
    assert submission.candidates[0].target.entity_type is EntityType.FORM
    assert submission.candidates[0].issues == tuple(
        Issue(i.code, i.detail, i.clause_ref) for i in candidate.issues
    )
    again = await SubmitRelations(rulebook, enabled=True).run(batch)
    assert (again.created, again.unchanged) == (0, 1)


async def test_disabled_relation_activities_do_nothing() -> None:
    rulebook = MemoryRulebook()
    stage, provider = relation_stage()
    batch = await ProposeRelations(rulebook, stage, enabled=False).run(
        RelationsRequest(document_id=UUID(int=1))
    )
    assert batch.skipped is True
    assert provider.requests == []
    report = await SubmitRelations(rulebook, enabled=True).run(batch)
    assert report.skipped is True
    assert rulebook.relations == []
