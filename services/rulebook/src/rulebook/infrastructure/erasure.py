"""The rulebook's part of a tenant's erasure (group ``rulebook.erasure``; ``py_common.erasure``).

The rulebook holds regulatory data, the same for every tenant: documents, clauses, rules and
their versions, citations, candidates and the review of all of them. One table names a tenant:
``error_report_review``, the error reports a tenant's members made about their obligations, as
the regulatory team reviews them. The eraser nulls the tenant and empties the masked text of the
tenant's reviews and keeps each decision as a fact about the rule version (what the regulatory
team found wrong in a rule is not the tenant's data); it deletes nothing else, lists what it
keeps and why, writes its erased marker (``erased_tenant``) and answers ``tenant.data.erased``
(service rulebook) with the count of the reviews it pseudonymised, so the deletion request can
complete. The writers of the reviews check the marker: the intake consumer only marks an erased
tenant's reports processed, and a decision on an erased tenant's review emits nothing.

The reviewers and approvers the rulebook names are the regulatory team's users, of the internal
tenant, which is never erased.

``PostgresRulebookEraser`` writes the answer to the rulebook's outbox, the audit entry and the
marker on the consumer's connection; ``MemoryRulebookEraser`` does the same to a
``MemoryKnowledgeStore``'s audit log, a list and markers of its own (tests and the in-process
journey).
"""

from typing import Final

from sqlalchemy import update

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, TenantDataErased, retained
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.erasure import (
    ERASED_RETAINED,
    OUTBOX_RETAINED,
    MemoryErasedTenants,
    PostgresTenantEraser,
    begin_erasure,
)
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.infrastructure.models import ErrorReportReviewRow

REGULATORY = "regulatory data of no tenant"
ERROR_REPORTS: Final = "error_report_review"
"""The one table that names a tenant: its rows are pseudonymised, never deleted."""
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
    ERASED_RETAINED,
    OUTBOX_RETAINED,
)


def erased(reviews: int) -> Erased:
    """The answer: ``reviews`` rows of ``error_report_review`` pseudonymised, the rest kept."""
    return Erased({ERROR_REPORTS: reviews}, RETAINED)


class PostgresRulebookEraser(PostgresTenantEraser):
    def erase(self, tenant_id: TenantId) -> Erased:
        begin_erasure(self.connection, tenant_id)
        pseudonymised = self.connection.execute(
            update(ErrorReportReviewRow)
            .where(ErrorReportReviewRow.tenant_id == tenant_id.value)
            .values(tenant_id=None, description_masked="")
            .returning(ErrorReportReviewRow.id)
        )
        return erased(len(pseudonymised.all()))


class MemoryRulebookEraser:
    """The eraser on a memory store: the audit entry in the store's log, the answer in
    ``outbox``, the marker in ``erased``."""

    def __init__(
        self,
        store: MemoryKnowledgeStore,
        outbox: list[DomainEvent],
        erased: MemoryErasedTenants | None = None,
    ) -> None:
        self._store = store
        self._outbox = outbox
        self.erased = erased or MemoryErasedTenants()

    def erase(self, tenant_id: TenantId) -> Erased:
        return erased(self._store.erase_error_reviews(tenant_id))

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        self._store.write_audit(entry)
        self._outbox.append(event)
        self.erased.mark(event)

    def write_audit(self, entry: AuditEntry) -> None:
        self._store.write_audit(entry)
