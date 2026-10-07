"""A tenant's erasure across the services: what one service erased and kept, and the event that
says so (docs/legal/data-map.md, docs/runbooks/data-requests.md).

Identity records a tenant's deletion request and emits ``tenant.deletion.requested``. Every
service that holds the tenant's data consumes it in its group ``<service>.erasure`` and, while
the flag ``identity.tenant_erasure`` (``ERASURE_FLAG``) is on for the tenant, erases it in one
transaction: it deletes or pseudonymises the tenant's rows (``Erased.tables``), names the tables
it keeps and why (``Erased.retained``), writes a ``tenant.erased`` audit entry
(``erasure_audit_entry``) and emits ``TenantDataErased``, all with the consumer's
``processed_event`` row. Identity's group ``identity.erasure-records`` counts the answers and
completes the request once every service has erased.

The audit log itself is never erased: its rows are masked when they are written and kept seven
years, the documented exception (``retain_audit`` is always true).

``TenantEraser`` is what a service's erasure runs on: the Postgres one on the consumer's
connection, a memory one on the service's memory store (tests and the in-process journey).
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import ClassVar, Final, Protocol

from domain_kernel._validation import require_aware, require_bool, require_instance, require_text
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import CorrelationId, EventId, TenantId

ERASURE_FLAG: Final = "identity.tenant_erasure"
"""The flag that lets the erasure consumers erase; off, each only logs (packages/flags)."""
DELETION_REQUESTED_TOPIC: Final = "tenant.deletion.requested"
DATA_ERASED_TOPIC: Final = "tenant.data.erased"
ERASURE_PURPOSE: Final = "erasure"
"""The purpose part of every erasure consumer group: ``<service>.erasure``."""
ERASED_ACTION: Final = "tenant.erased"
"""The audit action each service writes once it has erased a tenant."""
ERASED_SUBJECT_TYPE: Final = "tenant"
SERVICE_PATTERN: Final = re.compile(r"[a-z][a-z-]*")
TABLE_NAME: Final = re.compile(r"[a-z_][a-z0-9_.]*")
MAX_REASON_CHARS: Final = 300


def erasure_group(service: str) -> str:
    """The consumer group a service erases a tenant in: ``<service>.erasure``."""
    return f"{_service(service)}.{ERASURE_PURPOSE}"


def _service(value: object) -> str:
    text = require_text(value, "service")
    if not SERVICE_PATTERN.fullmatch(text):
        raise InvariantViolationError(f"service must be a service directory name, got {text!r}")
    return text


def _table(value: object) -> str:
    text = require_text(value, "table")
    if not TABLE_NAME.fullmatch(text):
        raise InvariantViolationError(f"table must be a table name, got {text!r}")
    return text


@dataclass(frozen=True, slots=True)
class Retained:
    """A table a service keeps rows of after the erasure, or keeps with the tenant's reference
    removed, and why."""

    table: str
    reason: str

    def __post_init__(self) -> None:
        _table(self.table)
        reason = require_text(self.reason, "reason")
        if len(reason) > MAX_REASON_CHARS:
            raise InvariantViolationError(f"a reason has at most {MAX_REASON_CHARS} characters")


@dataclass(frozen=True, slots=True)
class Erased:
    """What one service's erasure did: the rows it deleted or pseudonymised per table (zero
    counts included, so the event lists every table the service looked at) and what it kept."""

    tables: Mapping[str, int] = field(default_factory=dict, hash=False)
    retained: tuple[Retained, ...] = ()

    def __post_init__(self) -> None:
        counts: dict[str, int] = {}
        for table, rows in dict(self.tables).items():
            if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
                raise InvariantViolationError(f"{table}: a row count is a whole number, not {rows}")
            counts[_table(table)] = rows
        object.__setattr__(self, "tables", MappingProxyType(counts))
        require_instance(self.retained, tuple, "retained")
        for item in self.retained:
            require_instance(item, Retained, "retained[]")
        names = [item.table for item in self.retained]
        if len(names) != len(set(names)):
            raise InvariantViolationError("each retained table is named once")

    @property
    def rows(self) -> int:
        """Every row the erasure deleted or pseudonymised."""
        return sum(self.tables.values())


@dataclass(frozen=True, slots=True)
class DeletionRequest:
    """A ``tenant.deletion.requested`` event as an erasure consumer reads it."""

    event_id: EventId
    tenant_id: TenantId
    correlation_id: CorrelationId
    requested_at: datetime
    deadline_at: datetime
    retain_audit: bool = True

    def __post_init__(self) -> None:
        require_instance(self.event_id, EventId, "event_id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.correlation_id, CorrelationId, "correlation_id")
        require_aware(self.requested_at, "requested_at")
        require_aware(self.deadline_at, "deadline_at")
        require_bool(self.retain_audit, "retain_audit")


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantDataErased(DomainEvent):
    """One service erased a tenant; ``causation_id`` is the deletion request's event."""

    topic: ClassVar[str] = DATA_ERASED_TOPIC
    schema_version: ClassVar[str] = "1.0.0"

    service: str
    deletion_event_id: EventId
    erased_at: datetime
    tables: Mapping[str, int] = field(default_factory=dict, hash=False)
    retained: tuple[Retained, ...] = ()

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is None:
            raise InvariantViolationError("tenant.data.erased names the tenant it erased")
        _service(self.service)
        require_instance(self.deletion_event_id, EventId, "deletion_event_id")
        require_aware(self.erased_at, "erased_at")
        erased = Erased(self.tables, self.retained)
        object.__setattr__(self, "tables", erased.tables)

    @classmethod
    def answering(
        cls, request: DeletionRequest, service: str, erased: Erased, at: datetime
    ) -> "TenantDataErased":
        """The event a service emits once it has erased what ``request`` asked for."""
        return cls(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            causation_id=request.event_id,
            occurred_at=at,
            service=service,
            deletion_event_id=request.event_id,
            erased_at=at,
            tables=erased.tables,
            retained=erased.retained,
        )


def erasure_audit_entry(event: TenantDataErased) -> AuditEntry:
    """The ``tenant.erased`` entry a service writes with its erasure: by the service itself,
    with the row counts and the tables it kept (names only; the event carries the reasons)."""
    if event.tenant_id is None:  # pragma: no cover - the event refuses it
        raise InvariantViolationError("an erasure names its tenant")
    return AuditEntry(
        action=ERASED_ACTION,
        tenant_id=event.tenant_id,
        subject_type=ERASED_SUBJECT_TYPE,
        subject_id=str(event.tenant_id),
        actor=AuditActor.system(event.service),
        after={
            "service": event.service,
            "deletion_event_id": str(event.deletion_event_id),
            "tables": dict(event.tables),
            "retained": [item.table for item in event.retained],
        },
        occurred_at=event.erased_at,
        correlation_id=str(event.correlation_id),
    )


def retained(*items: tuple[str, str]) -> tuple[Retained, ...]:
    """``Retained`` entries from ``(table, reason)`` pairs, in the order given."""
    return tuple(Retained(table, reason) for table, reason in items)


def counts(pairs: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Row counts per table, adding up a table named more than once."""
    found: dict[str, int] = {}
    for table, rows in pairs:
        found[table] = found.get(table, 0) + rows
    return found


class TenantEraser(Protocol):
    """One service's erasure of a tenant, inside the transaction the consumer commits."""

    def erase(self, tenant_id: TenantId) -> Erased:
        """Delete or pseudonymise the tenant's rows, and say what stays."""
        ...

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        """Write the event to the service's outbox and the entry to the audit log, in the same
        transaction as the erasure."""
        ...
