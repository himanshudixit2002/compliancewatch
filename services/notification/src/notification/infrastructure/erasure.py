"""Notification's part of a tenant's erasure (group ``notification.erasure``;
``py_common.erasure``).

``PostgresNotificationEraser.erase`` runs in the consumer's transaction with ``app.tenant_id``
and ``app.erasure`` set, so row-level security admits the tenant's rows of its tenant tables. In
order it deletes:

- ``work_index`` (no row-level security: the dispatcher claims across tenants), the rows whose
  ``tenant_id`` is the tenant's: the work of its notifications;
- ``notification``, the tenant's notifications with their delivery receipts (the receipts are
  the notification's own sent, delivered, read and failed times and provider message id);
- ``recipient_address`` and ``recipient_business``, then ``recipient``;
- ``address_directory`` (no row-level security: routes an address to the tenants that
  registered it), the rows whose ``tenant_id`` is the tenant's;
- ``channel_preference`` (no row-level security and no tenant: consent per channel and address,
  honoured for every tenant), by this rule: the preference of an address the tenant held (in its
  directory rows, or set by its user on the web, ``set_for_tenant_id``) is deleted when no other
  tenant holds that address in the directory any more; when another tenant still holds it, the
  preference stays, and only its reference to this tenant (``set_for_tenant_id``) is nulled;
- the tenant's idempotency keys and its published or dead events in ``outbox_event``.

It keeps ``suppression``: an address closed by a permanent bounce, a complaint or support holds
for every tenant that sends to it, and it names no tenant.

``MemoryNotificationEraser`` does the same to a ``MemoryStore`` (tests and the in-process
journey).
"""

from dataclasses import replace
from typing import Final

from sqlalchemy import Connection, text

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, Retained, TenantDataErased, retained
from domain_kernel.ids import TenantId
from notification.infrastructure.memory import MemoryStore
from py_common.audit import MemoryAuditSink
from py_common.erasure import (
    OUTBOX_RETAINED,
    PostgresTenantEraser,
    begin_erasure,
    delete_rows,
    prune_outbox,
)

TABLES: Final = (
    "work_index",
    "notification",
    "recipient_address",
    "recipient_business",
    "recipient",
    "address_directory",
)
"""The tenant's rows by ``tenant_id``, in the order they go."""
SUPPRESSION_RETAINED: Final = retained(
    (
        "suppression",
        "addresses closed by a permanent bounce, a complaint or support hold for every tenant "
        "that sends to them; the table names no tenant",
    ),
)
SHARED_PREFERENCE_REASON: Final = (
    "the consent of an address another tenant still holds, honoured for every tenant; its "
    "reference to this tenant is removed"
)
TENANT_ADDRESSES_SQL: Final = (
    "SELECT DISTINCT channel, address FROM address_directory WHERE tenant_id = :tenant "
    "UNION SELECT channel, address FROM channel_preference WHERE set_for_tenant_id = :tenant"
)
HELD_ELSEWHERE_SQL: Final = (
    "SELECT 1 FROM address_directory WHERE channel = :channel AND address = :address LIMIT 1"
)


def retained_for(shared: int) -> tuple[Retained, ...]:
    """What the erasure keeps: the suppressions, the shared preferences when it kept any, and
    the pending events."""
    kept = list(SUPPRESSION_RETAINED)
    if shared:
        kept.extend(retained(("channel_preference", SHARED_PREFERENCE_REASON)))
    return (*kept, OUTBOX_RETAINED)


class PostgresNotificationEraser(PostgresTenantEraser):
    def erase(self, tenant_id: TenantId) -> Erased:
        connection = self.connection
        begin_erasure(connection, tenant_id)
        addresses = [
            (row.channel, row.address)
            for row in connection.execute(text(TENANT_ADDRESSES_SQL), {"tenant": tenant_id.value})
        ]
        tables = {table: delete_rows(connection, table, tenant_id) for table in TABLES}
        deleted, shared = _preferences(connection, tenant_id, addresses)
        tables["channel_preference"] = deleted
        tables["idempotency_key"] = delete_rows(connection, "idempotency_key", tenant_id)
        tables["outbox_event"] = prune_outbox(connection, tenant_id)
        return Erased(tables, retained_for(shared))


def _preferences(
    connection: Connection, tenant_id: TenantId, addresses: list[tuple[str, str]]
) -> tuple[int, int]:
    """Delete the preferences no other tenant's address holds; null this tenant's reference on
    the rest. Answers (deleted, kept)."""
    deleted = kept = 0
    for channel, address in addresses:
        key = {"channel": channel, "address": address}
        if connection.execute(text(HELD_ELSEWHERE_SQL), key).first() is None:
            result = connection.execute(
                text(
                    "DELETE FROM channel_preference WHERE channel = :channel AND address = :address"
                ),
                key,
            )
            deleted += max(result.rowcount, 0)
            continue
        result = connection.execute(
            text(
                "UPDATE channel_preference SET set_for_tenant_id = NULL WHERE channel = :channel "
                "AND address = :address AND set_for_tenant_id = :tenant"
            ),
            {**key, "tenant": tenant_id.value},
        )
        kept += 1 if result.rowcount else 0
    return deleted, kept


class MemoryNotificationEraser:
    """The eraser on a memory store, under its lock, by the same rule."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def erase(self, tenant_id: TenantId) -> Erased:
        store = self._store
        with store.lock:
            state = store.state
            mine = {key for key in state.directory if key[2] == tenant_id}
            addresses = {(key[0], key[1]) for key in mine} | {
                key for key, pref in state.preferences.items() if pref.set_for_tenant == tenant_id
            }
            work = [nid for nid, row in state.work.items() if row.entry.tenant_id == tenant_id]
            for nid in work:
                del state.work[nid]
            notes = [key for key, n in state.notifications.items() if n.tenant_id == tenant_id]
            for note in notes:
                del state.notifications[note]
            recipients = [key for key in state.recipients if key[0] == tenant_id]
            address_rows = sum(len(state.recipients[key].addresses) for key in recipients)
            business_rows = sum(len(state.recipients[key].businesses) for key in recipients)
            for key in recipients:
                del state.recipients[key]
            state.directory -= mine
            deleted = shared = 0
            for address in addresses:
                held = any((key[0], key[1]) == address for key in state.directory)
                pref = state.preferences.get(address)
                if pref is None:
                    continue
                if not held:
                    del state.preferences[address]
                    state.inbound.pop(address, None)
                    deleted += 1
                elif pref.set_for_tenant == tenant_id:
                    state.preferences[address] = replace(pref, set_for_tenant=None)
                    shared += 1
        return Erased(
            {
                "work_index": len(work),
                "notification": len(notes),
                "recipient_address": address_rows,
                "recipient_business": business_rows,
                "recipient": len(recipients),
                "address_directory": len(mine),
                "channel_preference": deleted,
                "idempotency_key": 0,
                "outbox_event": 0,
            },
            retained_for(shared),
        )

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        store = self._store
        with store.lock:
            store.sink.publish(event)
            sink = MemoryAuditSink(store.audit, tenant_id=event.tenant_id)
            sink.write(entry)
            sink.commit()
