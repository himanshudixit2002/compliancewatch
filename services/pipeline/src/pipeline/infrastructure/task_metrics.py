"""The OpenTelemetry gauge of the open pipeline tasks, read by the ParseFailureQueueHigh alert
(``docs/runbooks/parse-failures.md``).

``pipeline_open_tasks{kind}``: how many tasks of each kind are open; ``manual_parse`` counts the
stored documents no parser reads, which wait for an analyst's transcript and are not registered
meanwhile. Every kind is reported, zero when none is open, so the alert reads a count rather than
an absence. The gauge is observable and reads the store at most every ``CACHE_SECONDS``; a failed
read is logged and cached like a result, and the gauge reports nothing until the next one, so the
alert sees a gap rather than a false zero. The app registers it whenever telemetry is on. The
name carries no unit, which the collector's Prometheus exporter would add to it.
"""

import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime

from opentelemetry.metrics import CallbackOptions, Meter, Observation

from pipeline.domain.tasks import TaskKind
from py_common.logging import get_logger

OPEN_TASKS = "pipeline_open_tasks"
CACHE_SECONDS = 30.0
KIND_LABEL = "kind"

log = get_logger(__name__)


class OpenTaskGauge:
    """The gauge's callback over one cached reading of the open counts."""

    def __init__(
        self,
        read: Callable[[], Mapping[TaskKind, int]],
        clock: Callable[[], datetime],
        *,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._read = read
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._counts: Mapping[TaskKind, int] | None = None

    def counts(self) -> Mapping[TaskKind, int] | None:
        """The open tasks of each kind as last read, read again once the reading is
        ``cache_seconds`` old; None after a failed read."""
        now = self._clock()
        with self._lock:
            if self._read_at is not None and (
                (now - self._read_at).total_seconds() < self._cache_seconds
            ):
                return self._counts
            self._read_at = now
            try:
                read = self._read()
                self._counts = {kind: read.get(kind, 0) for kind in TaskKind}
            except Exception as exc:
                self._counts = None
                log.warning("task_metrics.read_failed", error=f"{type(exc).__name__}: {exc}")
            return self._counts

    def observe(self, _: CallbackOptions) -> Iterable[Observation]:
        counts = self.counts()
        if counts is None:
            return []
        return [Observation(count, {KIND_LABEL: kind.value}) for kind, count in counts.items()]


def register_task_gauge(
    read: Callable[[], Mapping[TaskKind, int]], clock: Callable[[], datetime], meter: Meter
) -> OpenTaskGauge:
    """Register the gauge on ``meter``; the composition root calls this when telemetry is on."""
    gauge = OpenTaskGauge(read, clock)
    meter.create_observable_gauge(
        OPEN_TASKS,
        callbacks=[gauge.observe],
        description=(
            "Open pipeline tasks by kind: manual_parse counts the documents no parser reads, "
            "waiting for a transcript"
        ),
    )
    return gauge
