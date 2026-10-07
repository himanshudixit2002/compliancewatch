"""The rulebook's part of a tenant's erasure (group ``rulebook.erasure``; ``py_common.erasure``).

The rulebook holds regulatory data, the same for every tenant: documents, clauses, rules and
their versions, citations, candidates and the review of all of them. None of its tables has a
tenant column or a reference to a tenant's rows today, so there is nothing to delete and no
tenant reference to null: the eraser deletes nothing, lists what it keeps and why, and answers
``tenant.data.erased`` (service rulebook) with an empty ``tables``, so the deletion request can
complete. When a table gains a tenant reference (error reports, M3-7), its erasure nulls it here.

The reviewers and approvers the rulebook names are the regulatory team's users, of the internal
tenant, which is never erased.

``PostgresRulebookEraser`` writes the answer to the rulebook's outbox and the audit entry on the
consumer's connection; ``MemoryRulebookEraser`` does the same to a ``MemoryKnowledgeStore``'s
audit log and a list of its own (tests and the in-process journey).
"""

from typing import Final

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, TenantDataErased, retained
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.erasure import OUTBOX_RETAINED, PostgresTenantEraser, begin_erasure
from rulebook.infrastructure.memory import MemoryKnowledgeStore

REGULATORY = "regulatory data of no tenant"
RETAINED: Final = (
    *retained(
        ("document", f"{REGULATORY}: the published notifications and circulars"),
        ("rule_version", f"{REGULATORY}: the rules every tenant's obligations come from"),
        ("rule_version_decision", f"{REGULATORY}: the regulatory team's review of each version"),
        ("rule_candidate", f"{REGULATORY}: candidates extracted from public documents"),
        ("review_task", f"{REGULATORY}: the regulatory team's review queue"),
        ("entity_review", f"{REGULATORY}: the review of the entities the documents name"),
        ("relation_candidate", f"{REGULATORY}: proposed relations between rules"),
    ),
    OUTBOX_RETAINED,
)


def erased() -> Erased:
    return Erased({}, RETAINED)


class PostgresRulebookEraser(PostgresTenantEraser):
    def erase(self, tenant_id: TenantId) -> Erased:
        begin_erasure(self.connection, tenant_id)
        return erased()


class MemoryRulebookEraser:
    """The eraser on a memory store: the audit entry in the store's log, the answer in
    ``outbox``."""

    def __init__(self, store: MemoryKnowledgeStore, outbox: list[DomainEvent]) -> None:
        self._store = store
        self._outbox = outbox

    def erase(self, tenant_id: TenantId) -> Erased:
        return erased()

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        self._store.write_audit(entry)
        self._outbox.append(event)
