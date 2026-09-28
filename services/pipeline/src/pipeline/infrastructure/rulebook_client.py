"""The rulebook's HTTP API as the pipeline's ``KnowledgeSink``."""

from uuid import UUID

import httpx2

from domain_kernel.ids import ClauseId, DocumentId
from pipeline.domain.errors import (
    RulebookConflictError,
    RulebookRejectedError,
    RulebookUnavailableError,
)
from pipeline.domain.knowledge import DocumentRecord, RegisteredDocument

DOCUMENTS_PATH = "/v1/rulebook/documents/{document_id}"
WRITE_TOKEN_HEADER = "x-cw-write-token"
WRITES_DISABLED = "rulebook-writes-disabled"
"""The problem type of the 503 a rulebook without a write token answers: configuration, not an
outage, so it is not retried."""


class HttpRulebook:
    """``base_url`` is ``CW_RULEBOOK_URL``; ``token`` the shared write token. Pass ``client`` to
    talk to an in-process app (a FastAPI ``TestClient``) instead of the network."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        *,
        token: str | None = None,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._token = token

    def register_document(self, record: DocumentRecord) -> RegisteredDocument:
        document = record.document
        body = {
            "source_id": str(record.source_id),
            "sha256": record.sha256,
            "regulator": record.regulator,
            "doc_type": document.doc_type.value,
            "external_ref": record.external_ref,
            "url": record.url,
            "title": document.title,
            "language": document.language,
            "media_type": record.media_type,
            "parser_version": document.parser_version,
            "published_at": None
            if document.published_at is None
            else document.published_at.isoformat(),
            "fetched_at": record.fetched_at.isoformat(),
            "raw_uri": record.raw_uri,
            "clauses": [
                {"clause_ref": clause.clause_ref, "text": clause.text, "page": clause.page}
                for clause in document.clauses
            ],
        }
        path = DOCUMENTS_PATH.format(document_id=document.document_id)
        headers = {WRITE_TOKEN_HEADER: self._token} if self._token else {}
        try:
            response = self._client.put(path, json=body, headers=headers)
        except httpx2.TransportError as exc:
            raise RulebookUnavailableError(f"rulebook unreachable: {exc}") from exc
        if response.status_code in (200, 201):
            data = response.json()
            return RegisteredDocument(
                document_id=DocumentId(UUID(str(data["document_id"]))),
                created=bool(data["created"]),
                clause_ids={
                    str(ref): ClauseId(UUID(str(clause_id)))
                    for ref, clause_id in dict(data["clause_ids"]).items()
                },
            )
        detail = f"{response.status_code}: {response.text[:500]}"
        if response.status_code == 409:
            raise RulebookConflictError(detail)
        if response.status_code >= 500 and WRITES_DISABLED not in response.text:
            raise RulebookUnavailableError(detail)
        raise RulebookRejectedError(detail)

    def close(self) -> None:
        self._client.close()
