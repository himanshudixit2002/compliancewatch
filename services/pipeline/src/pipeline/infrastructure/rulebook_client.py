"""The rulebook's HTTP API as the pipeline's ``KnowledgeSink``, ``RulebookReader`` and
``ClauseIndexSink``.

Writes carry the rulebook's shared write token (``x-cw-write-token``) while one is configured,
and every request carries the pipeline's own access token once ``CW_SERVICE_CLIENT_SECRET`` is
set (``auth``, from ``py_common.auth.service_auth_from``). Both go out during the move from
shared tokens to service tokens: a rulebook in ``header`` mode reads the write token, one in
``dual`` or ``token`` mode the bearer, which needs the rulebook:write scope. A token the identity
service could not issue is ``RulebookUnavailableError``, retried like an unreachable rulebook.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

import httpx2

from domain_kernel.documents import Clause, DocumentType, ParsedDocument
from domain_kernel.ids import ClauseId, DocumentId
from pipeline.domain.embedding import ClauseToEmbed, ClauseVector, EmbeddingsStored
from pipeline.domain.errors import (
    RulebookConflictError,
    RulebookRejectedError,
    RulebookUnavailableError,
)
from pipeline.domain.issues import Issue
from pipeline.domain.knowledge import (
    AlignmentReport,
    DocumentRecord,
    MentionSubmission,
    RegisteredDocument,
    RelationSubmission,
    RuleKey,
    StagingReport,
)
from py_common.auth import ServiceTokenUnavailableError

DOCUMENTS_PATH = "/v1/rulebook/documents/{document_id}"
MENTIONS_PATH = DOCUMENTS_PATH + "/mentions"
RELATIONS_PATH = DOCUMENTS_PATH + "/relation-candidates"
RULES_PATH = "/v1/rulebook/rules"
UNEMBEDDED_PATH = "/v1/rulebook/clauses/unembedded"
EMBEDDINGS_PATH = "/v1/rulebook/clauses/embeddings"
WRITE_TOKEN_HEADER = "x-cw-write-token"
WRITES_DISABLED = "rulebook-writes-disabled"
"""The problem type of the 503 a rulebook without a write token answers: configuration, not an
outage, so it is not retried."""


class HttpRulebook:
    """``base_url`` is ``CW_RULEBOOK_URL``; ``token`` the shared write token and ``auth`` the
    service's token auth (None sends no bearer). Pass ``client`` to talk to an in-process app (a
    FastAPI ``TestClient``) instead of the network; ``auth`` applies to it too."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        *,
        token: str | None = None,
        auth: httpx2.Auth | None = None,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._token = token
        self._auth = auth

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
        data = self._send("put", DOCUMENTS_PATH.format(document_id=document.document_id), body)
        return RegisteredDocument(
            document_id=DocumentId(UUID(str(data["document_id"]))),
            created=bool(data["created"]),
            clause_ids={
                str(ref): ClauseId(UUID(str(clause_id)))
                for ref, clause_id in dict(data["clause_ids"]).items()
            },
        )

    def submit_mentions(self, submission: MentionSubmission) -> AlignmentReport:
        body = {
            "extractor": submission.extractor,
            "mentions": [
                {
                    "clause_ref": m.clause_ref,
                    "entity_type": m.entity_type.value,
                    "text": m.text,
                    "span_start": m.span_start,
                    "span_end": m.span_end,
                    "proposed_name": m.proposed_name,
                }
                for m in submission.mentions
            ],
        }
        data = self._send("put", MENTIONS_PATH.format(document_id=submission.document_id), body)
        return AlignmentReport(
            aligned=int(data["aligned"]),
            queued=int(data["queued"]),
            unchanged=int(data["unchanged"]),
        )

    def submit_relations(self, submission: RelationSubmission) -> StagingReport:
        body = {
            "extractor": submission.extractor,
            "model": submission.model,
            "outcome": submission.outcome,
            "run_issues": [_issue(issue) for issue in submission.run_issues],
            "candidates": [
                {
                    "relation": c.relation.value,
                    "target_type": c.target.entity_type.value,
                    "target_name": c.target.proposed_name,
                    "target_clause_ref": c.target.clause_ref,
                    "target_span_start": c.target.span_start,
                    "target_span_end": c.target.span_end,
                    "rule_key": c.rule_key,
                    "evidence_clause_ref": c.evidence_clause_ref,
                    "evidence_quote": c.evidence_quote,
                    "quote_score": c.quote_score,
                    "period_label": c.period_label,
                    "new_due_on": None if c.new_due_on is None else c.new_due_on.isoformat(),
                    "confidence": c.confidence,
                    "issues": [_issue(issue) for issue in c.issues],
                    "needs_review": c.needs_review,
                }
                for c in submission.candidates
            ],
        }
        data = self._send("put", RELATIONS_PATH.format(document_id=submission.document_id), body)
        return StagingReport(created=int(data["created"]), unchanged=int(data["unchanged"]))

    def parsed_document(self, document_id: DocumentId) -> ParsedDocument:
        data = self._send("get", DOCUMENTS_PATH.format(document_id=document_id))
        published = data.get("published_at")
        return ParsedDocument(
            document_id=DocumentId(UUID(str(data["document_id"]))),
            doc_type=DocumentType(str(data["doc_type"])),
            title=str(data["title"]),
            clauses=tuple(
                Clause(clause_ref=str(c["clause_ref"]), text=str(c["text"]), page=c.get("page"))
                for c in data["clauses"]
            ),
            published_at=None if published is None else date.fromisoformat(str(published)),
            language=str(data["language"]),
            parser_version=str(data["parser_version"]),
        )

    def known_rules(self) -> tuple[RuleKey, ...]:
        data = self._send("get", RULES_PATH)
        return tuple(RuleKey(str(rule["rule_key"]), str(rule["title"])) for rule in data)

    def unembedded_clauses(
        self,
        model: str,
        *,
        document_id: DocumentId | None = None,
        limit: int = 64,
        after: ClauseId | None = None,
    ) -> tuple[ClauseToEmbed, ...]:
        params: dict[str, str | int] = {"model": model, "limit": limit}
        if document_id is not None:
            params["document_id"] = str(document_id)
        if after is not None:
            params["after"] = str(after)
        data = self._send("get", UNEMBEDDED_PATH, params=params)
        return tuple(_clause_to_embed(item) for item in data)

    def put_embeddings(
        self, model: str, dims: int, items: Sequence[ClauseVector]
    ) -> EmbeddingsStored:
        body = {
            "model": model,
            "dims": dims,
            "items": [
                {"clause_id": str(item.clause_id), "vector": list(item.vector)} for item in items
            ],
        }
        data = self._send("put", EMBEDDINGS_PATH, body)
        return EmbeddingsStored(stored=int(data["stored"]), unchanged=int(data["unchanged"]))

    def _send(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> Any:
        headers = {WRITE_TOKEN_HEADER: self._token} if self._token and method != "get" else {}
        auth = httpx2.USE_CLIENT_DEFAULT if self._auth is None else self._auth
        try:
            if method == "get":
                response = self._client.get(path, params=dict(params or {}), auth=auth)
            else:
                response = self._client.put(path, json=dict(body or {}), headers=headers, auth=auth)
        except httpx2.TransportError as exc:
            raise RulebookUnavailableError(f"rulebook unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise RulebookUnavailableError(f"no service token for the rulebook: {exc}") from exc
        if response.status_code in (200, 201):
            return response.json()
        detail = f"{response.status_code}: {response.text[:500]}"
        if response.status_code == 409:
            raise RulebookConflictError(detail)
        if response.status_code >= 500 and WRITES_DISABLED not in response.text:
            raise RulebookUnavailableError(detail)
        raise RulebookRejectedError(detail)

    def close(self) -> None:
        self._client.close()


def _issue(issue: Issue) -> dict[str, str]:
    return {"code": issue.code, "detail": issue.detail[:2_000]}


def _clause_to_embed(item: Mapping[str, Any]) -> ClauseToEmbed:
    published = item.get("published_at")
    return ClauseToEmbed(
        clause_id=ClauseId(UUID(str(item["clause_id"]))),
        document_id=DocumentId(UUID(str(item["document_id"]))),
        clause_ref=str(item["clause_ref"]),
        text=str(item["text"]),
        regulator=str(item["regulator"]),
        doc_type=DocumentType(str(item["doc_type"])),
        external_ref=str(item.get("external_ref") or ""),
        title=str(item.get("title") or ""),
        published_at=None if published is None else date.fromisoformat(str(published)),
    )
