"""Reading the audit log: who may read which rows, the query a page answers, and the document
one entry becomes.

Every service writes ``audit.event`` rows in the transaction of the action they record
(``py_common.audit``); identity owns the table and is the one service that reads it.

- ``AuditScope`` is what a reader may see. ``TENANT``: the rows of one tenant, for its owners, CA
  admins and compliance leads. ``REGULATORY``: the rows of no tenant (platform-wide actions: rule
  versions, entity reviews, relation candidates, review tasks, sources, raw documents, pipeline
  tasks, outbox requeues, fan-out runs and holds, dry runs, service clients) and the rows of the
  reader's own tenant (the internal tenant's users), for analysts, reviewers and admins.
  ``EXPORT``: every row, for ``identity-admin audit-export`` only. The store applies the scope
  twice: through the row-level security policies (``app.audit_scope``, identity migration 0006)
  and in the query itself, so a role that bypasses row-level security reads no more.
- ``AuditQuery`` filters by subject, action and a time range (``since`` inclusive, ``until``
  exclusive) and pages by the keyset ``AuditKey`` (``occurred_at``, ``id``), newest first; a
  page is at most ``MAX_PAGE`` entries.
- ``AuditReader`` is the port the Postgres and memory stores implement.
- ``entry_document(entry)`` is one entry as plain JSON: what the route answers and what the
  export writes, one line each.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from domain_kernel._validation import require_aware
from domain_kernel.audit import AuditEntry, AuditEntryId
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId

MAX_PAGE: Final = 200
"""The most entries one page answers."""


class AuditScope(StrEnum):
    TENANT = "tenant"
    REGULATORY = "regulatory"
    EXPORT = "export"


@dataclass(frozen=True, slots=True)
class AuditKey:
    """Where a page starts: after the entry at ``occurred_at`` with ``entry_id``, newest first."""

    occurred_at: datetime
    entry_id: AuditEntryId

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, "occurred_at")

    @classmethod
    def of(cls, entry: AuditEntry) -> "AuditKey":
        return cls(entry.occurred_at, entry.entry_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditQuery:
    """One page of the trail: the filters, the size, and where it starts (None: the newest)."""

    subject_type: str | None = None
    subject_id: str | None = None
    action: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50
    after: AuditKey | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_PAGE:
            raise InvariantViolationError(f"limit is 1 to {MAX_PAGE}, got {self.limit}")
        for name in ("since", "until"):
            value = getattr(self, name)
            if value is not None:
                require_aware(value, name)
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise InvariantViolationError("from must be earlier than to")

    def matches(self, entry: AuditEntry) -> bool:
        """Whether ``entry`` passes the filters and lies after ``after`` (the memory store's
        query; Postgres runs the same one in SQL)."""
        if self.subject_type is not None and entry.subject_type != self.subject_type:
            return False
        if self.subject_id is not None and entry.subject_id != self.subject_id:
            return False
        if self.action is not None and entry.action != self.action:
            return False
        if self.since is not None and entry.occurred_at < self.since:
            return False
        if self.until is not None and entry.occurred_at >= self.until:
            return False
        if self.after is not None:
            return newest_first_key(entry) < newest_first_key_of(self.after)
        return True


def newest_first_key(entry: AuditEntry) -> tuple[datetime, str]:
    """The keyset of an entry; the trail is read in descending order of it."""
    return entry.occurred_at, str(entry.entry_id.value)


def newest_first_key_of(key: AuditKey) -> tuple[datetime, str]:
    return key.occurred_at, str(key.entry_id.value)


def readable(scope: AuditScope, tenant_id: TenantId | None, entry: AuditEntry) -> bool:
    """Whether a reader of ``scope`` acting in ``tenant_id`` may read ``entry``: the rule the
    row-level security policies and the queries both hold."""
    if scope is AuditScope.EXPORT:
        return True
    if scope is AuditScope.REGULATORY and entry.tenant_id is None:
        return True
    return tenant_id is not None and entry.tenant_id == tenant_id


class AuditReader(Protocol):
    def page(
        self, scope: AuditScope, tenant_id: TenantId | None, query: AuditQuery
    ) -> list[AuditEntry]:
        """Up to ``query.limit + 1`` entries ``scope`` admits in ``tenant_id``, newest first;
        the extra one tells the caller another page follows."""
        ...

    def export(self, since: datetime, until: datetime) -> Iterator[AuditEntry]:
        """Every entry from ``since`` (inclusive) to ``until`` (exclusive), oldest first."""
        ...


def entry_document(entry: AuditEntry) -> dict[str, Any]:
    """``entry`` as plain JSON: the route's item and one line of the export."""
    return {
        "id": str(entry.entry_id.value),
        "action": entry.action,
        "tenant_id": None if entry.tenant_id is None else str(entry.tenant_id.value),
        "subject": {"type": entry.subject_type, "id": entry.subject_id},
        "actor": {"kind": entry.actor.kind.value, "id": entry.actor.id, "label": entry.actor.label},
        "reason": entry.reason,
        "before": plain_json(entry.before),
        "after": plain_json(entry.after),
        "occurred_at": entry.occurred_at.isoformat(),
        "correlation_id": entry.correlation_id,
    }


def plain_json(value: object) -> Any:
    """An entry's read-only state as the dicts and lists JSON serialises; None stays None."""
    if isinstance(value, Mapping):
        return {str(key): plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [plain_json(item) for item in value]
    return value
