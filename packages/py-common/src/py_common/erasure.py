"""The erasure consumers' common part: read ``tenant.deletion.requested``, check it with identity,
erase, answer with ``tenant.data.erased``, and keep the erased tenant out afterwards
(``domain_kernel.erasure``; docs/runbooks/data-requests.md).

- ``erasure_component(service, eraser_on, enabled=..., verifier=...)``: the consumer a service's
  worker hosts, group ``<service>.erasure`` on ``tenant.deletion.requested``, in two steps
  (``py_common.outbox.read_then_write``). First, with no transaction open: while ``enabled``
  answers false for the tenant (the flag ``identity.tenant_erasure`` off) it only logs
  ``erasure.off``, the deletion request stays pending at identity, and ``identity-admin erasure
  resend`` sends it again once the flag is on; on, it asks identity what it holds of the tenant's
  deletion (``ErasureVerifier``: ``GET /v1/identity/erasures/{tenant_id}``, a short timeout).
  Then, on the consumer's connection: an event identity did not send for the tenant's open
  deletion request, or one for the internal tenant (``domain_kernel.erasure.erasure_refusal``),
  erases nothing: the service writes a ``tenant.erasure_refused`` audit entry and the event is
  dead-lettered at once (``EventRefusedError``). Otherwise ``eraser_on(connection)`` makes the
  service's ``TenantEraser`` there, which erases the tenant and records the event, the audit
  entry and the erased marker in the transaction that also marks the event processed. Identity
  unreachable, or answering anything but its check, raises ``IdentityUnreachableError``: the
  consumer retries, then dead-letters, and nothing is erased.
- ``erasure_switch(settings)``: the process's one ``ErasureSwitch``, ``enabled`` from the flag.
  The process's flags are configured once (``configure_flags_once``), however many services a
  worker hosts; ``cw-mvp worker`` configures them before it builds any component.
- The erased marker, ``erased_tenant`` (tenant_id, erased_at, deletion_event_id), one table per
  service with no row-level security, since every session must see it
  (``create_erased_tenant_table`` from a migration). The eraser writes it with the erasure.
  ``PostgresErasedTenants`` reads it for the service's routes (``create_app(erased_tenants=...)``:
  410 ``tenant-erased``), and ``skip_erased`` / ``skip_erased_write`` wrap a consumer's handler
  so an event of an erased tenant is marked processed with the outcome ``erased_tenant`` and
  writes nothing. On Postgres the check holds a shared advisory lock on the tenant's erasure for
  the rest of the consumer's transaction and ``begin_erasure`` takes it exclusively, so a handler
  either commits before the erasure starts (and the erasure deletes what it wrote) or sees the
  marker. ``MemoryErasedTenants`` is the memory stores' twin.
- The Postgres helpers an eraser builds on: ``begin_erasure`` sets ``app.tenant_id`` and
  ``app.erasure`` for the transaction (row-level security admits the tenant's rows only, and the
  append-only guards let its DELETEs through), ``delete_rows`` deletes a table's rows of the
  tenant, ``prune_outbox`` the tenant's events the relay has published or given up on (nothing
  prunes the outbox on its own: docs/runbooks/outbox-relay.md), and ``PostgresTenantEraser``
  writes the event to the service's outbox, the entry to the audit log and the erased marker on
  the same connection. Their statements are SQLAlchemy Core: a table and its tenant column come
  from an eraser's fixed list (plain names, which the dialect quotes), and the tenant is a bound
  parameter. Only the advisory locks and ``set_config`` are SQL text, fixed strings with bound
  parameters.
"""

import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

import httpx2
from alembic.operations import Operations
from sqlalchemy import (
    Column,
    Connection,
    DateTime,
    Engine,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    TableClause,
    Uuid,
    bindparam,
    create_engine,
    delete,
    func,
    select,
    text,
)
from sqlalchemy import column as sql_column
from sqlalchemy import table as sql_table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.schema import SchemaItem

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import (
    DELETION_REQUESTED_TOPIC,
    ERASURE_FLAG,
    DeletionRequest,
    ErasedTenants,
    ErasureCheck,
    Retained,
    TenantDataErased,
    TenantEraser,
    erasure_audit_entry,
    erasure_group,
    erasure_refusal,
    refusal_audit_entry,
)
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, EventId, TenantId
from py_common.audit.writer import AuditWriter
from py_common.auth import ServiceTokenUnavailableError, service_auth_from
from py_common.events import EventMessage
from py_common.flags import configure_flags, flag_enabled
from py_common.logging import get_logger
from py_common.migrations import ERASURE_SETTING, TENANT_SETTING
from py_common.outbox.consumer import EventRefusedError, Handler
from py_common.outbox.schema import STATUS_PENDING, outbox_event
from py_common.outbox.sync import SyncHandler, read_first_store, read_then_write
from py_common.outbox.writer import OutboxWriter
from py_common.runtime import ConsumerComponent
from py_common.settings import Settings

