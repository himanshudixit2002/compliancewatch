"""Idempotency keys with 24 hour replay for creating routes.

- ``store``: the request fingerprint, the outcomes of ``begin`` and the ``IdempotencyStore`` and
  ``IdempotencyRecorder`` protocols.
- ``memory``: ``MemoryIdempotencyStore`` for tests, demos and memory mode.
- ``errors``: the 428, 422 and 409 problems, mapped for every service by py-common.
- ``sqlalchemy``: ``SqlAlchemyIdempotencyStore`` (its own short transactions) and
  ``SqlAlchemyIdempotencyRecorder`` (inside the caller's transaction) on Postgres.
- ``schema``: the ``idempotency_key`` table; ``create_idempotency_table(op)`` for a migration.
- ``fastapi``: the ``IdempotencyKey`` dependency and ``run_idempotent``.
- ``python -m py_common.idempotency purge`` deletes expired keys, for a daily schedule.

This module exports only the parts without FastAPI or SQLAlchemy, so importing it (as
``py_common.problems`` does for the errors) loads neither; import ``fastapi``, ``sqlalchemy`` and
``schema`` from their own modules.
"""

from py_common.idempotency.errors import (
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
    IdempotencyRequestInFlightError,
)
from py_common.idempotency.memory import MemoryIdempotencyStore
from py_common.idempotency.store import (
    IN_FLIGHT_LEASE,
    REPLAY_WINDOW,
    IdempotencyRecorder,
    IdempotencyRequest,
    IdempotencyStore,
    InFlight,
    Outcome,
    Replay,
    Reused,
    Started,
    StoredResponse,
    fingerprint,
)

__all__ = [
    "IN_FLIGHT_LEASE",
    "REPLAY_WINDOW",
    "IdempotencyKeyRequiredError",
    "IdempotencyKeyReusedError",
    "IdempotencyRecorder",
    "IdempotencyRequest",
    "IdempotencyRequestInFlightError",
    "IdempotencyStore",
    "InFlight",
    "MemoryIdempotencyStore",
    "Outcome",
    "Replay",
    "Reused",
    "Started",
    "StoredResponse",
    "fingerprint",
]
