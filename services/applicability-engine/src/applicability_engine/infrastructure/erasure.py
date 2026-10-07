"""The applicability engine's part of a tenant's erasure (group ``applicability-engine.erasure``;
``py_common.erasure``).

``PostgresEngineEraser.erase`` runs in the consumer's transaction with ``app.tenant_id`` and
``app.erasure`` set: row-level security admits the tenant's rows only, and the append-only guard
of ``applicability_decision`` lets its DELETE through. It deletes the tenant's review items
(they reference the decisions), its decisions, its entries in ``business_directory`` (a routing
directory every session may read and only the tenant's own setting may write: these are the
tenant's rows), its idempotency keys and its published or dead events in ``outbox_event``.

It keeps ``fanout_run`` and ``fanout_hold``: rule-level runs of a published version over every
tenant, with counters only and no tenant reference.

A profile.updated or rule event still in flight when the engine erased the tenant can write a
directory entry or a decision again; the staging drill checks for it, and
``identity-admin erasure resend`` erases again (docs/runbooks/data-requests.md).

``MemoryEngineEraser`` does the same to a ``MemoryStore`` (tests and the in-process journey).
"""

from typing import Final

from applicability_engine.infrastructure.memory import MemoryStore
from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, TenantDataErased, retained
from domain_kernel.ids import TenantId
from py_common.audit import MemoryAuditSink
from py_common.erasure import (
    OUTBOX_RETAINED,
    PostgresTenantEraser,
    begin_erasure,
    delete_rows,
    prune_outbox,
)

TABLES: Final = (
    "review_item",
    "applicability_decision",
    "business_directory",
    "idempotency_key",
)
"""The tenant's tables, in the order their rows go."""
RETAINED: Final = (
    *retained(
        (
            "fanout_run",
            "rule-level runs of a published version over every tenant: counters, no tenant "
            "reference",
        ),
        ("fanout_hold", "the global hold of the fan-outs, no tenant reference"),
    ),
    OUTBOX_RETAINED,
)


class PostgresEngineEraser(PostgresTenantEraser):
    def erase(self, tenant_id: TenantId) -> Erased:
        begin_erasure(self.connection, tenant_id)
        tables = {table: delete_rows(self.connection, table, tenant_id) for table in TABLES}
        tables["outbox_event"] = prune_outbox(self.connection, tenant_id)
        return Erased(tables, RETAINED)


class MemoryEngineEraser:
    """The eraser on a memory store, under its lock."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def erase(self, tenant_id: TenantId) -> Erased:
        store = self._store
        with store.lock:
            reviews = [key for key, item in store.reviews.items() if item.tenant_id == tenant_id]
            for review_id in reviews:
                del store.reviews[review_id]
            decisions = [key for key, d in store.decisions.items() if d.tenant_id == tenant_id]
            for decision_id in decisions:
                del store.decisions[decision_id]
            entries = [key for key, e in store.directory.items() if e.tenant_id == tenant_id]
            for business_id in entries:
                del store.directory[business_id]
        return Erased(
            {
                "review_item": len(reviews),
                "applicability_decision": len(decisions),
                "business_directory": len(entries),
                "idempotency_key": 0,
                "outbox_event": 0,
            },
            RETAINED,
        )

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        store = self._store
        with store.lock:
            store.events.append(event)
            sink = MemoryAuditSink(store.audit, tenant_id=event.tenant_id)
            sink.write(entry)
            sink.commit()