TOPICS: Final = (DELETION_REQUESTED_TOPIC,)
OUTBOX_TABLE: Final = "outbox_event"
ERASED_TABLE: Final = "erased_tenant"
OUTBOX_RETAINED: Final = Retained(
    OUTBOX_TABLE,
    "the tenant's events the relay has not published yet, this one among them: the relay sends "
    "them; nothing prunes the outbox on its own, an operator does (outbox-relay runbook)",
)
"""What every service with an outbox keeps: ``prune_outbox`` leaves pending rows to the relay."""
ERASED_RETAINED: Final = Retained(
    ERASED_TABLE,
    "the erased marker: the tenant's id, when and by which deletion event; the service's routes "
    "answer 410 and its consumers drop the tenant's events by it",
)
"""What every service keeps of an erased tenant: its marker."""
VERIFY_PATH: Final = "/v1/identity/erasures/{tenant_id}"
VERIFY_TIMEOUT_SECONDS: Final = 5.0
"""How long a consumer waits for identity's check; past it the consumer retries."""
ERASED_OUTCOME: Final = "erased_tenant"
"""The outcome a consumer logs for an event of a tenant it has erased: processed, nothing
written."""
LOCK_PREFIX: Final = "cw.erasure:"
DETAIL_CHARS: Final = 300
_IDENTIFIER: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")
_TENANT_PARAM: Final = "tenant"
"""The bound parameter that carries the tenant's id in the statements here."""

Enabled = Callable[[TenantId], bool]
"""Whether erasing is on for a tenant."""
EraserOn = Callable[[Connection], TenantEraser]
"""The service's eraser inside the consumer's transaction on the connection."""
ErasedOn = Callable[[Connection], ErasedTenants]
"""The service's erased markers read inside the consumer's transaction on the connection."""
log = get_logger(__name__)


class MalformedDeletionRequestError(ValueError):
    """A tenant.deletion.requested message without its tenant or with a payload its contract
    refuses; the consumer retries it and then dead-letters it."""


class IdentityUnreachableError(RuntimeError):
    """Identity could not say what it holds of a tenant's deletion; the consumer retries, then
    dead-letters, and nothing is erased."""


class ErasureRefusedError(EventRefusedError):
    """A deletion event the service refuses (``erasure_refusal``): dead-lettered at once, with
    its ``tenant.erasure_refused`` audit entry kept."""


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


class ErasureVerifier(Protocol):
    def check(self, tenant_id: TenantId) -> ErasureCheck:
        """What identity holds of the tenant's deletion; ``IdentityUnreachableError`` when it
        cannot say."""
        ...


