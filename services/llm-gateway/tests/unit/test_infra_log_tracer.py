"""The log tracer: one structured line per call, error rows at error level, no prompt text."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from structlog.testing import capture_logs

from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.tracing import CallRecord
from llm_gateway.infrastructure.tracing.log import LogTracer

TENANT = TenantId.new()
NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
PII = {"gstin": 1, "pan": 0, "aadhaar": 0, "phone": 2, "email": 0}


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
        "input_tokens": 1008,
        "output_tokens": 52,
        "cached": False,
        "cost_usd": Decimal("0.000122"),
        "cost_inr": Decimal("0.0107"),
        "cost_source": CostSource.GATEWAY,
        "latency_ms": 840,
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
        "system": "Extract rules. SECRET-SYSTEM",
        "user": "Section 7. SECRET-USER",
        "output": "SECRET-OUTPUT",
        "pii_counts": PII,
        "temperature": 0.0,
        "max_tokens": 1024,
        "has_schema": True,
        "metadata": {"document_id": "doc-1"},
    }
    fields.update(changes)
    return CallRecord(**fields)


def test_a_served_call_logs_one_info_line_with_the_ledger_fields() -> None:
    row = entry()
    with capture_logs() as logs:
        LogTracer().record(record(row))

    [line] = logs
    assert line["event"] == "llm.call.completed"
    assert line["log_level"] == "info"
    assert line["kind"] == "completion"
    assert line["feature"] == "extraction"
    assert line["prompt"] == "extraction.rule_candidate@0"
    assert (line["model_requested"], line["model_served"], line["provider"]) == (
        "deepseek/deepseek-v4-pro-0813",
        "zai/glm-5.3",
        "morph",
    )
    assert (line["input_tokens"], line["output_tokens"]) == (1008, 52)
    assert (line["cost_usd"], line["cost_inr"], line["cost_source"]) == (
        "0.000122",
        "0.0107",
        "gateway",
    )
    assert (line["cached"], line["latency_ms"], line["status"], line["error_type"]) == (
        False,
        840,
        "ok",
        "",
    )
    assert line["pii"] == PII
    assert line["metadata"] == {"document_id": "doc-1"}
    assert line["tenant_id"] == str(TENANT)
    assert (line["correlation_id"], line["trace_id"], line["generation_id"]) == (
        "req-1",
        str(row.id),
        "gen-1",
    )
    assert "error_detail" not in line
    assert "SECRET" not in json.dumps(line, default=str)


def test_an_error_row_logs_at_error_with_the_detail() -> None:
    row = entry(
        status=CallStatus.ERROR,
        error_type="llm-provider-unavailable",
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal("0.000000"),
        cost_inr=Decimal("0.0000"),
        cost_source=CostSource.ESTIMATE,
        generation_id="",
    )
    with capture_logs() as logs:
        LogTracer().record(record(row, output="", error_detail="gateway returned 503"))

    [line] = logs
    assert line["log_level"] == "error"
    assert line["event"] == "llm.call.completed"
    assert line["status"] == "error"
    assert line["error_type"] == "llm-provider-unavailable"
    assert line["error_detail"] == "gateway returned 503"
    assert (line["cost_usd"], line["cost_inr"]) == ("0.000000", "0.0000")


def test_a_regulatory_call_without_a_gateway_cost_logs_nulls() -> None:
    row = entry(tenant_id=None, cost_usd=None, cost_source=CostSource.ESTIMATE)
    with capture_logs() as logs:
        LogTracer().record(record(row))
    [line] = logs
    assert line["tenant_id"] is None
    assert line["cost_usd"] is None


def test_flush_does_nothing() -> None:
    LogTracer().flush()
