"""The Langfuse tracer against a stub client: trace and generation shape, cost in usage, safety."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallKind, CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.tracing import CallRecord
from llm_gateway.infrastructure.tracing import langfuse as module
from llm_gateway.infrastructure.tracing.langfuse import LangfuseTracer

TENANT = TenantId.new()
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
PII = {"gstin": 1, "pan": 0, "aadhaar": 0, "phone": 0, "email": 0}


# ---- stub client ------------------------------------------------------------------------------


class Generation:
    def __init__(self) -> None:
        self.ended: list[dict[str, Any]] = []

    def end(self, **kwargs: Any) -> "Generation":
        self.ended.append(kwargs)
        return self


class Trace:
    def __init__(self) -> None:
        self.generations: list[dict[str, Any]] = []
        self.generation_client = Generation()

    def generation(self, **kwargs: Any) -> Generation:
        self.generations.append(kwargs)
        return self.generation_client


class Client:
    def __init__(self, *, fail: bool = False) -> None:
        self.traces: list[dict[str, Any]] = []
        self.trace_client = Trace()
        self.flushed = 0
        self.fail = fail

    def trace(self, **kwargs: Any) -> Trace:
        if self.fail:
            raise RuntimeError("langfuse down")
        self.traces.append(kwargs)
        return self.trace_client

    def flush(self) -> None:
        self.flushed += 1


def entry(**changes: Any) -> LedgerEntry:
    entry_id = uuid4()
    fields: dict[str, Any] = {
        "id": entry_id,
        "occurred_at": NOW,
        "tenant_id": TENANT,
        "feature": Feature.EXTRACTION,
        "prompt_name": "extraction.rule_candidate",
        "prompt_version": "0",
        "model_requested": "deepseek/deepseek-v4-pro-0813",
        "model_served": "zai/glm-5.3",
        "provider": "morph",
        "input_tokens": 10,
        "output_tokens": 5,
        "cached": False,
        "cost_usd": Decimal("0.000122"),
        "cost_inr": Decimal("0.0107"),
        "cost_source": CostSource.GATEWAY,
        "latency_ms": 12,
        "correlation_id": "req-1",
        "trace_id": str(entry_id),
        "generation_id": "gen-1",
        "status": CallStatus.OK,
    }
    fields.update(changes)
    return LedgerEntry(**fields)


def record(row: LedgerEntry | None = None, **changes: Any) -> CallRecord:
    fields: dict[str, Any] = {
        "entry": row if row is not None else entry(),
        "system": "Extract rules.",
        "user": "Section 7 says the return is due monthly.",
        "output": '{"rules": []}',
        "pii_counts": PII,
        "temperature": 0.0,
        "max_tokens": 1024,
        "has_schema": True,
        "metadata": {"document_id": "doc-1"},
    }
    fields.update(changes)
    return CallRecord(**fields)


def test_records_one_trace_with_one_generation() -> None:
    client = Client()
    row = entry()
    LangfuseTracer(client, environment="test").record(record(row))

    [trace] = client.traces
    assert trace == {
        "id": str(row.id),
        "name": "llm.extraction",
        "user_id": str(TENANT),
        "session_id": "req-1",
        "tags": ["extraction", "gateway", "live", "ok"],
        "metadata": {
            "prompt": "extraction.rule_candidate@0",
            "provider": "morph",
            "generation_id": "gen-1",
            "environment": "test",
            "correlation_id": "req-1",
            "document_id": "doc-1",
        },
    }
    [generation] = client.trace_client.generations
    assert generation == {
        "name": "extraction.rule_candidate@0",
        "model": "zai/glm-5.3",
        "model_parameters": {"temperature": "0.0", "max_tokens": 1024, "json_schema": True},
        "input": [
            {"role": "system", "content": "Extract rules."},
            {"role": "user", "content": "Section 7 says the return is due monthly."},
        ],
        "start_time": NOW,
        "metadata": {
            "pii": PII,
            "model_requested": "deepseek/deepseek-v4-pro-0813",
            "cached": False,
            "cost_source": "gateway",
        },
    }
    [end] = client.trace_client.generation_client.ended
    assert end == {
        "output": '{"rules": []}',
        "end_time": NOW + timedelta(milliseconds=12),
        "level": "DEFAULT",
        "status_message": None,
        "usage": {"input": 10, "output": 5, "total": 15, "unit": "TOKENS", "total_cost": 0.000122},
    }
    assert isinstance(end["usage"]["total_cost"], float)


def test_an_error_row_is_level_error_with_the_detail() -> None:
    client = Client()
    row = entry(
        status=CallStatus.ERROR,
        error_type="llm-provider-response-invalid",
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal("0.000000"),
        cost_inr=Decimal("0.0000"),
        cost_source=CostSource.ESTIMATE,
        generation_id="",
    )
    LangfuseTracer(client).record(
        record(row, output="", error_detail="gateway returned no choices")
    )

    assert client.traces[0]["tags"] == ["extraction", "estimate", "live", "error"]
    [end] = client.trace_client.generation_client.ended
    assert end["level"] == "ERROR"
    assert end["status_message"] == "gateway returned no choices"
    assert end["output"] == ""
    assert end["usage"]["total_cost"] == 0.0


def test_regulatory_cached_calls_without_a_system_prompt() -> None:
    client = Client()
    row = entry(
        tenant_id=None,
        cached=True,
        cost_usd=None,
        cost_inr=Decimal("0.0000"),
        cost_source=CostSource.CACHE,
        correlation_id="",
    )
    LangfuseTracer(client).record(record(row, system="", temperature=0.7, has_schema=False))

    [trace] = client.traces
    assert trace["user_id"] is None
    assert trace["session_id"] is None
    assert trace["tags"] == ["extraction", "cache", "cached", "ok"]
    assert trace["metadata"]["environment"] == "local"
    [generation] = client.trace_client.generations
    assert generation["input"] == [
        {"role": "user", "content": "Section 7 says the return is due monthly."}
    ]
    assert generation["model_parameters"] == {
        "temperature": "0.7",
        "max_tokens": 1024,
        "json_schema": False,
    }
    [end] = client.trace_client.generation_client.ended
    assert end["usage"]["total_cost"] is None


def test_an_embedding_is_traced_with_its_inputs_and_no_sampling_parameters() -> None:
    client = Client()
    row = entry(
        feature=Feature.RETRIEVAL,
        prompt_name="retrieval.embedding",
        prompt_version="1",
        model_requested="voyage/voyage-3.5-lite",
        model_served="voyage/voyage-3.5-lite",
        output_tokens=0,
    )
    embedding = record(
        row,
        system="",
        user="Section 7.\n\nSection 8.",
        output="2 vectors of 512 dimensions",
        max_tokens=None,
        has_schema=False,
        kind=CallKind.EMBEDDING,
    )
    LangfuseTracer(client).record(embedding)

    assert client.traces[0]["name"] == "llm.retrieval"
    [generation] = client.trace_client.generations
    assert generation["name"] == "retrieval.embedding@1"
    assert generation["model_parameters"] == {"kind": "embedding"}
    assert generation["input"] == "Section 7.\n\nSection 8."
    [end] = client.trace_client.generation_client.ended
    assert end["output"] == "2 vectors of 512 dimensions"
    assert (end["usage"]["input"], end["usage"]["output"]) == (10, 0)


@pytest.mark.parametrize(
    ("row", "status"),
    [
        (entry(), None),
        (
            entry(
                status=CallStatus.ERROR,
                error_type="llm-residency-unavailable",
                input_tokens=0,
                output_tokens=0,
                generation_id="",
            ),
            "llm-residency-unavailable",
        ),
    ],
    ids=["served", "refused"],
)
def test_without_text_only_the_calls_metadata_is_sent(row: LedgerEntry, status: str | None) -> None:
    """Under CW_LLM_RESIDENCY=india_only: no prompt, answer or error detail reaches Langfuse."""
    client = Client()
    tracer = LangfuseTracer(client, environment="test", send_text=False)
    assert tracer.send_text is False
    tracer.record(record(row, error_detail="refused: Section 7 says the return is due monthly."))

    [trace] = client.traces
    assert trace["name"] == "llm.extraction"
    assert trace["metadata"]["document_id"] == "doc-1"
    [generation] = client.trace_client.generations
    assert generation["input"] is None
    assert generation["metadata"]["pii"] == PII
    [end] = client.trace_client.generation_client.ended
    assert end["output"] is None
    assert end["status_message"] == status
    assert end["usage"]["input"] == row.input_tokens
    sent = repr((client.traces, client.trace_client.generations, end))
    for text in ("Section 7", "Extract rules.", '{"rules": []}'):
        assert text not in sent


def test_a_failing_client_is_logged_and_swallowed() -> None:
    client = Client(fail=True)
    row = entry()
    with capture_logs() as logs:
        LangfuseTracer(client).record(record(row))
    [line] = logs
    assert line["event"] == "langfuse_trace_failed"
    assert line["log_level"] == "error"
    assert line["trace_id"] == str(row.id)
    assert line["exc_info"] is True


def test_flush_delegates_to_the_client() -> None:
    client = Client()
    LangfuseTracer(client).flush()
    assert client.flushed == 1


def test_from_keys_builds_the_client_with_the_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []
    client = Client()

    def factory(**kwargs: Any) -> Client:
        built.append(kwargs)
        return client

    monkeypatch.setattr(module, "Langfuse", factory)
    tracer = LangfuseTracer.from_keys(
        public_key="pk-lf-dev",
        secret_key="sk-lf-dev",
        host="http://localhost:3010",
        environment="local",
    )
    assert tracer.send_text is True
    tracer.flush()
    assert built == [
        {"public_key": "pk-lf-dev", "secret_key": "sk-lf-dev", "host": "http://localhost:3010"}
    ]
    assert client.flushed == 1
