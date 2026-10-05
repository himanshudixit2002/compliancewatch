"""The audit log (guide sections 9, 15 and 16): one ``audit.event`` row per audited action,
written in the transaction of the action it records, never changed and kept seven years.

- ``context``: ``audit_actor(service, principal)``, the actor the request's verified principal
  names (a user with their roles, or a service client), else the system as ``system:<service>``;
  ``current_correlation_id()``, the correlation id ``py_common.request_context`` bound for the
  request.
- ``memory``: ``MemoryAuditSink``, the twin a memory store's unit of work writes entries to.
- ``schema``: the ``audit.event`` table; ``create_audit_table(op)`` and ``drop_audit_table(op)``
  for identity's migration, which owns it.
- ``writer``: ``AuditWriter.write(connection, entry)`` inserts the row in the caller's
  transaction, as ``OutboxWriter`` does for events; ``PostgresAuditSink`` is the kernel's
  ``AuditSink`` on one connection, a unit of work's ``audit``.
- ``testing``: entries with synthetic values, the table on a test database, the rows read back.

The entry itself, its actor and the ``AuditSink`` protocol are the kernel's
(``domain_kernel.audit``). This module exports only the parts without SQLAlchemy, so an
application layer may import it (an import-linter contract keeps it so); import ``schema``,
``writer`` and ``testing`` from their own modules.
"""

from py_common.audit.context import CORRELATION_FIELD, audit_actor, current_correlation_id
from py_common.audit.memory import MemoryAuditSink

__all__ = ["CORRELATION_FIELD", "MemoryAuditSink", "audit_actor", "current_correlation_id"]
