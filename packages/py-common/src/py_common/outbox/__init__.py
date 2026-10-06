"""Transactional outbox (ADR-005): write events with the state change, relay them to Kafka,
consume them once.

- ``schema``: the ``outbox_event`` and ``processed_event`` tables and the alembic helpers a
  service calls from its own migration.
- ``writer``: ``OutboxWriter.write`` inserts the wire message in the caller's transaction.
- ``store``: the store protocols and their Postgres implementations.
- ``producer``: the producer protocol and the aiokafka adapter.
- ``relay``: claims pending rows, publishes them, retries with backoff, dead-letters after
  ``max_attempts`` (the row keeps when it went dead); ``python -m py_common.outbox`` runs it for
  one service schema.
- ``admin``: ``OutboxAdmin`` lists the dead rows, reads one and puts a dead row back to pending,
  on the caller's connection, for a service's admin routes.
- ``replay``: ``DeadLetters`` lists a dead-letter topic and sends one of its messages back to its
  origin; ``python -m py_common.outbox.replay`` (``make replay``) is its command line. Import it
  from its module: the package does not load it, so ``-m`` runs it cleanly.
- ``consumer``: ``IdempotentConsumer`` processes each event id once per consumer group and
  dead-letters what its handler cannot process.
- ``sync``: ``SyncProcessedStore`` and ``sync_handler`` run a handler written against a sync
  connection in the consumer's transaction, on a thread of its own; ``read_first_store`` and
  ``read_then_write`` run a handler that reads other services before it writes, with no
  transaction open while it reads; ``run_consumer`` runs one consumer group until a stop event.
"""

from py_common.outbox.admin import DeadKey, DeadRows, OutboxAdmin, OutboxRow, payload_summary
from py_common.outbox.consumer import ConsumerConfig, IdempotentConsumer, InboundRecord, Outcome
from py_common.outbox.producer import AiokafkaProducer, MessageProducer
from py_common.outbox.relay import OutboxRelay, RelayConfig, RelayStats, backoff_seconds
from py_common.outbox.schema import (
    create_outbox_table,
    create_processed_event_table,
    drop_outbox_table,
    drop_processed_event_table,
    outbox_event,
    processed_event,
)
from py_common.outbox.store import (
    ClaimedMessage,
    OutboxBatch,
    OutboxStore,
    PostgresOutboxStore,
    PostgresProcessedStore,
    PostgresUnitOfWork,
    ProcessedStore,
    UnitOfWork,
)
from py_common.outbox.sync import (
    SyncHandler,
    SyncProcessedStore,
    SyncUnit,
    read_first_store,
    read_then_write,
    run_consumer,
    sync_handler,
)
from py_common.outbox.writer import OutboxRecord, OutboxWriter

__all__ = [
    "AiokafkaProducer",
    "ClaimedMessage",
    "ConsumerConfig",
    "DeadKey",
    "DeadRows",
    "IdempotentConsumer",
    "InboundRecord",
    "MessageProducer",
    "OutboxAdmin",
    "OutboxBatch",
    "OutboxRecord",
    "OutboxRelay",
    "OutboxRow",
    "OutboxStore",
    "OutboxWriter",
    "Outcome",
    "PostgresOutboxStore",
    "PostgresProcessedStore",
    "PostgresUnitOfWork",
    "ProcessedStore",
    "RelayConfig",
    "RelayStats",
    "SyncHandler",
    "SyncProcessedStore",
    "SyncUnit",
    "UnitOfWork",
    "backoff_seconds",
    "create_outbox_table",
    "create_processed_event_table",
    "drop_outbox_table",
    "drop_processed_event_table",
    "outbox_event",
    "payload_summary",
    "processed_event",
    "read_first_store",
    "read_then_write",
    "run_consumer",
    "sync_handler",
]