class HttpErasureVerifier:
    """``GET {CW_IDENTITY_URL}/v1/identity/erasures/{tenant_id}`` with the service's token
    (scope ``erasure:verify``), within ``timeout_seconds``. A 404 ``identity-tenant-not-found``
    is a tenant identity does not hold; any other answer that is not a 200 with the check, a
    transport error or no service token raises ``IdentityUnreachableError``. Pass ``client`` to
    talk to an in-process app or a mock transport."""

    def __init__(
        self,
        identity_url: str,
        *,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = VERIFY_TIMEOUT_SECONDS,
        client: httpx2.Client | None = None,
    ) -> None:
        self._client = client or httpx2.Client(
            base_url=identity_url.rstrip("/"), timeout=timeout_seconds
        )
        self._auth = auth

    def check(self, tenant_id: TenantId) -> ErasureCheck:
        path = VERIFY_PATH.format(tenant_id=tenant_id)
        try:
            if self._auth is None:
                response = self._client.get(path)
            else:
                response = self._client.get(path, auth=self._auth)
        except httpx2.TransportError as exc:
            raise IdentityUnreachableError(f"identity unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise IdentityUnreachableError(f"no service token for identity: {exc}") from exc
        if response.status_code == 404 and _problem_type(response).endswith(
            "identity-tenant-not-found"
        ):
            return ErasureCheck(tenant_id, None)
        if response.status_code != 200:
            raise IdentityUnreachableError(
                f"identity answered {response.status_code} for tenant {tenant_id}'s erasure: "
                f"{response.text[:DETAIL_CHARS]}"
            )
        try:
            return check_from(response.json())
        except (ValueError, TypeError, KeyError) as exc:
            raise IdentityUnreachableError(
                f"identity answered a check the consumer cannot read: {exc}"
            ) from exc

    def close(self) -> None:
        self._client.close()


def _problem_type(response: httpx2.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    found = body.get("type") if isinstance(body, dict) else None
    return found if isinstance(found, str) else ""


def check_from(body: object) -> ErasureCheck:
    """The ``ErasureCheck`` identity's answer carries (``ErasureCheckOut``)."""
    if not isinstance(body, dict):
        raise TypeError("identity's check is a JSON object")
    event_id = body["deletion_event_id"]
    return ErasureCheck(
        tenant_id=TenantId(UUID(str(body["tenant_id"]))),
        tenant_status=str(body["status"]),
        internal=_bool(body["internal"]),
        deletion_event_id=None if event_id is None else EventId(UUID(str(event_id))),
    )


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("identity's check says internal true or false")
    return value


def verifier_from(settings: Settings) -> HttpErasureVerifier:
    """Identity at ``CW_IDENTITY_URL``, with the service's own token when it has a secret."""
    return HttpErasureVerifier(settings.identity_url, auth=service_auth_from(settings))


@dataclass(frozen=True, slots=True)
class ErasurePlan:
    """A deletion request a consumer read, and why it must erase nothing (None: erase)."""

    request: DeletionRequest
    refusal: str | None = None


def plan_erasure(
    service: str,
    message: EventMessage,
    *,
    enabled: Enabled,
    verifier: ErasureVerifier,
) -> ErasurePlan | None:
    """The first step, with no transaction open: the request, checked with identity while the
    flag is on for the tenant; None when there is nothing to do."""
    if message.topic != DELETION_REQUESTED_TOPIC:
        log.info("erasure.event_ignored", topic=message.topic, event_id=str(message.event_id))
        return None
    request = deletion_request_from(message)
    if not enabled(request.tenant_id):
        log_erasure_off(service, request)
        return None
    return ErasurePlan(request, erasure_refusal(verifier.check(request.tenant_id), request))


def erase_and_record(
    service: str,
    eraser: TenantEraser,
    request: DeletionRequest,
    *,
    clock: Callable[[], datetime] = utc_now,
    details: dict[str, object] | None = None,
) -> TenantDataErased:
    """Erase the tenant with ``eraser``, then record the answer, its audit entry (with
    ``details``) and the erased marker there."""
    erased = eraser.erase(request.tenant_id)
    event = TenantDataErased.answering(request, service, erased, clock())
    eraser.record(event, erasure_audit_entry(event, details=details))
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


def refuse_erasure(
    service: str,
    eraser: TenantEraser,
    request: DeletionRequest,
    reason: str,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> None:
    """Write the refusal's audit entry with ``eraser``, then raise ``ErasureRefusedError``: the
    entry commits, the event goes to the dead letters, and nothing is erased."""
    eraser.write_audit(refusal_audit_entry(service, request, reason, clock()))
    log.error(
        "erasure.refused",
        service=service,
        tenant_id=str(request.tenant_id),
        deletion_event_id=str(request.event_id),
        reason=reason,
    )
    raise ErasureRefusedError(reason)


def apply_erasure(
    service: str,
    plan: ErasurePlan,
    eraser: TenantEraser,
    *,
    clock: Callable[[], datetime] = utc_now,
    details: dict[str, object] | None = None,
) -> TenantDataErased:
    """The second step, in the consumer's transaction: refuse, or erase and record."""
    if plan.refusal is not None:
        refuse_erasure(service, eraser, plan.request, plan.refusal, clock=clock)
    return erase_and_record(service, eraser, plan.request, clock=clock, details=details)


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
    verifier: ErasureVerifier,
    clock: Callable[[], datetime] = utc_now,
) -> Handler:
    """The handler of ``tenant.deletion.requested``: identity's check with no transaction open,
    then the erasure (or the refusal) on the consumer's connection."""

    def read(message: EventMessage) -> ErasurePlan | None:
        return plan_erasure(service, message, enabled=enabled, verifier=verifier)

    def write(message: EventMessage, plan: ErasurePlan | None, connection: Connection) -> None:
        if plan is not None:
            apply_erasure(service, plan, eraser_on(connection), clock=clock)

    return read_then_write(read, write)


def erasure_component(
    service: str,
    eraser_on: EraserOn,
    *,
    enabled: Enabled,
    verifier: ErasureVerifier,
    clock: Callable[[], datetime] = utc_now,
) -> ConsumerComponent:
    """The consumer of group ``<service>.erasure`` a service's worker hosts."""
    return ConsumerComponent(
        group_id=erasure_group(service),
        topics=TOPICS,
        handler=erasure_handler(
            service, eraser_on, enabled=enabled, verifier=verifier, clock=clock
        ),
        store_factory=read_first_store,
    )


class _FlagsOnce:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.done = False


_flags = _FlagsOnce()
_switch: list["ErasureSwitch"] = []


def configure_flags_once(settings: Settings) -> bool:
    """Configure the process's flags from ``settings`` unless this process has done it already;
    whether this call did. A reader waits while another configures them, so no flag is read
    from a provider being swapped."""
    with _flags.lock:
        if _flags.done:
            return False
        configure_flags(settings)
        _flags.done = True
        return True


def reset_flags_once() -> None:
    """Forget that the flags were configured, and the process's switch (tests)."""
    with _flags.lock:
        _flags.done = False
        _switch.clear()


class ErasureSwitch:
    """``enabled`` from the flag ``identity.tenant_erasure`` for each tenant. The first answer
    configures the process's flags from ``settings`` unless the process has configured them
    (``configure_flags_once``): a worker reads no flag otherwise."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def __call__(self, tenant_id: TenantId) -> bool:
        configure_flags_once(self._settings)
        return flag_enabled(ERASURE_FLAG, tenant_id.value)


def erasure_switch(settings: Settings) -> ErasureSwitch:
    """The process's one switch, made from the first ``settings`` given: every erasure consumer
    a worker hosts reads the flag through it."""
    with _flags.lock:
        if not _switch:
            _switch.append(ErasureSwitch(settings))
        return _switch[0]


def _identifier(name: str) -> str:
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"not a plain table or column name: {name!r}")
    return name


def _tenant_rows(table: str, column: str) -> TableClause:
    """``table`` with its ``column`` that names the tenant, for a Core statement: plain names
    only, quoted by the dialect where it must, never written into SQL text."""
    return sql_table(_identifier(table), sql_column(_identifier(column)))


def _tenant(tenant_id: TenantId) -> dict[str, UUID]:
    return {_TENANT_PARAM: tenant_id.value}


def _lock_key(tenant_id: TenantId) -> str:
    return f"{LOCK_PREFIX}{tenant_id}"


def begin_erasure(connection: Connection, tenant_id: TenantId) -> None:
    """Take the tenant's erasure lock (waiting for the consumers whose transactions checked the
    tenant), then set the tenant and the erasure setting for the rest of the transaction."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": _lock_key(tenant_id)},
    )
    connection.execute(
        text("SELECT set_config(:tenant_setting, :tenant, true), set_config(:erasure, 'on', true)"),
        {"tenant_setting": TENANT_SETTING, "tenant": str(tenant_id), "erasure": ERASURE_SETTING},
    )


