"""The composite tracer: every tracer sees every call; one failing never stops the others."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from structlog.testing import capture_logs

from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.tracing import CallRecord
from llm_gateway.infrastructure.tracing.composite import CompositeTracer


class Recording:
    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[CallRecord] = []
        self.flushes = 0
        self.fail = fail

    def record(self, call: CallRecord) -> None:
        if self.fail:
            raise RuntimeError("tracer down")
        self.records.append(call)

    def flush(self) -> None:
        if self.fail:
            raise RuntimeError("flush down")
        self.flushes += 1


def call() -> CallRecord:
    entry_id = uuid4()
    entry = LedgerEntry(
        id=entry_id,
        occurred_at=datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
        tenant_id=TenantId.new(),
        feature=Feature.SMOKE,
        prompt_name="smoke.echo",
        prompt_version="1",
        model_requested="fake/echo",
        model_served="fake/echo",
        provider="fake",
        input_tokens=3,
        output_tokens=2,
        cached=False,
        cost_usd=Decimal("0.000001"),
        cost_inr=Decimal("0.0001"),
        cost_source=CostSource.ESTIMATE,
        latency_ms=1,
        correlation_id="req-1",
        trace_id=str(entry_id),
        generation_id="fake-1",
        status=CallStatus.OK,
    )
    return CallRecord(
        entry=entry,
        system="",
        user="hello",
        output="fake:hello",
        pii_counts={},
        temperature=0.0,
        max_tokens=16,
        has_schema=False,
        metadata={},
    )


def test_every_tracer_sees_the_call_in_order() -> None:
    first, second = Recording(), Recording()
    composite = CompositeTracer([first, second])
    record = call()
    composite.record(record)
    assert first.records == [record]
    assert second.records == [record]
    assert composite.tracers == (first, second)


def test_a_failing_tracer_is_logged_and_the_others_still_record() -> None:
    broken, working = Recording(fail=True), Recording()
    record = call()
    with capture_logs() as logs:
        CompositeTracer([broken, working]).record(record)
    assert working.records == [record]
    [line] = logs
    assert line["event"] == "tracer_record_failed"
    assert line["tracer"] == "Recording"
    assert line["trace_id"] == record.entry.trace_id
    assert line["exc_info"] is True


def test_flush_fans_out_and_swallows_failures() -> None:
    broken, working = Recording(fail=True), Recording()
    with capture_logs() as logs:
        CompositeTracer((broken, working)).flush()
    assert working.flushes == 1
    [line] = logs
    assert line["event"] == "tracer_flush_failed"
    assert line["tracer"] == "Recording"


def test_an_empty_composite_does_nothing() -> None:
    composite = CompositeTracer([])
    composite.record(call())
    composite.flush()
    assert composite.tracers == ()
