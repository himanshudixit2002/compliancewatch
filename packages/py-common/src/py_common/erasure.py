"""The erasure consumers' common part: read ``tenant.deletion.requested``, erase, answer with
``tenant.data.erased`` (``domain_kernel.erasure``; docs/runbooks/data-requests.md).

- ``erasure_component(service, eraser_on, enabled=...)``: the consumer a service's worker hosts,
  group ``<service>.erasure`` on ``tenant.deletion.requested``. Its handler runs on the
  consumer's connection (``sync_handler``): ``eraser_on(connection)`` makes the service's
  ``TenantEraser`` there, which erases the tenant and records the event and the audit entry in
  the transaction that also marks the event processed. While ``enabled(tenant)`` answers false
  (the flag ``identity.tenant_erasure`` off for the tenant), it only logs ``erasure.off``, and
  the deletion request stays pending at identity; ``identity-admin erasure resend`` sends the
  request again once the flag is on.
- ``ErasureSwitch(settings)``: ``enabled`` from the flag, configuring the process's flags on
  first use, so a worker that hosts several services needs nothing else.
- The Postgres helpers an eraser builds on: ``begin_erasure`` sets ``app.tenant_id`` and
  ``app.erasure`` for the transaction (row-level security admits the tenant's rows only, and the
  append-only guards let its DELETEs through), ``delete_rows`` deletes a table's rows of the
  tenant, ``prune_outbox`` the tenant's events the relay has published or given up on, and
  ``PostgresTenantEraser`` writes the event to the service's outbox and the entry to the audit
  log on the same connection.
"""

import re
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Final

from sqlalchemy import Connection, text

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import (
    DELETION_REQUESTED_TOPIC,
    ERASURE_FLAG,
    DeletionRequest,
    Retained,
    TenantDataErased,
    TenantEraser,
    erasure_audit_entry,
    erasure_group,
)
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, EventId, TenantId
from py_common.audit.writer import AuditWriter
from py_common.events import EventMessage
from py_common.flags import configure_flags, flag_enabled
from py_common.logging import get_logger
from py_common.migrations import ERASURE_SETTING, TENANT_SETTING
from py_common.outbox.sync import SyncHandler, sync_handler
from py_common.outbox.writer import OutboxWriter
from py_common.runtime import ConsumerComponent
from py_common.settings import Settings

TOPICS: Final = (DELETION_REQUESTED_TOPIC,)
OUTBOX_TABLE: Final = "outbox_event"
OUTBOX_RETAINED: Final = Retained(
    OUTBOX_TABLE,
    "the tenant's events the relay has not published yet, this one among them: the relay sends "
    "them and the outbox prune removes them",
)
"""What every service with an outbox keeps: ``prune_outbox`` leaves pending rows to the relay."""
_IDENTIFIER: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")

Enabled = Callable[[TenantId], bool]
"""Whether erasing is on for a tenant."""
EraserOn = Callable[[Connection], TenantEraser]
"""The service's eraser inside the consumer's transaction on the connection."""

log = get_logger(__name__)


class MalformedDeletionRequestError(ValueError):
    """A tenant.deletion.requested message without its tenant or with a payload its contract
    refuses; the consumer retries it and then dead-letters it."""


