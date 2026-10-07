"""OpenTelemetry gauges over every tenant's open data requests, read by the DataRequestOverdue
alert (``docs/runbooks/data-requests.md``):

- ``identity_data_requests_open{kind}``: the requests not completed yet, by kind, zero when none;
- ``identity_data_requests_overdue``: how many of them are past their 30-day deadline.

The counts come from ``DataRequestDirectory`` (in Postgres the SECURITY DEFINER function
``identity.data_requests_open()``, which answers counts only). Both gauges are observable and
share one reading, kept for ``CACHE_SECONDS`` so an export every 15 seconds is not a query every
15 seconds. A failed read (the function not made yet, the database down) is logged and cached
like a result, and the gauges report nothing until the next read, so the alert sees a gap rather
than a false zero. The composition root registers them only when telemetry is on.
"""

import threading
from collections.abc import Callable, Iterable
from datetime import datetime

from opentelemetry.metrics import CallbackOptions, Meter, Observation

from identity.domain.data_requests import DataRequestDirectory, OpenRequests
from py_common.logging import get_logger

OPEN_REQUESTS = "identity_data_requests_open"
OVERDUE_REQUESTS = "identity_data_requests_overdue"
CACHE_SECONDS = 60.0

log = get_logger(__name__)


class DataRequestGauges:
    """The callbacks of both gauges over one cached reading of the directory."""

    def __init__(
        self,
        directory: DataRequestDirectory,
        clock: Callable[[], datetime],
        *,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._directory = directory
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._counts: list[OpenRequests] | None = None

    def counts(self) -> list[OpenRequests] | None:
        """The cached reading, read again once it is ``cache_seconds`` old; None after a failed
        read."""
        now = self._clock()
        with self._lock:
            if self._read_at is not None and (
                (now - self._read_at).total_seconds() < self._cache_seconds
            ):
                return self._counts
            self._read_at = now
            try:
                self._counts = self._directory.open_counts()
            except Exception as exc:
                self._counts = None
                log.warning(
                    "data_request_metrics.read_failed", error=f"{type(exc).__name__}: {exc}"
                )
            return self._counts

    def open_requests(self, _: CallbackOptions) -> Iterable[Observation]:
        counts = self.counts()
        if counts is None:
            return []
        return [Observation(entry.open, {"kind": entry.kind.value}) for entry in counts]

    def overdue_requests(self, _: CallbackOptions) -> Iterable[Observation]:
        counts = self.counts()
        if counts is None:
            return []
        return [Observation(sum(entry.overdue for entry in counts))]


def register_data_request_gauges(
    directory: DataRequestDirectory, clock: Callable[[], datetime], meter: Meter
) -> DataRequestGauges:
    """Register both gauges on ``meter``; the composition root calls this only when telemetry
    is on."""
    gauges = DataRequestGauges(directory, clock)
    meter.create_observable_gauge(
        OPEN_REQUESTS,
        callbacks=[gauges.open_requests],
        description="Data requests not completed yet, every tenant's, by kind",
    )
    meter.create_observable_gauge(
        OVERDUE_REQUESTS,
        callbacks=[gauges.overdue_requests],
        description="Data requests past their 30-day deadline and not completed",
    )
    return gauges
