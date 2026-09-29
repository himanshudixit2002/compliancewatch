"""The pipeline's own access token on its calls to the rulebook and the gateway.

With ``CW_SERVICE_CLIENT_SECRET`` set every request carries ``Authorization: Bearer`` with the
token the identity service issued, and the rulebook's writes still carry the shared write token
while it is configured. Without the secret nothing changes: only the write-token header goes out.
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from domain_kernel.documents import (
    Clause,
    DocumentType,
    ParsedDocument,
    clause_id_for,
    document_id_for,
)
from domain_kernel.ids import SourceId
from domain_kernel.llm import CompletionRequest
from pipeline import embed, worker
from pipeline.domain.embedding import ClauseVector
from pipeline.domain.errors import RulebookUnavailableError
from pipeline.domain.knowledge import DocumentRecord
from pipeline.infrastructure.gateway import GatewayEmbedder, GatewayError, GatewayProvider
from pipeline.infrastructure.rulebook_client import WRITE_TOKEN_HEADER, HttpRulebook
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryRulebook, ScriptedEmbedder
from py_common.auth import BearerAuth, service_auth_from
from py_common.auth.service_tokens import SERVICE_TOKENS_PATH

IDENTITY_URL = "http://identity.test"
CLIENT_ID = "pipeline"
CLIENT_SECRET = SecretStr("pipeline-" + "s" * 32)
"""The dev client secret these tests exchange; the fake identity checks it."""
WRITE_TOKEN = "write-" + "w" * 16
DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOCUMENT_ID = document_id_for(DIGEST)
CLAUSE_ID = clause_id_for(DOCUMENT_ID, "en.p1")
COMPLETION = {
    "text": "{}",
    "model_served": "fake/echo",
    "input_tokens": 3,
    "output_tokens": 1,
    "cached": False,
    "trace_id": "t1",
}
EMBEDDING = {"model_served": "fake/embed", "dims": 2, "vectors": [[0.6, 0.8]], "trace_id": "t2"}


class Identity:
    """The identity service's token route: checks the client and numbers the tokens it issues."""

    def __init__(self) -> None:
        self.issued = 0
        self.down = False

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == IDENTITY_URL + SERVICE_TOKENS_PATH
        if self.down:
            return httpx2.Response(503, json={"type": "urn:problem:unavailable"})
        body = json.loads(request.content)
        if body != {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET.get_secret_value()}:
            return httpx2.Response(401, json={"type": "identity-service-client-invalid"})
        self.issued += 1
        return httpx2.Response(
            200,
            json={
                "access_token": f"service-token-{self.issued}",
                "token_type": "Bearer",
                "expires_in": 600,
                "scopes": ["rulebook:write", "llm:call", "tenant:act"],
            },
        )


def settings(*, secret: SecretStr | None = CLIENT_SECRET, **overrides: Any) -> PipelineSettings:
    return PipelineSettings(
        _env_file=None,
        service_name="pipeline-worker",
        identity_url=IDENTITY_URL,
        service_client_id=CLIENT_ID,
        service_client_secret=secret,
        **overrides,
    )


def auth_for(identity: Identity) -> BearerAuth:
    auth = service_auth_from(
        settings(), client=httpx2.Client(transport=httpx2.MockTransport(identity))
    )
    assert auth is not None
    return auth


