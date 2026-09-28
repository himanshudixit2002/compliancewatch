"""The rulebook's HTTP API as the pipeline's ``KnowledgeSink`` and ``RulebookReader``."""

from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import UUID

import httpx2

from domain_kernel.documents import Clause, DocumentType, ParsedDocument
from domain_kernel.ids import ClauseId, DocumentId
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

DOCUMENTS_PATH = "/v1/rulebook/documents/{document_id}"
MENTIONS_PATH = DOCUMENTS_PATH + "/mentions"
RELATIONS_PATH = DOCUMENTS_PATH + "/relation-candidates"
RULES_PATH = "/v1/rulebook/rules"
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

    def _send(self, method: str, path: str, body: Mapping[str, object] | None = None) -> Any:
        headers = {WRITE_TOKEN_HEADER: self._token} if self._token and method != "get" else {}
        try:
            if method == "get":
                response = self._client.get(path)
            else:
                response = self._client.put(path, json=dict(body or {}), headers=headers)
        except httpx2.TransportError as exc:
            raise RulebookUnavailableError(f"rulebook unreachable: {exc}") from exc
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
