"""OpenTelemetry gauges over the two review queues an analyst works through.

- The entity review queue, read by the EntityReviewQueueStale and EntityReviewQueueBacklog
  alerts (``docs/runbooks/entity-review-queue.md``): open items by entity type and the age of
  the oldest one.
- The review tasks, read by the RuleReviewQueueStale alert
  (``docs/runbooks/rule-review-queue.md``): ``rulebook_review_tasks_open{regulator}``, the tasks
  not decided yet (claimed or not) for every regulator that has had a task, zero when none
  waits, and ``rulebook_review_task_oldest_open_age_seconds``, how long the oldest of them has
  waited since it was opened.

Every gauge is observable: the SDK calls it back on every export. The gauges of one queue share
one reading of it, kept for ``CACHE_SECONDS`` so an export every 15 seconds is not a query every
15 seconds. A failed read is logged and cached like a result, and the gauges report nothing
until the next read, so the alerts see a gap rather than a false zero. The names carry no unit:
the collector's Prometheus exporter would add a suffix to the name.
"""

import threading
from collections.abc import Callable, Iterable
from datetime import datetime

from opentelemetry.metrics import CallbackOptions, Meter, Observation

from py_common.logging import get_logger
from rulebook.domain.review import ReviewQueueStats
from rulebook.domain.review_tasks import ReviewTaskStats

OPEN_ITEMS = "rulebook_entity_review_open_items"
OLDEST_OPEN_AGE = "rulebook_entity_review_oldest_open_age_seconds"
OPEN_TASKS = "rulebook_review_tasks_open"
OLDEST_TASK_AGE = "rulebook_review_task_oldest_open_age_seconds"
CACHE_SECONDS = 60.0

log = get_logger(__name__)


class ReviewQueueGauges:
    """The callbacks of both gauges over one cached reading of the queue."""

    def __init__(
        self,
        read: Callable[[], ReviewQueueStats],
        clock: Callable[[], datetime],
        *,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._read = read
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._stats: ReviewQueueStats | None = None

    def stats(self) -> ReviewQueueStats | None:
        """The cached reading, read again once it is ``cache_seconds`` old; None after a
        failed read."""
        now = self._clock()
        with self._lock:
            if self._read_at is not None and (
                (now - self._read_at).total_seconds() < self._cache_seconds
            ):
                return self._stats
            self._read_at = now
            try:
                self._stats = self._read()
            except Exception as exc:
                self._stats = None
                log.warning("review_metrics.read_failed", error=f"{type(exc).__name__}: {exc}")
            return self._stats

    def open_items(self, _: CallbackOptions) -> Iterable[Observation]:
        stats = self.stats()
        if stats is None:
            return []
        return [
            Observation(count, {"entity_type": entity_type.value})
            for entity_type, count in stats.counts().items()
        ]

    def oldest_open_age(self, _: CallbackOptions) -> Iterable[Observation]:
        stats = self.stats()
        if stats is None:
            return []
        return [Observation(stats.oldest_open_age_seconds(self._clock()))]


def register_review_queue_gauges(
    read: Callable[[], ReviewQueueStats], clock: Callable[[], datetime], meter: Meter
) -> ReviewQueueGauges:
    """Register both gauges on ``meter``; the composition root calls this only when telemetry
    is on."""
    gauges = ReviewQueueGauges(read, clock)
    meter.create_observable_gauge(
        OPEN_ITEMS,
        callbacks=[gauges.open_items],
        description="Open entity review items by entity type",
    )
    meter.create_observable_gauge(
        OLDEST_OPEN_AGE,
        callbacks=[gauges.oldest_open_age],
        description="Seconds the oldest open entity review item has waited",
    )
    return gauges


class ReviewTaskGauges:
    """The callbacks of the review task gauges over one cached reading of the queue."""

    def __init__(
        self,
        read: Callable[[], ReviewTaskStats],
        clock: Callable[[], datetime],
        *,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._read = read
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._stats: ReviewTaskStats | None = None

    def stats(self) -> ReviewTaskStats | None:
        """The cached reading, read again once it is ``cache_seconds`` old; None after a
        failed read."""
        now = self._clock()
        with self._lock:
            if self._read_at is not None and (
                (now - self._read_at).total_seconds() < self._cache_seconds
            ):
                return self._stats
            self._read_at = now
            try:
                self._stats = self._read()
            except Exception as exc:
                self._stats = None
                log.warning(
                    "review_metrics.tasks_read_failed", error=f"{type(exc).__name__}: {exc}"
                )
            return self._stats

    def open_tasks(self, _: CallbackOptions) -> Iterable[Observation]:
        stats = self.stats()
        if stats is None:
            return []
        return [
            Observation(count, {"regulator": regulator})
            for regulator, count in stats.open_by_regulator().items()
        ]

    def oldest_open_age(self, _: CallbackOptions) -> Iterable[Observation]:
        stats = self.stats()
        if stats is None:
            return []
        return [Observation(stats.oldest_open_age_seconds(self._clock()))]


def register_review_task_gauges(
    read: Callable[[], ReviewTaskStats], clock: Callable[[], datetime], meter: Meter
) -> ReviewTaskGauges:
    """Register the review task gauges on ``meter``; the composition root calls this only when
    telemetry is on."""
    gauges = ReviewTaskGauges(read, clock)
    meter.create_observable_gauge(
        OPEN_TASKS,
        callbacks=[gauges.open_tasks],
        description="Review tasks not decided yet, claimed or not, by regulator",
    )
    meter.create_observable_gauge(
        OLDEST_TASK_AGE,
        callbacks=[gauges.oldest_open_age],
        description="Seconds the oldest review task not decided yet has waited",
    )
    return gauges
