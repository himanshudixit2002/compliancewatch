"""Obligation's part of a tenant's erasure (group ``obligation.erasure``; ``py_common.erasure``).

``PostgresObligationEraser.erase`` runs in the consumer's transaction with ``app.tenant_id`` and
``app.erasure`` set: row-level security admits the tenant's rows only, and the append-only guards
of ``obligation_change`` and ``obligation_comment`` let their DELETEs through. In the order of the
foreign keys it deletes the changes and the comments (both RESTRICT on their obligation), the
reminders, the obligations, the applied decisions, the tenant's entry in the ``obligation_tenant``
directory (a routing directory: any session reads the ids, a write needs the tenant's own
setting, so this is the tenant's one row), its idempotency keys and its published or dead
events in ``outbox_event``.

It keeps ``rule_version_ref``, the cache of the rule versions obligations come from: rule-level
data, the same for every tenant and holding no tenant reference.

``MemoryObligationEraser`` does the same to a ``MemoryStore`` (tests and the in-process
journey).
"""

from typing import Final

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, TenantDataErased, retained
from domain_kernel.ids import TenantId
from obligation.infrastructure.memory import MemoryStore
from py_common.audit import MemoryAuditSink
from py_common.erasure import (
    OUTBOX_RETAINED,
    PostgresTenantEraser,
    begin_erasure,
    delete_rows,
    prune_outbox,
)

TABLES: Final = (
    "obligation_change",
    "obligation_comment",
    "obligation_reminder",
    "obligation",
    "obligation_decision",
    "obligation_tenant",
    "idempotency_key",
)
"""The tenant's tables, in the order their rows go."""
RETAINED: Final = (
    *retained(
        (
            "rule_version_ref",
            "rule-level cache of the rule versions obligations come from, the same for every "
            "tenant, with no tenant reference",
        ),
    ),
    OUTBOX_RETAINED,
)


class PostgresObligationEraser(PostgresTenantEraser):
    def erase(self, tenant_id: TenantId) -> Erased:
        begin_erasure(self.connection, tenant_id)
        tables = {table: delete_rows(self.connection, table, tenant_id) for table in TABLES}
        tables["outbox_event"] = prune_outbox(self.connection, tenant_id)
        return Erased(tables, RETAINED)


class MemoryObligationEraser:
    """The eraser on a memory store, under its lock. The memory store keeps no directory and no
    idempotency keys of its own: it lists the tenants from the obligations."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def erase(self, tenant_id: TenantId) -> Erased:
        store = self._store
        with store.lock:
            changes = [c for c in store.changes if c.tenant_id != tenant_id]
            comments = [c for c in store.comments if c.tenant_id != tenant_id]
            reminders = [r for r in store.reminders if r.tenant_id != tenant_id]
            counted = {
                "obligation_change": len(store.changes) - len(changes),
                "obligation_comment": len(store.comments) - len(comments),
                "obligation_reminder": len(store.reminders) - len(reminders),
            }
            store.changes[:] = changes
            store.comments[:] = comments
            store.reminders[:] = reminders
            mine = [key for key, o in store.obligations.items() if o.tenant_id == tenant_id]
            for obligation_id in mine:
                del store.obligations[obligation_id]
            decisions = [key for key, d in store.decisions.items() if d.tenant_id == tenant_id]
            for key in decisions:
                del store.decisions[key]
        return Erased(
            {
                **counted,
                "obligation": len(mine),
                "obligation_decision": len(decisions),
                "obligation_tenant": int(bool(mine)),
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
