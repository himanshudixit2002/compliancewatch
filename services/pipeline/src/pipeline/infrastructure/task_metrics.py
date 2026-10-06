"""The OpenTelemetry gauges of the open pipeline tasks, read by the ParseFailureQueueHigh and
TriageQueueStale alerts (``docs/runbooks/parse-failures.md``, ``docs/runbooks/pipeline-triage.md``).

- ``pipeline_open_tasks{kind}``: how many tasks of each kind are open; ``manual_parse`` counts the
  stored documents no parser reads, which wait for an analyst's transcript and are not
  registered meanwhile, and ``triage`` the documents held for an analyst's decision.
- ``pipeline_task_oldest_open_age_seconds{kind}``: how long the oldest open task of each kind has
  waited since it opened.

Every kind is reported, zero when none is open, so the alerts read a value rather than an
absence. The gauges are observable and share one reading of the store, taken at most every
``CACHE_SECONDS``; the age is counted from it to the moment of the export. A failed read is
logged and cached like a result, and the gauges report nothing until the next one, so the alerts
see a gap rather than a false zero. The app registers them whenever telemetry is on. The names
carry no unit, which the collector's Prometheus exporter would add to them.
"""

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from opentelemetry.metrics import CallbackOptions, Meter, Observation

from pipeline.domain.tasks import TaskKind
from py_common.logging import get_logger

OPEN_TASKS = "pipeline_open_tasks"
OLDEST_OPEN_AGE = "pipeline_task_oldest_open_age_seconds"
CACHE_SECONDS = 30.0
KIND_LABEL = "kind"

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OpenTasks:
    """One reading of the open tasks: how many of each kind, and when the oldest of each kind
    was opened; a kind with none open is absent from both."""

    counts: Mapping[TaskKind, int]
    oldest: Mapping[TaskKind, datetime] = field(default_factory=dict)


class OpenTaskGauge:
    """The callbacks of both gauges over one cached reading of the open tasks."""

    def __init__(
        self,
        read: Callable[[], OpenTasks],
        clock: Callable[[], datetime],
        *,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._read = read
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._reading: OpenTasks | None = None

    def reading(self) -> OpenTasks | None:
        """The open tasks as last read, every kind counted, read again once the reading is
        ``cache_seconds`` old; None after a failed read."""
        now = self._clock()
        with self._lock:
            if self._read_at is not None and (
                (now - self._read_at).total_seconds() < self._cache_seconds
            ):
                return self._reading
            self._read_at = now
            try:
                read = self._read()
                self._reading = OpenTasks(
                    counts={kind: read.counts.get(kind, 0) for kind in TaskKind},
                    oldest=dict(read.oldest),
                )
            except Exception as exc:
                self._reading = None
                log.warning("task_metrics.read_failed", error=f"{type(exc).__name__}: {exc}")
            return self._reading

    def counts(self) -> Mapping[TaskKind, int] | None:
        """The open tasks of each kind as last read; None after a failed read."""
        reading = self.reading()
        return None if reading is None else reading.counts

    def ages(self) -> Mapping[TaskKind, float] | None:
        """How many seconds the oldest open task of each kind has waited by now, zero for a kind
        with none open; None after a failed read."""
        reading = self.reading()
        if reading is None:
            return None
        now = self._clock()
        ages: dict[TaskKind, float] = {}
        for kind in TaskKind:
            opened = reading.oldest.get(kind)
            ages[kind] = 0.0 if opened is None else max(0.0, (now - opened).total_seconds())
        return ages

    def observe(self, _: CallbackOptions) -> Iterable[Observation]:
        counts = self.counts()
        if counts is None:
            return []
        return [Observation(count, {KIND_LABEL: kind.value}) for kind, count in counts.items()]

    def observe_ages(self, _: CallbackOptions) -> Iterable[Observation]:
        ages = self.ages()
        if ages is None:
            return []
        return [Observation(age, {KIND_LABEL: kind.value}) for kind, age in ages.items()]


def register_task_gauges(
    read: Callable[[], OpenTasks], clock: Callable[[], datetime], meter: Meter
) -> OpenTaskGauge:
    """Register both gauges on ``meter``; the composition root calls this when telemetry is on."""
    gauge = OpenTaskGauge(read, clock)
    meter.create_observable_gauge(
        OPEN_TASKS,
        callbacks=[gauge.observe],
        description=(
            "Open pipeline tasks by kind: manual_parse counts the documents no parser reads, "
            "waiting for a transcript; triage the documents held for an analyst's decision"
        ),
    )
    meter.create_observable_gauge(
        OLDEST_OPEN_AGE,
        callbacks=[gauge.observe_ages],
        description="Seconds the oldest open pipeline task of each kind has waited, 0 for none",
    )
    return gauge
