"""Fan one call out to several tracers; a failing tracer never stops the others."""

from collections.abc import Iterable

from llm_gateway.domain.tracing import CallRecord, Tracer
from py_common.logging import get_logger

log = get_logger(__name__)


class CompositeTracer:
    def __init__(self, tracers: Iterable[Tracer]) -> None:
        self._tracers: tuple[Tracer, ...] = tuple(tracers)

    @property
    def tracers(self) -> tuple[Tracer, ...]:
        return self._tracers

    def record(self, call: CallRecord) -> None:
        for tracer in self._tracers:
            try:
                tracer.record(call)
            except Exception:
                log.exception(
                    "tracer_record_failed",
                    tracer=type(tracer).__name__,
                    trace_id=call.entry.trace_id,
                )

    def flush(self) -> None:
        for tracer in self._tracers:
            try:
                tracer.flush()
            except Exception:
                log.exception("tracer_flush_failed", tracer=type(tracer).__name__)
