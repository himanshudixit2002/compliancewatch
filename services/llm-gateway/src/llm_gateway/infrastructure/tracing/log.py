"""A tracer that writes one structured log line per call: the trace every deployment has."""

from llm_gateway.domain.features import CallStatus
from llm_gateway.domain.tracing import CallRecord
from py_common.logging import get_logger

EVENT = "llm.call.completed"
log = get_logger(__name__)


class LogTracer:
    """Info for a served call, error for an error row. Never logs the prompt or the answer."""

    def record(self, call: CallRecord) -> None:
        entry = call.entry
        fields: dict[str, object] = {
            "feature": entry.feature.value,
            "prompt": f"{entry.prompt_name}@{entry.prompt_version}",
            "model_requested": entry.model_requested,
            "model_served": entry.model_served,
            "provider": entry.provider,
            "input_tokens": entry.input_tokens,
            "output_tokens": entry.output_tokens,
            "cost_usd": None if entry.cost_usd is None else format(entry.cost_usd, "f"),
            "cost_inr": format(entry.cost_inr, "f"),
            "cost_source": entry.cost_source.value,
            "cached": entry.cached,
            "latency_ms": entry.latency_ms,
            "pii": dict(call.pii_counts),
            "metadata": dict(call.metadata),
            "tenant_id": None if entry.tenant_id is None else str(entry.tenant_id),
            "correlation_id": entry.correlation_id,
            "trace_id": entry.trace_id,
            "generation_id": entry.generation_id,
            "status": entry.status.value,
            "error_type": entry.error_type,
        }
        if entry.status is CallStatus.ERROR:
            log.error(EVENT, error_detail=call.error_detail, **fields)
        else:
            log.info(EVENT, **fields)

    def flush(self) -> None:
        return None