def recording(
    answer: Callable[[httpx2.Request], httpx2.Response], base_url: str
) -> tuple[httpx2.Client, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return answer(request)

    return httpx2.Client(base_url=base_url, transport=httpx2.MockTransport(handler)), seen


def rulebook_answer(request: httpx2.Request) -> httpx2.Response:
    if request.method == "GET":
        return httpx2.Response(200, json=[{"rule_key": "gst.gstr3b", "title": "GSTR-3B"}])
    return httpx2.Response(200, json={"stored": 1, "unchanged": 0})


def record() -> DocumentRecord:
    return DocumentRecord(
        document=ParsedDocument(
            document_id=DOCUMENT_ID,
            doc_type=DocumentType.NOTIFICATION,
            title="Notification No. 01/2026",
            clauses=(Clause("en.p1", "first", page=1),),
            published_at=date(2026, 1, 16),
            parser_version="pdf@1",
        ),
        source_id=SourceId.new(),
        sha256=DIGEST,
        regulator="CBIC",
        url="https://example.invalid/n.pdf",
        media_type="application/pdf",
        fetched_at=datetime(2026, 9, 28, 6, tzinfo=UTC),
        external_ref="01/2026-Central Tax",
    )


# ---------------------------------------------------------------- the rulebook


def test_with_a_client_secret_every_rulebook_call_carries_the_bearer_and_writes_the_token() -> None:
    identity = Identity()
    client, seen = recording(rulebook_answer, "http://rulebook.test")
    rulebook = HttpRulebook(token=WRITE_TOKEN, auth=auth_for(identity), client=client)
    assert rulebook.known_rules()[0].rule_key == "gst.gstr3b"
    stored = rulebook.put_embeddings("fake/embed", 2, [ClauseVector(CLAUSE_ID, (1, 0))])
    rulebook.close()
    assert (stored.stored, stored.unchanged) == (1, 0)
    read, write = seen
    assert read.headers["authorization"] == "Bearer service-token-1"
    assert WRITE_TOKEN_HEADER not in read.headers
    assert write.headers["authorization"] == "Bearer service-token-1"
    assert write.headers[WRITE_TOKEN_HEADER] == WRITE_TOKEN
    assert identity.issued == 1


def test_without_a_client_secret_only_the_write_token_goes_out() -> None:
    assert service_auth_from(settings(secret=None)) is None
    client, seen = recording(rulebook_answer, "http://rulebook.test")
    rulebook = HttpRulebook(token=WRITE_TOKEN, auth=None, client=client)
    rulebook.known_rules()
    rulebook.put_embeddings("fake/embed", 2, [])
    read, write = seen
    assert "authorization" not in read.headers
    assert "authorization" not in write.headers
    assert write.headers[WRITE_TOKEN_HEADER] == WRITE_TOKEN


def test_a_rulebook_in_token_mode_can_take_the_bearer_alone() -> None:
    client, seen = recording(
        lambda request: httpx2.Response(
            201,
            json={
                "document_id": str(DOCUMENT_ID),
                "created": True,
                "clause_ids": {"en.p1": str(CLAUSE_ID)},
            },
        ),
        "http://rulebook.test",
    )
    rulebook = HttpRulebook(auth=auth_for(Identity()), client=client)
    assert rulebook.register_document(record()).created is True
    (request,) = seen
    assert request.headers["authorization"] == "Bearer service-token-1"
    assert WRITE_TOKEN_HEADER not in request.headers


def test_a_refused_token_is_replaced_once_and_the_write_resent() -> None:
    identity = Identity()
    sent: list[tuple[str, Any]] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append((request.headers["authorization"], json.loads(request.content)))
        if request.headers["authorization"] == "Bearer service-token-1":
            return httpx2.Response(401, json={"type": "auth-token-invalid"})
        return httpx2.Response(200, json={"stored": 2, "unchanged": 0})

    client, _ = recording(answer, "http://rulebook.test")
    rulebook = HttpRulebook(token=WRITE_TOKEN, auth=auth_for(identity), client=client)
    assert rulebook.put_embeddings("fake/embed", 2, []).stored == 2
    body = {"model": "fake/embed", "dims": 2, "items": []}
    assert sent == [("Bearer service-token-1", body), ("Bearer service-token-2", body)]


def test_no_service_token_is_a_rulebook_outage_worth_retrying() -> None:
    identity = Identity()
    identity.down = True
    client, seen = recording(rulebook_answer, "http://rulebook.test")
    rulebook = HttpRulebook(token=WRITE_TOKEN, auth=auth_for(identity), client=client)
    with pytest.raises(RulebookUnavailableError, match="no service token for the rulebook"):
        rulebook.put_embeddings("fake/embed", 2, [])
    with pytest.raises(RulebookUnavailableError, match="no service token"):
        rulebook.known_rules()
    assert seen == []


# ---------------------------------------------------------------- the gateway


def test_gateway_calls_carry_the_bearer_and_the_tenant_they_name() -> None:
    identity = Identity()
    auth = auth_for(identity)
    client, seen = recording(
        lambda request: httpx2.Response(
            200, json=COMPLETION if request.url.path.endswith("completions") else EMBEDDING
        ),
        "http://gateway.test",
    )
    tenant = "00000000-0000-0000-0000-000000000001"
    provider = GatewayProvider(client=client, tenant_id=tenant, auth=auth)
    assert provider.complete(CompletionRequest("extraction", "x.y@1", "s", "u")).text == "{}"
    embedder = GatewayEmbedder(client=client, auth=auth)
    assert embedder.embed(["clause"]).model == "fake/embed"
    completion, embedding = seen
    assert completion.headers["authorization"] == "Bearer service-token-1"
    assert completion.headers["x-tenant-id"] == tenant
    assert embedding.headers["authorization"] == "Bearer service-token-1"
    assert "x-tenant-id" not in embedding.headers
    assert identity.issued == 1


def test_without_a_client_secret_gateway_calls_carry_no_bearer() -> None:
    client, seen = recording(lambda request: httpx2.Response(200, json=COMPLETION), "http://g")
    GatewayProvider(client=client).complete(CompletionRequest("extraction", "x.y@1", "s", "u"))
    assert "authorization" not in seen[0].headers


def test_no_service_token_is_a_gateway_error() -> None:
    identity = Identity()
    identity.down = True
    auth = auth_for(identity)
    client, seen = recording(lambda request: httpx2.Response(200, json=EMBEDDING), "http://g")
    with pytest.raises(GatewayError, match="no service token for the gateway"):
        GatewayProvider(client=client, auth=auth).complete(
            CompletionRequest("extraction", "x.y@1", "s", "u")
        )
    with pytest.raises(GatewayError, match="no service token for the gateway"):
        GatewayEmbedder(client=client, auth=auth).embed(["clause"])
    assert seen == []


# ---------------------------------------------------------------- wiring


class Built:
    """Stands in for a client class and records the keyword arguments each instance got."""

    def __init__(self, made: object) -> None:
        self.made = made
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return self.made


def test_the_worker_passes_its_service_auth_to_every_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rulebook, provider, embedder = Built(MemoryRulebook()), Built(object()), Built(object())
    monkeypatch.setattr(worker, "HttpRulebook", rulebook)
    monkeypatch.setattr(worker, "GatewayProvider", provider)
    monkeypatch.setattr(worker, "GatewayEmbedder", embedder)
    worker.activities(
        settings(pipeline_knowledge_enabled=True, rulebook_write_token=SecretStr(WRITE_TOKEN))
    )
    (made,) = rulebook.calls
    assert made["token"] == WRITE_TOKEN
    auth = made["auth"]
    assert isinstance(auth, BearerAuth)
    assert auth.source.client_id == CLIENT_ID
    assert provider.calls == [{"auth": auth}]
    assert embedder.calls == [{"auth": auth}]


def test_the_worker_without_a_secret_sends_no_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    rulebook = Built(MemoryRulebook())
    monkeypatch.setattr(worker, "HttpRulebook", rulebook)
    worker.activities(settings(secret=None), embedder=ScriptedEmbedder())
    assert rulebook.calls == [{"token": None, "auth": None}]


class ClosingRulebook(MemoryRulebook):
    def close(self) -> None:
        pass


class ClosingEmbedder(ScriptedEmbedder):
    def close(self) -> None:
        pass


def test_the_embedding_backfill_uses_the_service_auth(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made_rulebook, made_embedder = Built(ClosingRulebook()), Built(ClosingEmbedder())
    monkeypatch.setattr(embed, "PipelineSettings", lambda service_name: settings())
    monkeypatch.setattr(embed, "HttpRulebook", made_rulebook)
    monkeypatch.setattr(embed, "GatewayEmbedder", made_embedder)
    assert embed.main([]) == 0
    assert capsys.readouterr().out.endswith("embedded 0, unchanged 0\n")
    auth = made_rulebook.calls[0]["auth"]
    assert isinstance(auth, BearerAuth)
    assert made_embedder.calls == [{"auth": auth}]
