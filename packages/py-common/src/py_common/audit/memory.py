"""The memory twin of ``audit.event``, for memory stores and tests.

A memory unit of work exposes a ``MemoryAuditSink`` as its ``audit``. Entries wait in
``pending`` until the unit commits them into the store's log, and a unit that fails drops them
(``rollback``), as a rolled back transaction drops its rows. The sink refuses what the table
refuses: a second entry with an id already stored, and, as row-level security does, an entry of
a tenant other than the unit's; a unit of no tenant writes only entries of no tenant. It stores
what the table stores: the entry masked for personal identifiers (``masking.masked_entry``).
"""

from domain_kernel.audit import AuditEntry
from domain_kernel.ids import TenantId
from py_common.audit.masking import masked_entry


class MemoryAuditSink:
    """``AuditSink`` for one unit of work of ``tenant_id``, over a log the store keeps."""

    def __init__(self, log: list[AuditEntry], *, tenant_id: TenantId | None = None) -> None:
        self._log = log
        self._tenant_id = tenant_id
        self.pending: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        if entry.tenant_id is not None and entry.tenant_id != self._tenant_id:
            raise ValueError(f"audit entry {entry.entry_id} belongs to another tenant")
        if any(stored.entry_id == entry.entry_id for stored in (*self._log, *self.pending)):
            raise ValueError(f"audit entry {entry.entry_id} is stored already")
        self.pending.append(masked_entry(entry))

    def commit(self) -> None:
        """Add the pending entries to the log, in the order they were written."""
        self._log.extend(self.pending)
        self.pending.clear()

    def rollback(self) -> None:
        """Drop the pending entries."""
        self.pending.clear()