def delete_rows(
    connection: Connection, table: str, tenant_id: TenantId, *, column: str = "tenant_id"
) -> int:
    """Delete the rows of ``table`` whose ``column`` names the tenant; how many went."""
    rows = _tenant_rows(table, column)
    statement = delete(rows).where(rows.c[column] == bindparam(_TENANT_PARAM))
    result = connection.execute(statement, _tenant(tenant_id))
    return max(result.rowcount, 0)


def count_rows(
    connection: Connection, table: str, tenant_id: TenantId, *, column: str = "tenant_id"
) -> int:
    """How many rows of ``table`` name the tenant in ``column``."""
    rows = _tenant_rows(table, column)
    statement = (
        select(func.count()).select_from(rows).where(rows.c[column] == bindparam(_TENANT_PARAM))
    )
    return int(connection.execute(statement, _tenant(tenant_id)).scalar_one())


def prune_outbox(connection: Connection, tenant_id: TenantId) -> int:
    """Delete the tenant's outbox rows the relay has published or given up on; pending ones stay
    for the relay (``OUTBOX_RETAINED``)."""
    statement = delete(outbox_event).where(
        outbox_event.c.tenant_id == bindparam(_TENANT_PARAM),
        outbox_event.c.status != STATUS_PENDING,
    )
    result = connection.execute(statement, _tenant(tenant_id))
    return max(result.rowcount, 0)


