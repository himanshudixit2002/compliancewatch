"""Langfuse tracing: one trace per call with one generation inside it, the cost inside ``usage``.

Pinned to the v2 SDK because the self-hosted server is v2 (a v3 server needs ClickHouse,
Redis and MinIO). The client is injected so tests use a stub and never start the SDK's
background thread; ``from_keys`` builds the real one. The SDK ships no type marker, so the
client is described by the small protocol below.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal, Protocol, Self

from langfuse import Langfuse  # type: ignore[import-untyped]

from llm_gateway.domain.features import CallKind, CallStatus
from llm_gateway.domain.tracing import CallRecord
from py_common.logging import get_logger

log = get_logger(__name__)

Level = Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"]
ModelParameters = dict[str, str | int | bool | list[str] | None]
Usage = dict[str, str | int | float | None]


class GenerationClient(Protocol):
    def end(
        self,
        *,
        output: object,
        end_time: datetime,
        level: Level,
        status_message: str | None,
        usage: Usage,
    ) -> object: ...


class TraceClient(Protocol):
    def generation(
        self,
        *,
        name: str,
        model: str,
        model_parameters: ModelParameters,
        input: object,
        start_time: datetime,
        metadata: dict[str, object],
    ) -> GenerationClient: ...


class LangfuseClient(Protocol):
    """The part of ``langfuse.Langfuse`` this tracer uses."""

    def trace(
        self,
        *,
        id: str,
        name: str,
        user_id: str | None,
        session_id: str | None,
        tags: list[str],
        metadata: dict[str, object],
    ) -> TraceClient: ...

    def flush(self) -> None: ...


class LangfuseTracer:
    """Never fails a call: any SDK error is logged and swallowed."""

    def __init__(self, client: LangfuseClient, *, environment: str = "local") -> None:
        self._client = client
        self._environment = environment

    @classmethod
    def from_keys(
        cls, *, public_key: str, secret_key: str, host: str, environment: str = "local"
    ) -> Self:
        """A tracer over a real client; ``flush`` at shutdown sends what the SDK buffered."""
        client: LangfuseClient = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return cls(client, environment=environment)

    def record(self, call: CallRecord) -> None:
        try:
            self._record(call)
        except Exception:
            log.exception("langfuse_trace_failed", trace_id=call.entry.trace_id)

    def flush(self) -> None:
        self._client.flush()

    def _record(self, call: CallRecord) -> None:
        entry = call.entry
        prompt = f"{entry.prompt_name}@{entry.prompt_version}"
        failed = entry.status is CallStatus.ERROR
        trace = self._client.trace(
            id=entry.trace_id,
            name=f"llm.{entry.feature.value}",
            user_id=None if entry.tenant_id is None else str(entry.tenant_id),
            session_id=entry.correlation_id or None,
            tags=[
                entry.feature.value,
                entry.cost_source.value,
                "cached" if entry.cached else "live",
                entry.status.value,
            ],
            metadata={
                "prompt": prompt,
                "provider": entry.provider,
                "generation_id": entry.generation_id,
                "environment": self._environment,
                "correlation_id": entry.correlation_id,
                **call.metadata,
            },
        )
        generation = trace.generation(
            name=prompt,
            model=entry.model_served,
            model_parameters=_parameters(call),
            input=_messages(call) if call.kind is CallKind.COMPLETION else call.user,
            start_time=entry.occurred_at,
            metadata={
                "pii": dict(call.pii_counts),
                "model_requested": entry.model_requested,
                "cached": entry.cached,
                "cost_source": entry.cost_source.value,
            },
        )
        generation.end(
            output=call.output,
            end_time=entry.occurred_at + timedelta(milliseconds=entry.latency_ms),
            level="ERROR" if failed else "DEFAULT",
            status_message=call.error_detail or None,
            usage=_usage(entry.input_tokens, entry.output_tokens, entry.cost_usd),
        )


def _parameters(call: CallRecord) -> ModelParameters:
    """Sampling parameters of a completion; an embedding has none but its kind."""
    if call.kind is CallKind.EMBEDDING:
        return {"kind": call.kind.value}
    return {
        "temperature": str(call.temperature),
        "max_tokens": call.max_tokens,
        "json_schema": call.has_schema,
    }


def _messages(call: CallRecord) -> list[Mapping[str, str]]:
    """The scrubbed prompt as chat messages; the system message only when there is one."""
    messages: list[Mapping[str, str]] = []
    if call.system:
        messages.append({"role": "system", "content": call.system})
    messages.append({"role": "user", "content": call.user})
    return messages


def _usage(input_tokens: int, output_tokens: int, cost_usd: object) -> Usage:
    """Token counts and the USD cost in the v2 shape; ``total_cost`` is the only way cost lands."""
    return {
        "input": input_tokens,
        "output": output_tokens,
        "total": input_tokens + output_tokens,
        "unit": "TOKENS",
        "total_cost": None if cost_usd is None else float(str(cost_usd)),
    }
