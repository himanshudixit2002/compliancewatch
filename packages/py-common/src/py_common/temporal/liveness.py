"""Worker liveness: the gauge ``temporal_worker_up{task_queue}``.

``running(task_queue)`` records that this process serves a task queue for as long as the block
runs. ``run_worker`` wraps its worker in it, and a process that runs several workers wraps each
one, so a combined worker reports one series per queue through the same instrument. At every
collection the gauge observes 1 for each queue in the registry and nothing for a queue that has
stopped, so the series ends when the worker does: the collector's Prometheus exporter drops it
five minutes later (``metric_expiration``), and the TemporalWorkerDown alert fires for a queue
seen in the last six hours that no longer reports.

The instrument comes from ``opentelemetry.metrics.get_meter`` and binds to whatever meter
provider the process installs (``py_common.telemetry.configure_telemetry``); with none installed
it records nothing. This package never imports ``py_common.telemetry``: that module pulls in
FastAPI and SQLAlchemy, and workflow and activity code, which imports ``py_common.temporal``,
must stay free of both (an import-linter contract holds it).
"""

import threading
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Meter, ObservableGauge, Observation

METRIC_NAME = "temporal_worker_up"
QUEUE_ATTRIBUTE = "task_queue"
DESCRIPTION = "1 for each Temporal task queue a worker in this process is serving"

_lock = threading.Lock()
_running: Counter[str] = Counter()


@contextmanager
def running(task_queue: str) -> Iterator[None]:
    """Report ``task_queue`` as served while the block runs. Two workers of one process on the
    same queue count separately; the queue stops reporting when the last one leaves."""
    if not task_queue.strip():
        raise ValueError("task_queue must not be blank")
    with _lock:
        _running[task_queue] += 1
    try:
        yield
    finally:
        with _lock:
            _running[task_queue] -= 1
            if _running[task_queue] <= 0:
                del _running[task_queue]


def running_queues() -> tuple[str, ...]:
    """The task queues this process serves now, sorted."""
    with _lock:
        return tuple(sorted(_running))


def observe(_options: CallbackOptions) -> Iterable[Observation]:
    """The gauge's callback: 1 per running queue."""
    return [Observation(1, {QUEUE_ATTRIBUTE: queue}) for queue in running_queues()]


def register(meter: Meter) -> ObservableGauge:
    """Create the gauge on ``meter``. The module does this once on the global meter; tests call
    it with a meter of their own to read what the registry reports.

    No unit is set: the collector's Prometheus exporter appends a unit suffix to the name
    (``_ratio`` for ``1``), and the alert rules query ``temporal_worker_up`` as it is.
    """
    return meter.create_observable_gauge(METRIC_NAME, callbacks=[observe], description=DESCRIPTION)


GAUGE = register(metrics.get_meter("py_common.temporal.liveness"))
"""The one instrument of the process, shared by every worker it runs."""
