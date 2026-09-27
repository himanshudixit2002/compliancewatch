from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from uuid import uuid4

import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.tracing import CallRecord, Tracer


def _entry() -> LedgerEntry:
    entry_id = uuid4()
    return LedgerEntry(
        id=entry_id,
        occurred_at=datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
        tenant_id=None,
        feature=Feature.QA,
        prompt_name="qa.answer",
        prompt_version="1",
        model_requested="fake/echo",
        model_served="fake/echo",
        provider="fake",
        input_tokens=1,
        output_tokens=1,
        cached=False,
        cost_usd=None,
        cost_inr=Decimal("0.0000"),
        cost_source=CostSource.ESTIMATE,
        latency_ms=0,
        correlation_id="",
        trace_id=str(entry_id),
        generation_id="",
        status=CallStatus.OK,
    )


def _record(**changes: object) -> CallRecord:
    fields: dict[str, object] = {
        "entry": _entry(),
        "system": "",
        "user": "[PAN] filed",
        "output": "fake:[PAN] filed",
        "pii_counts": {"pan": 1},
        "temperature": 0.0,
        "max_tokens": 64,
        "has_schema": False,
        "metadata": {"document_id": "doc-1"},
    }
    fields.update(changes)
    return CallRecord(**fields)  # type: ignore[arg-type]


def test_record_freezes_its_mappings() -> None:
    record = _record()
    assert isinstance(record.pii_counts, MappingProxyType)
    assert isinstance(record.metadata, MappingProxyType)
    assert record.metadata == {"document_id": "doc-1"}
    assert record.error_detail == ""
    assert _record(error_detail="boom").error_detail == "boom"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"entry": None}, "entry must be LedgerEntry"),
        ({"system": None}, "system must be str"),
        ({"user": 1}, "user must be str"),
        ({"output": b""}, "output must be str"),
        ({"pii_counts": [1]}, "pii_counts must be a mapping"),
        ({"pii_counts": {"pan": -1}}, r"pii_counts\['pan'\] must be at least 0"),
        ({"temperature": float("nan")}, "temperature must be a finite number"),
        ({"max_tokens": 0}, "max_tokens must be at least 1"),
        ({"has_schema": 1}, "has_schema must be bool"),
        ({"metadata": {"pages": 3}}, "metadata values must be strings"),
        ({"metadata": "x"}, "metadata must be a mapping"),
        ({"error_detail": None}, "error_detail must be str"),
    ],
)
def test_record_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        _record(**changes)


class _Tracer:
    def __init__(self) -> None:
        self.records: list[CallRecord] = []
        self.flushed = 0

    def record(self, call: CallRecord) -> None:
        self.records.append(call)

    def flush(self) -> None:
        self.flushed += 1


def test_tracer_protocol_is_structural() -> None:
    tracer: Tracer = _Tracer()
    tracer.record(_record())
    tracer.flush()
    assert isinstance(tracer, _Tracer)
    assert (len(tracer.records), tracer.flushed) == (1, 1)