ERASED_COMMENT: Final = (
    "The tenants this service has erased: the marker its routes (410) and consumers check, so "
    "nothing of an erased tenant is written again. No row-level security: every session must "
    "see it. Ids and times only."
)
metadata = MetaData()


def _erased_columns() -> list[SchemaItem]:
    return [
        Column("tenant_id", Uuid(), nullable=False),
        Column("erased_at", DateTime(timezone=True), nullable=False),
        Column("deletion_event_id", Uuid(), nullable=False),
        PrimaryKeyConstraint("tenant_id", name=f"pk_{ERASED_TABLE}"),
    ]


erased_tenant = Table(ERASED_TABLE, metadata, *_erased_columns(), comment=ERASED_COMMENT)


def create_erased_tenant_table(op: Operations) -> None:
    """Create ``erased_tenant``. Call from a service migration's ``upgrade``; the schema needs
    the lint exemption ``*.erased_tenant`` (infra/scripts/migration_lint.toml), which it has."""
    op.create_table(ERASED_TABLE, *_erased_columns(), comment=ERASED_COMMENT)


def drop_erased_tenant_table(op: Operations) -> None:
    op.drop_table(ERASED_TABLE)


def mark_erased(connection: Connection, event: TenantDataErased) -> bool:
    """Write the tenant's erased marker; an erasure run again keeps the first. Whether it was
    written now."""
    if event.tenant_id is None:  # pragma: no cover - the event refuses it
        raise ValueError("an erasure names its tenant")
    statement = (
        insert(erased_tenant)
        .values(
            tenant_id=event.tenant_id.value,
            erased_at=event.erased_at,
            deletion_event_id=event.deletion_event_id.value,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id"])
    )
    return connection.execute(statement).rowcount > 0


_MARKER_QUERY: Final = select(erased_tenant.c.tenant_id).where(
    erased_tenant.c.tenant_id == bindparam(_TENANT_PARAM)
)
"""The tenant's erased marker, by its primary key."""


def _has_marker(connection: Connection, tenant_id: TenantId) -> bool:
    """Whether ``erased_tenant`` on the connection holds the tenant's marker."""
    return connection.execute(_MARKER_QUERY, _tenant(tenant_id)).first() is not None


class ConnectionErasedTenants:
    """The erased markers inside a consumer's transaction: ``is_erased`` first takes a shared
    lock on the tenant's erasure for the rest of the transaction, so an erasure that starts
    meanwhile waits for it, and one that committed first is seen."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def is_erased(self, tenant_id: TenantId) -> bool:
        self._connection.execute(
            text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:key, 0))"),
            {"key": _lock_key(tenant_id)},
        )
        return _has_marker(self._connection, tenant_id)


class _NoMarkers:
    def is_erased(self, tenant_id: TenantId) -> bool:
        return False


def erased_on_connection(connection: Connection) -> ErasedTenants:
    """The default ``erased_on`` of a consumer's handler: the erased markers on the consumer's
    Postgres connection (``ConnectionErasedTenants``). On another database, the SQLite inbox of a
    test whose units are a memory store's, there is no marker table: none is read, and a test
    that erases passes the memory store's markers instead."""
    if connection.dialect.name == "postgresql":
        return ConnectionErasedTenants(connection)
    return _NoMarkers()


class PostgresErasedTenants:
    """The erased markers for a service's routes, on ``engine``. A tenant once seen erased stays
    so in the process (an erasure is not undone); any other is read again on each request, one
    primary-key lookup. ``pooled(url)`` gives it a small pool of its own, so the services, whose
    units of work open a connection each, do not open a second one per request for it."""

    POOL_SIZE: Final = 2
    MAX_OVERFLOW: Final = 4

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._known: set[TenantId] = set()
        self._lock = threading.Lock()

    @classmethod
    def pooled(cls, database_url: str) -> "PostgresErasedTenants":
        """The markers on an engine of their own with a small connection pool."""
        return cls(
            create_engine(
                database_url,
                pool_size=cls.POOL_SIZE,
                max_overflow=cls.MAX_OVERFLOW,
                pool_pre_ping=True,
            )
        )

    def is_erased(self, tenant_id: TenantId) -> bool:
        with self._lock:
            if tenant_id in self._known:
                return True
        with self._engine.connect() as connection:
            found = _has_marker(connection, tenant_id)
        if not found:
            return False
        with self._lock:
            self._known.add(tenant_id)
        return True


@dataclass(frozen=True, slots=True)
class ErasedMarker:
    tenant_id: TenantId
    erased_at: datetime
    deletion_event_id: EventId


class MemoryErasedTenants:
    """A memory store's erased markers: its eraser marks, its routes and handlers ask."""

    def __init__(self) -> None:
        self._markers: dict[TenantId, ErasedMarker] = {}
        self._lock = threading.Lock()

    def mark(self, event: TenantDataErased) -> bool:
        if event.tenant_id is None:  # pragma: no cover - the event refuses it
            raise ValueError("an erasure names its tenant")
        with self._lock:
            if event.tenant_id in self._markers:
                return False
            self._markers[event.tenant_id] = ErasedMarker(
                event.tenant_id, event.erased_at, event.deletion_event_id
            )
            return True

    def is_erased(self, tenant_id: TenantId) -> bool:
        with self._lock:
            return tenant_id in self._markers

    def __iter__(self) -> Iterator[ErasedMarker]:
        with self._lock:
            return iter(list(self._markers.values()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._markers)


def _skipped(
    service: str, message: EventMessage, erased_on: ErasedOn, connection: Connection
) -> bool:
    if message.tenant_id is None:
        return False
    tenant_id = TenantId(message.tenant_id)
    if not erased_on(connection).is_erased(tenant_id):
        return False
    log.info(
        "consumer.erased_tenant",
        service=service,
        topic=message.topic,
        event_id=str(message.event_id),
        tenant_id=str(tenant_id),
        outcome=ERASED_OUTCOME,
    )
    return True


def skip_erased(
    service: str, handler: SyncHandler, *, erased_on: ErasedOn = erased_on_connection
) -> SyncHandler:
    """``handler``, unless the message's tenant is erased here: then the event is only marked
    processed (outcome ``erased_tenant``) and nothing is written."""

    def handle(message: EventMessage, connection: Connection) -> None:
        if not _skipped(service, message, erased_on, connection):
            handler(message, connection)

    return handle


def skip_erased_write[P](
    service: str,
    write: Callable[[EventMessage, P, Connection], None],
    *,
    erased_on: ErasedOn = erased_on_connection,
) -> Callable[[EventMessage, P, Connection], None]:
    """The write step of a ``read_then_write`` handler, unless the message's tenant is erased
    here: then the event is only marked processed (outcome ``erased_tenant``)."""

    def guarded(message: EventMessage, plan: P, connection: Connection) -> None:
        if not _skipped(service, message, erased_on, connection):
            write(message, plan, connection)

    return guarded


class PostgresTenantEraser:
    """The recording half of a Postgres eraser: the event into the service's outbox, the entry
    into ``audit.event`` and the erased marker, on the connection whose transaction holds the
    erasure. A service's eraser subclasses it and adds ``erase``."""

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
        mark_erased(self.connection, event)

    def write_audit(self, entry: AuditEntry) -> None:
        """The entry alone (a refusal: nothing erased), under the entry's tenant setting, which
        row-level security on ``audit.event`` needs for a row of a tenant."""
        if entry.tenant_id is not None:
            self.connection.execute(
                text("SELECT set_config(:setting, :tenant, true)"),
                {"setting": TENANT_SETTING, "tenant": str(entry.tenant_id)},
            )
        self._audit.write(self.connection, entry)
