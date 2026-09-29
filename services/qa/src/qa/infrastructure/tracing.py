"""The ``Tracer`` port on OpenTelemetry.

Spans go to the tracer provider passed in, or to the global one that py-common installs when
``CW_OTEL_ENDPOINT`` is set (without it every span is a no-op). A span is the current span
while its block runs, so the solver's step spans nest under the layer span and the request's
server span. An exception leaving the block is recorded and sets the span's status to ERROR.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from opentelemetry import trace

from qa import __version__
from qa.domain.ports import AttributeValue

INSTRUMENTATION: str = "qa"


class OtelTracer:
    def __init__(self, tracer_provider: trace.TracerProvider | None = None) -> None:
        self._tracer = trace.get_tracer(
            INSTRUMENTATION, __version__, tracer_provider=tracer_provider
        )

    @contextmanager
    def span(
        self, name: str, attributes: Mapping[str, AttributeValue] | None = None
    ) -> Iterator[trace.Span]:
        with self._tracer.start_as_current_span(
            name,
            attributes=dict(attributes or {}),
            record_exception=True,
            set_status_on_exception=True,
        ) as span:
            yield span
