"""Temporal worker scaffold (ADR-004): one client, one worker bootstrap, one activity shape.

- ``client.connect(settings)``: a ``Client`` with the pydantic data converter and the
  OpenTelemetry tracing interceptor, so every workflow and activity is a span.
- ``activity.ActivityBase``: the template method every activity follows (validate, run, record),
  with its retry policy and timeouts declared on the class and a ``schedule`` helper for
  workflows.
- ``worker.run_worker(...)``: builds the worker from activity instances and workflow classes and
  runs it until SIGTERM, SIGINT or a stop event.
"""

from py_common.temporal.activity import ActivityBase, sleep_with_heartbeat
from py_common.temporal.client import connect
from py_common.temporal.worker import WorkerConfig, run_worker

__all__ = [
    "ActivityBase",
    "WorkerConfig",
    "connect",
    "run_worker",
    "sleep_with_heartbeat",
]
