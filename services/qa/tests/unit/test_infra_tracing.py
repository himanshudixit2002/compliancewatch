"""The OpenTelemetry tracer: names, attributes, nesting and failures, on the SDK's in-memory
exporter."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from qa import __version__
from qa.infrastructure.tracing import OtelTracer


@pytest.fixture
def exported() -> tuple[OtelTracer, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OtelTracer(provider), exporter


def test_spans_nest_and_carry_their_attributes(
    exported: tuple[OtelTracer, InMemorySpanExporter],
) -> None:
    tracer, exporter = exported
    with tracer.span("qa.ask", {"qa.question_id": "q1"}) as ask:
        with tracer.span("qa.solve.step", {"qa.step.id": "s1"}) as step:
            step.set_attribute("qa.step.items", 2)
        ask.set_attribute("qa.layer", "kag")
    inner, outer = exporter.get_finished_spans()
    assert (outer.name, dict(outer.attributes or {})) == (
        "qa.ask",
        {"qa.question_id": "q1", "qa.layer": "kag"},
    )
    assert dict(inner.attributes or {}) == {"qa.step.id": "s1", "qa.step.items": 2}
    assert inner.parent is not None
    assert inner.parent.span_id == outer.context.span_id
    assert outer.instrumentation_scope is not None
    assert (outer.instrumentation_scope.name, outer.instrumentation_scope.version) == (
        "qa",
        __version__,
    )


def test_an_exception_marks_the_span_failed(
    exported: tuple[OtelTracer, InMemorySpanExporter],
) -> None:
    tracer, exporter = exported
    with pytest.raises(RuntimeError), tracer.span("qa.layer"):
        raise RuntimeError("step failed")
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert [event.name for event in span.events] == ["exception"]


def test_without_a_provider_the_global_one_is_used() -> None:
    with OtelTracer().span("qa.ask") as span:
        span.set_attribute("qa.layer", "hybrid")
