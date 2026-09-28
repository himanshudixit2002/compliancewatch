"""Activities that hand the pipeline's output to the rulebook, which owns regulator records.

``RegisterDocument`` stores a parsed document and its clauses. It parses the fetched bytes again
rather than carrying clause text through the workflow history, and checks that the rulebook
derived the same clause ids the kernel gives here. Behind ``CW_PIPELINE_KNOWLEDGE_ENABLED``:
disabled, it answers ``skipped`` without a call.
"""

import dataclasses
from datetime import timedelta
from typing import ClassVar
from uuid import UUID

from pydantic import Field
from temporalio.common import RetryPolicy

from domain_kernel.documents import clause_id_for
from domain_kernel.ids import SourceId
from domain_kernel.protocols import DocumentParser
from pipeline.application.activities import Frozen, ParseRequest, parse_fetched
from pipeline.domain.errors import KnowledgeContractError
from pipeline.domain.knowledge import DocumentRecord
from pipeline.domain.ports import KnowledgeSink
from py_common.temporal import ActivityBase


class RegisterRequest(Frozen):
    parse: ParseRequest
    regulator: str = Field(min_length=1)


class Registered(Frozen):
    document_id: UUID
    clause_count: int = 0
    created: bool = False
    skipped: bool = False


class RegisterDocument(ActivityBase[RegisterRequest, Registered]):
    """Store the parsed document in the rulebook; idempotent, so a retry is harmless."""

    name: ClassVar[str] = "pipeline.register_document"
    input_type: ClassVar[type[RegisterRequest]] = RegisterRequest
    output_type: ClassVar[type[Registered]] = Registered
    start_to_close: ClassVar[timedelta] = timedelta(minutes=2)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=5,
        non_retryable_error_types=[
            "RulebookConflictError",
            "RulebookRejectedError",
            "KnowledgeContractError",
            "UnsupportedDocumentError",
        ],
    )

    def __init__(self, parser: DocumentParser, sink: KnowledgeSink, *, enabled: bool) -> None:
        self._parser = parser
        self._sink = sink
        self._enabled = enabled

    async def run(self, input: RegisterRequest) -> Registered:
        if not self._enabled:
            return Registered(document_id=input.parse.document_id, skipped=True)
        request = input.parse
        fetched = request.fetched
        parsed = parse_fetched(self._parser, fetched)
        parsed = dataclasses.replace(
            parsed,
            title=request.title or parsed.title,
            published_at=request.published_at or parsed.published_at,
        )
        registered = self._sink.register_document(
            DocumentRecord(
                document=parsed,
                source_id=SourceId(fetched.source_id),
                sha256=fetched.sha256,
                regulator=input.regulator,
                url=fetched.url,
                media_type=fetched.media_type,
                fetched_at=fetched.fetched_at,
                external_ref=fetched.external_ref,
            )
        )
        expected = {
            clause.clause_ref: clause_id_for(parsed.document_id, clause.clause_ref)
            for clause in parsed.clauses
        }
        if registered.document_id != parsed.document_id or dict(registered.clause_ids) != expected:
            raise KnowledgeContractError(
                f"the rulebook's ids for document {parsed.document_id} differ from the kernel's"
            )
        return Registered(
            document_id=parsed.document_id.value,
            clause_count=len(parsed.clauses),
            created=registered.created,
        )
