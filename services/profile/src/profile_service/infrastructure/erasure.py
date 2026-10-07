"""Profile's part of a tenant's erasure (group ``profile.erasure``; ``py_common.erasure``).

``PostgresProfileEraser.erase`` runs in the consumer's transaction with ``app.tenant_id`` and
``app.erasure`` set, so row-level security admits the tenant's rows only. It deletes, in the
order of the foreign keys, ``profile_version``, ``profile_attribute`` and ``review_task`` (each
references its node), then ``profile_node`` (a node's parent goes in the same statement), then
the tenant's idempotency keys and its published or dead events in ``outbox_event``, and writes the
erased marker with its answer (``erased_tenant``), after which the profile's routes answer the
tenant 410. Every profile table is the tenant's under row-level security; only ``outbox_event``
keeps the tenant's pending events for the relay, and ``erased_tenant`` the marker. The
not-applicable answers ``CW_PROFILE_EVAL_CASES_PATH`` appends to a file outside the database are
not erased here: that file is a local seed for the eval set, and the runbook has the operator
remove the tenant's lines from it where it is set.

``MemoryProfileEraser`` does the same to a ``MemoryStore`` (tests and the in-process journey),
the eval-case seeds it keeps in memory included.
"""

from typing import Final

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, TenantDataErased
from domain_kernel.ids import TenantId
from profile_service.infrastructure.memory import MemoryStore
from py_common.audit import MemoryAuditSink
from py_common.erasure import (
    ERASED_RETAINED,
    OUTBOX_RETAINED,
    PostgresTenantEraser,
    begin_erasure,
    delete_rows,
    prune_outbox,
)
from py_common.idempotency import MemoryIdempotencyStore

TABLES: Final = (
    "profile_version",
    "profile_attribute",
    "review_task",
    "profile_node",
    "idempotency_key",
)
"""The tenant's tables, in the order their rows go."""
RETAINED: Final = (ERASED_RETAINED, OUTBOX_RETAINED)


class PostgresProfileEraser(PostgresTenantEraser):
    def erase(self, tenant_id: TenantId) -> Erased:
        begin_erasure(self.connection, tenant_id)
        tables = {table: delete_rows(self.connection, table, tenant_id) for table in TABLES}
        tables["outbox_event"] = prune_outbox(self.connection, tenant_id)
        return Erased(tables, RETAINED)


class MemoryProfileEraser:
    """The eraser on a memory store, under its lock."""

    def __init__(
        self, store: MemoryStore, *, idempotency: MemoryIdempotencyStore | None = None
    ) -> None:
        self._store = store
        self._idempotency = idempotency

    def erase(self, tenant_id: TenantId) -> Erased:
        store = self._store
        with store.lock:
            versions = [key for key, v in store.versions.items() if v.tenant_id == tenant_id]
            for key in versions:
                del store.versions[key]
            nodes = [node for node in store.nodes.values() if node.tenant_id == tenant_id]
            attributes = sum(len(node.attributes) for node in nodes)
            tasks = [
                task_id for task_id, task in store.tasks.items() if task.tenant_id == tenant_id
            ]
            for task_id in tasks:
                del store.tasks[task_id]
            for node in nodes:
                del store.nodes[node.id]
            kept = [case for case in store.eval_cases if case.get("tenant_id") != str(tenant_id)]
            store.eval_cases[:] = kept
        return Erased(
            {
                "profile_version": len(versions),
                "profile_attribute": attributes,
                "review_task": len(tasks),
                "profile_node": len(nodes),
                "idempotency_key": _forget(self._idempotency, tenant_id),
                "outbox_event": 0,
            },
            RETAINED,
        )

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        store = self._store
        with store.lock:
            store.events.append(event)
            store.erased.mark(event)
            _audit(store, entry)

    def write_audit(self, entry: AuditEntry) -> None:
        with self._store.lock:
            _audit(self._store, entry)


def _audit(store: MemoryStore, entry: AuditEntry) -> None:
    sink = MemoryAuditSink(store.audit, tenant_id=entry.tenant_id)
    sink.write(entry)
    sink.commit()


def _forget(idempotency: MemoryIdempotencyStore | None, tenant_id: TenantId) -> int:
    """The tenant's idempotency keys dropped from the service's memory store of them, when the
    eraser was given it."""
    return 0 if idempotency is None else idempotency.forget(tenant_id)
