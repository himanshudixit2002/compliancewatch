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
  honoured for every tenant), by this rule, for the preference of each address the tenant held
  (in its directory rows, or set by its user on the web, ``set_for_tenant_id``):

  - an opt-out (``opted_in`` false) stays: it is the record that the person asked us to stop,
    and it must outlive the tenant's account, or the next tenant to register the number would
    message someone who said no;
  - an opt-in stays while another tenant still holds the address: one of that tenant's
    recipients has it in the directory (read across every tenant), or that tenant's user set
    the preference (its ``set_for_tenant_id``);
  - any other opt-in is deleted with what it holds (the times the address last wrote);
  - a preference that stays keeps no reference to this tenant: its ``set_for_tenant_id`` is
    nulled when it named this tenant;
- the tenant's idempotency keys and its published or dead events in ``outbox_event``.

It then writes the erased marker with its answer (``erased_tenant``): from then on its routes
answer the tenant 410 and its consumer of the obligation events queues nothing for it.

It keeps ``suppression``: an address closed by a permanent bounce, a complaint or support holds
for every tenant that sends to it, and it names no tenant.

``MemoryNotificationEraser`` does the same to a ``MemoryStore`` (tests and the in-process
journey).
"""

from dataclasses import replace
from typing import Final
from uuid import UUID

from sqlalchemy import Connection, text

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, Retained, TenantDataErased, retained
from domain_kernel.ids import TenantId
from notification.infrastructure.memory import MemoryStore
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
KEPT_PREFERENCE_REASON: Final = (
    "opt-outs, kept as the record that the person asked to stop, which must outlive the account, "
    "and the consents of addresses another tenant still holds, honoured for every tenant; no "
    "reference to this tenant is kept"
)
TENANT_ADDRESSES_SQL: Final = (
    "SELECT DISTINCT channel, address FROM address_directory WHERE tenant_id = :tenant "
    "UNION SELECT channel, address FROM channel_preference WHERE set_for_tenant_id = :tenant"
)
PREFERENCE_SQL: Final = (
    "SELECT p.opted_in, p.set_for_tenant_id, EXISTS (SELECT 1 FROM address_directory d "
    "WHERE d.channel = p.channel AND d.address = p.address AND d.tenant_id <> :tenant) AS held "
    "FROM channel_preference p WHERE p.channel = :channel AND p.address = :address"
)
"""The address's preference, and whether another tenant's recipient holds the address in the
directory (which has no row-level security: every tenant's rows)."""


def retained_for(kept: int) -> tuple[Retained, ...]:
    """What the erasure keeps: the suppressions, the preferences when it kept any, the marker
    and the pending events."""
    found = list(SUPPRESSION_RETAINED)
    if kept:
        found.extend(retained(("channel_preference", KEPT_PREFERENCE_REASON)))
    return (*found, ERASED_RETAINED, OUTBOX_RETAINED)


def preference_stays(opted_in: bool, set_for: UUID | None, held: bool, tenant_id: TenantId) -> bool:
    """Whether a preference outlives the tenant's erasure: an opt-out always, an opt-in while
    another tenant still holds the address (in its directory, or by setting it)."""
    set_elsewhere = set_for is not None and set_for != tenant_id.value
    return not opted_in or held or set_elsewhere


class PostgresNotificationEraser(PostgresTenantEraser):
    def erase(self, tenant_id: TenantId) -> Erased:
        connection = self.connection
        begin_erasure(connection, tenant_id)
        addresses = [
            (row.channel, row.address)
            for row in connection.execute(text(TENANT_ADDRESSES_SQL), {"tenant": tenant_id.value})
        ]
        tables = {table: delete_rows(connection, table, tenant_id) for table in TABLES}
        changed, kept = _preferences(connection, tenant_id, addresses)
        tables["channel_preference"] = changed
        tables["idempotency_key"] = delete_rows(connection, "idempotency_key", tenant_id)
        tables["outbox_event"] = prune_outbox(connection, tenant_id)
        return Erased(tables, retained_for(kept))


def _preferences(
    connection: Connection, tenant_id: TenantId, addresses: list[tuple[str, str]]
) -> tuple[int, int]:
    """Delete the preferences that do not stay (``preference_stays``); null this tenant's
    reference on the rest. Answers (deleted or changed, kept)."""
    changed = kept = 0
    for channel, address in addresses:
        key = {"channel": channel, "address": address, "tenant": tenant_id.value}
        row = connection.execute(text(PREFERENCE_SQL), key).first()
        if row is None:
            continue
        if not preference_stays(
            bool(row.opted_in), row.set_for_tenant_id, bool(row.held), tenant_id
        ):
            result = connection.execute(
                text(
                    "DELETE FROM channel_preference WHERE channel = :channel AND address = :address"
                ),
                key,
            )
            changed += max(result.rowcount, 0)
            continue
        kept += 1
        result = connection.execute(
            text(
                "UPDATE channel_preference SET set_for_tenant_id = NULL WHERE channel = :channel "
                "AND address = :address AND set_for_tenant_id = :tenant"
            ),
            key,
        )
        changed += max(result.rowcount, 0)
    return changed, kept


class MemoryNotificationEraser:
    """The eraser on a memory store, under its lock, by the same rule."""

    def __init__(
        self, store: MemoryStore, *, idempotency: MemoryIdempotencyStore | None = None
    ) -> None:
        self._store = store
        self._idempotency = idempotency

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
            changed = kept = 0
            for address in addresses:
                held = any(
                    (key[0], key[1]) == address and key[2] != tenant_id for key in state.directory
                )
                pref = state.preferences.get(address)
                if pref is None:
                    continue
                set_for = None if pref.set_for_tenant is None else pref.set_for_tenant.value
                if not preference_stays(pref.opted_in, set_for, held, tenant_id):
                    del state.preferences[address]
                    state.inbound.pop(address, None)
                    changed += 1
                    continue
                kept += 1
                if pref.set_for_tenant == tenant_id:
                    state.preferences[address] = replace(pref, set_for_tenant=None)
                    changed += 1
        return Erased(
            {
                "work_index": len(work),
                "notification": len(notes),
                "recipient_address": address_rows,
                "recipient_business": business_rows,
                "recipient": len(recipients),
                "address_directory": len(mine),
                "channel_preference": changed,
                "idempotency_key": _forget(self._idempotency, tenant_id),
                "outbox_event": 0,
            },
            retained_for(kept),
        )

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        store = self._store
        with store.lock:
            store.sink.publish(event)
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
