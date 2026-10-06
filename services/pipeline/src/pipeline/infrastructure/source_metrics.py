"""OpenTelemetry gauges of each source's freshness, read by the SourceStale alert
(``docs/runbooks/source-stale.md``).

- ``pipeline_source_freshness_seconds{source}``: seconds since a crawl last listed the source,
  or since it was added when none has (``schedule.staleness_age``);
- ``pipeline_source_cadence_seconds{source}``: the source's cadence.

Only the sources the schedule crawls (enabled and not paused) are reported, so a paused source
pages nobody. Both gauges are observable and share one reading of the store, kept for
``CACHE_SECONDS``; a failed read is logged and cached like a result, and the gauges report
nothing until the next one, so the alert sees a gap rather than a false age. The app registers
them only while crawling is on (``CW_PIPELINE_CRAWL_ENABLED``): with crawling off every source
would read stale. The names carry no unit, which the collector's Prometheus exporter would add
to them.
"""

import threading
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime

from opentelemetry.metrics import CallbackOptions, Meter, Observation

from pipeline.domain.schedule import staleness_age
from pipeline.domain.sources import Source
from py_common.logging import get_logger

FRESHNESS = "pipeline_source_freshness_seconds"
CADENCE = "pipeline_source_cadence_seconds"
CACHE_SECONDS = 30.0
SOURCE_LABEL = "source"

log = get_logger(__name__)


class SourceFreshnessGauges:
    """The callbacks of both gauges over one cached reading of the sources."""

    def __init__(
        self,
        read: Callable[[], Sequence[Source]],
        clock: Callable[[], datetime],
        *,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._read = read
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._sources: Sequence[Source] | None = None

    def sources(self) -> Sequence[Source] | None:
        """The crawled sources as last read, read again once the reading is ``cache_seconds``
        old; None after a failed read."""
        now = self._clock()
        with self._lock:
            if self._read_at is not None and (
                (now - self._read_at).total_seconds() < self._cache_seconds
            ):
                return self._sources
            self._read_at = now
            try:
                self._sources = [source for source in self._read() if source.crawlable]
            except Exception as exc:
                self._sources = None
                log.warning("source_metrics.read_failed", error=f"{type(exc).__name__}: {exc}")
            return self._sources

    def freshness(self, _: CallbackOptions) -> Iterable[Observation]:
        sources = self.sources()
        if sources is None:
            return []
        now = self._clock()
        return [
            Observation(
                round(staleness_age(source, now).total_seconds()), {SOURCE_LABEL: source.key}
            )
            for source in sources
        ]

    def cadence(self, _: CallbackOptions) -> Iterable[Observation]:
        sources = self.sources()
        if sources is None:
            return []
        return [
            Observation(round(source.cadence.total_seconds()), {SOURCE_LABEL: source.key})
            for source in sources
        ]


def register_source_gauges(
    read: Callable[[], Sequence[Source]], clock: Callable[[], datetime], meter: Meter
) -> SourceFreshnessGauges:
    """Register both gauges on ``meter``; the composition root calls this only when telemetry
    and crawling are on."""
    gauges = SourceFreshnessGauges(read, clock)
    meter.create_observable_gauge(
        FRESHNESS,
        callbacks=[gauges.freshness],
        description="Seconds since a crawl last listed the source (since it was added, before)",
    )
    meter.create_observable_gauge(
        CADENCE,
        callbacks=[gauges.cadence],
        description="Seconds between the crawls the schedule starts of the source",
    )
    return gauges