def _when(payload: dict[str, object], name: str) -> datetime:
    value = payload.get(name)
    if not isinstance(value, str):
        raise MalformedDeletionRequestError(f"tenant.deletion.requested needs {name}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MalformedDeletionRequestError(f"{name} is not a date-time: {value!r}") from exc
    if parsed.tzinfo is None:
        raise MalformedDeletionRequestError(f"{name} has no time zone: {value!r}")
    return parsed


def deletion_request_from(message: EventMessage) -> DeletionRequest:
    """The deletion request a ``tenant.deletion.requested`` message carries."""
    if message.topic != DELETION_REQUESTED_TOPIC:
        raise MalformedDeletionRequestError(f"{message.topic} is not a deletion request")
    if message.tenant_id is None:
        raise MalformedDeletionRequestError(
            f"tenant.deletion.requested event {message.event_id} names no tenant"
        )
    retain_audit = message.payload.get("retain_audit")
    if not isinstance(retain_audit, bool):
        raise MalformedDeletionRequestError("tenant.deletion.requested needs retain_audit")
    return DeletionRequest(
        event_id=EventId(message.event_id),
        tenant_id=TenantId(message.tenant_id),
        correlation_id=CorrelationId(message.correlation_id),
        requested_at=_when(message.payload, "requested_at"),
        deadline_at=_when(message.payload, "deadline_at"),
        retain_audit=retain_audit,
    )


def erase_and_record(
    service: str,
    eraser: TenantEraser,
    request: DeletionRequest,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> TenantDataErased:
    """Erase the tenant with ``eraser``, then record the answer and its audit entry there."""
    erased = eraser.erase(request.tenant_id)
    event = TenantDataErased.answering(request, service, erased, clock())
    eraser.record(event, erasure_audit_entry(event))
    log.info(
        "erasure.done",
        service=service,
        tenant_id=str(request.tenant_id),
        deletion_event_id=str(request.event_id),
        rows=erased.rows,
        tables=dict(erased.tables),
        retained=[item.table for item in erased.retained],
    )
    return event


def log_erasure_off(service: str, request: DeletionRequest) -> None:
    """The line a consumer logs instead of erasing while the flag is off for the tenant."""
    log.warning(
        "erasure.off",
        service=service,
        tenant_id=str(request.tenant_id),
        deletion_event_id=str(request.event_id),
        flag=ERASURE_FLAG,
        hint="the deletion request stays pending; turn the flag on and resend it",
    )


def erasure_handler(
    service: str,
    eraser_on: EraserOn,
    *,
    enabled: Enabled,
    clock: Callable[[], datetime] = utc_now,
) -> SyncHandler:
    """The handler of ``tenant.deletion.requested`` on the consumer's connection."""

    def handle(message: EventMessage, connection: Connection) -> None:
        if message.topic != DELETION_REQUESTED_TOPIC:
            log.info("erasure.event_ignored", topic=message.topic, event_id=str(message.event_id))
            return
        request = deletion_request_from(message)
        if not enabled(request.tenant_id):
            log_erasure_off(service, request)
            return
        erase_and_record(service, eraser_on(connection), request, clock=clock)

    return handle


def erasure_component(
    service: str,
    eraser_on: EraserOn,
    *,
    enabled: Enabled,
    clock: Callable[[], datetime] = utc_now,
) -> ConsumerComponent:
    """The consumer of group ``<service>.erasure`` a service's worker hosts."""
    return ConsumerComponent(
        group_id=erasure_group(service),
        topics=TOPICS,
        handler=sync_handler(erasure_handler(service, eraser_on, enabled=enabled, clock=clock)),
    )


class ErasureSwitch:
    """``enabled`` from the flag ``identity.tenant_erasure`` for each tenant. The first answer
    configures the process's flags from ``settings`` (``configure_flags``), unless they are
    configured already: a worker reads no flag otherwise."""

    def __init__(self, settings: Settings, *, configure: bool = True) -> None:
        self._settings = settings
        self._configured = not configure
        self._lock = threading.Lock()

    def __call__(self, tenant_id: TenantId) -> bool:
        if not self._configured:
            with self._lock:
                if not self._configured:
                    configure_flags(self._settings)
                    self._configured = True
        return flag_enabled(ERASURE_FLAG, tenant_id.value)


def _identifier(name: str) -> str:
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"not a plain table or column name: {name!r}")
    return name


def begin_erasure(connection: Connection, tenant_id: TenantId) -> None:
    """Set the tenant and the erasure setting for the rest of the transaction."""
    connection.execute(
        text("SELECT set_config(:tenant_setting, :tenant, true), set_config(:erasure, 'on', true)"),
        {"tenant_setting": TENANT_SETTING, "tenant": str(tenant_id), "erasure": ERASURE_SETTING},
    )


def delete_rows(
    connection: Connection, table: str, tenant_id: TenantId, *, column: str = "tenant_id"
) -> int:
    """Delete the rows of ``table`` whose ``column`` names the tenant; how many went."""
    result = connection.execute(
        text(f"DELETE FROM {_identifier(table)} WHERE {_identifier(column)} = :tenant"),
        {"tenant": tenant_id.value},
    )
    return max(result.rowcount, 0)


def count_rows(
    connection: Connection, table: str, tenant_id: TenantId, *, column: str = "tenant_id"
) -> int:
    """How many rows of ``table`` name the tenant in ``column``."""
    found = connection.execute(
        text(f"SELECT count(*) FROM {_identifier(table)} WHERE {_identifier(column)} = :tenant"),
        {"tenant": tenant_id.value},
    ).scalar_one()
    return int(found)


def prune_outbox(connection: Connection, tenant_id: TenantId) -> int:
    """Delete the tenant's outbox rows the relay has published or given up on; pending ones stay
    for the relay (``OUTBOX_RETAINED``)."""
    result = connection.execute(
        text(f"DELETE FROM {OUTBOX_TABLE} WHERE tenant_id = :tenant AND status <> 'pending'"),
        {"tenant": tenant_id.value},
    )
    return max(result.rowcount, 0)


class PostgresTenantEraser:
    """The recording half of a Postgres eraser: the event into the service's outbox and the
    entry into ``audit.event``, on the connection whose transaction holds the erasure. A
    service's eraser subclasses it and adds ``erase``."""

    def __init__(
        self,
        connection: Connection,
        *,
        writer: OutboxWriter | None = None,
        audit: AuditWriter | None = None,
    ) -> None:
        self.connection = connection
        self._writer = writer or OutboxWriter()
        self._audit = audit or AuditWriter()

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        self._writer.write(self.connection, event)
        self._audit.write(self.connection, entry)
