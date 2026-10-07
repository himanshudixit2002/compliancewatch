"""The identity worker: ``python -m identity.worker``, locally ``make worker SERVICE=identity``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what
``cw-mvp worker`` hosts:

- a consumer in group ``identity.erasure`` of ``tenant.deletion.requested``, in two steps
  (``py_common.outbox.read_then_write``). While the flag ``identity.tenant_erasure`` is off for
  the tenant it only logs ``erasure.off``. On, with no transaction open, it first checks the event
  against identity's own records (``CheckErasure``): an event for a tenant that is not being
  deleted, for the internal tenant, or that is not the one identity last sent for the tenant's
  open deletion request touches nothing, not even the provider; the consumer writes a
  ``tenant.erasure_refused`` audit entry and dead-letters it at once. Otherwise it deletes every
  user's account at the identity provider (``DeleteProviderAccounts``; an account already gone
  counts as deleted), then erases the tenant on the consumer's connection
  (``PostgresIdentityEraser``: users, sign-in subjects and idempotency keys deleted, consents and
  the billing customer pseudonymised with ``CW_IDENTITY_ERASURE_PEPPER``, checkout links emptied,
  the tenant marked erased) and writes ``tenant.data.erased`` (service identity), its
  ``tenant.erased`` audit entry (with the accounts of another provider the operator deletes by
  hand) and the erased marker, which commit with the ``processed_event`` row.
- a consumer in group ``identity.erasure-records`` of ``tenant.data.erased``: each service's
  answer to the event identity last sent joins the tenant's open deletion request
  (``RecordErasure``); once ``CW_IDENTITY_ERASURE_SERVICES`` have all answered, the second pass is
  written to the outbox, held ``CW_IDENTITY_ERASURE_SECOND_PASS_SECONDS``, and the request
  completes once they have all answered that too, with its audit entries, in the consumer's
  transaction.

What a handler cannot process goes to ``<topic>.<group>.dlq`` after the consumer's retries. The
consumers write through Postgres, so the worker needs ``CW_IDENTITY_STORE=postgres``. The outbox
relay that publishes identity's events runs on its own (``make relay SERVICE=identity``), or in
``cw-mvp worker``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.erasure import (
    DATA_ERASED_TOPIC,
    DELETION_REQUESTED_TOPIC,
    ERASURE_FLAG,
    SERVICE_PATTERN,
    ErasureCheck,
    erasure_group,
)
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, EventId, TenantId
from identity import __version__
from identity.application.erasure import (
    SERVICE,
    CheckErasure,
    DeleteProviderAccounts,
    ProviderDeletions,
    RecordErasure,
)
from identity.composition import identity_provider
from identity.domain.erasure import IdentityEraser
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.infrastructure.erasure import PostgresIdentityEraser
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from identity.settings import IdentitySettings
from py_common.erasure import (
    Enabled,
    ErasurePlan,
    apply_erasure,
    erasure_switch,
    plan_erasure,
)
from py_common.events import EventMessage
from py_common.flags import flag_may_be_on
from py_common.logging import get_logger
from py_common.outbox import read_first_store, read_then_write, sync_handler
from py_common.outbox.consumer import Handler
from py_common.outbox.sync import SyncHandler
from py_common.runtime import ConsumerComponent, WorkerComponents, run_worker_process

GROUP_ID: Final = erasure_group(SERVICE)
RECORDS_GROUP_ID: Final = "identity.erasure-records"
SERVICE_NAME: Final = "identity-worker"

log = get_logger(__name__)

EraserOn = Callable[[Connection], IdentityEraser]
UnitsOn = Callable[[Connection], UnitOfWorkFactory]


class MalformedAnswerError(ValueError):
    """A tenant.data.erased message without its tenant, its service or the deletion event it
    answers."""


def answering_service(message: EventMessage) -> str:
    """The service a ``tenant.data.erased`` message says erased the tenant."""
    service = message.payload.get("service")
    if not isinstance(service, str) or not SERVICE_PATTERN.fullmatch(service):
        raise MalformedAnswerError(f"tenant.data.erased event {message.event_id} names no service")
    return service


def answered_event(message: EventMessage) -> EventId:
    """The deletion event a ``tenant.data.erased`` message answers."""
    value = message.payload.get("deletion_event_id")
    try:
        return EventId(UUID(str(value)))
    except ValueError as exc:
        raise MalformedAnswerError(
            f"tenant.data.erased event {message.event_id} names no deletion event"
        ) from exc


@dataclass(frozen=True, slots=True)
class IdentityPlan:
    """What the first step decided: the plan, and the provider's deletions when it erases."""

    plan: ErasurePlan
    deletions: ProviderDeletions | None = None


class _LocalCheck:
    """``ErasureVerifier`` on identity's own records."""

    def __init__(self, check: CheckErasure) -> None:
        self._check = check

    def check(self, tenant_id: TenantId) -> ErasureCheck:
        return self._check.run(tenant_id)


def erasure_handler(
    accounts: DeleteProviderAccounts,
    check: CheckErasure,
    *,
    enabled: Enabled,
    eraser_on: EraserOn,
    clock: Callable[[], datetime] = utc_now,
) -> Handler:
    """The handler of ``tenant.deletion.requested``: the check against identity's records and
    the provider's accounts with no transaction open, then the erasure (or the refusal) on the
    consumer's connection. ``eraser_on`` makes the eraser there; tests pass the memory
    store's."""
    verifier = _LocalCheck(check)

    def read(message: EventMessage) -> IdentityPlan | None:
        plan = plan_erasure(SERVICE, message, enabled=enabled, verifier=verifier)
        if plan is None:
            return None
        if plan.refusal is not None:
            return IdentityPlan(plan)
        deletions = accounts.run(plan.request.tenant_id)
        log.info(
            "identity.provider_accounts_deleted",
            tenant_id=str(plan.request.tenant_id),
            deleted=deletions.deleted,
            other_provider=[account.document() for account in deletions.elsewhere],
        )
        return IdentityPlan(plan, deletions)

    def write(message: EventMessage, found: IdentityPlan | None, connection: Connection) -> None:
        if found is None:
            return
        details = None if found.deletions is None else found.deletions.details()
        apply_erasure(SERVICE, found.plan, eraser_on(connection), clock=clock, details=details)

    return read_then_write(read, write)


def records_handler(
    record: RecordErasure, *, units_on: UnitsOn = PostgresUnitOfWorkFactory.on_connection
) -> SyncHandler:
    """The handler of ``tenant.data.erased``: the answer recorded on the consumer's
    connection. ``units_on`` makes the units there; tests pass the memory store's."""

    def handle(message: EventMessage, connection: Connection) -> None:
        if message.topic != DATA_ERASED_TOPIC:
            log.info("erasure.event_ignored", topic=message.topic, event_id=str(message.event_id))
            return
        if message.tenant_id is None:
            raise MalformedAnswerError(
                f"tenant.data.erased event {message.event_id} names no tenant"
            )
        service = answering_service(message)
        tenant_id = TenantId(message.tenant_id)
        with units_on(connection)(tenant_id) as uow:
            recorded = record.run_in(
                uow,
                tenant_id,
                service,
                deletion_event_id=answered_event(message),
                correlation_id=CorrelationId(message.correlation_id),
            )
        request = recorded.request
        log.info(
            "identity.erasure_recorded",
            tenant_id=str(tenant_id),
            service=service,
            request_id=None if request is None else str(request.id),
            status=None if request is None else request.status.value,
            erasure_pass=None if request is None else request.erasure_pass,
            pending=[] if request is None else list(request.pending(record.expected)),
            changed=recorded.changed,
            stale=recorded.stale,
        )

    return handle


def record_erasure(settings: IdentitySettings) -> RecordErasure:
    """The answers' recorder the settings describe: the services and the second pass's delay."""
    return RecordErasure(
        settings.erasure_services,
        second_pass_after=timedelta(seconds=settings.identity_erasure_second_pass_seconds),
    )


def components(
    settings: IdentitySettings,
    *,
    provider: IdentityProvider | None = None,
    enabled: Enabled | None = None,
) -> WorkerComponents:
    """The two consumers; ``provider`` replaces the identity provider and ``enabled`` the flag
    (tests). Where the flag can be on, the worker refuses to start without the erasure pepper
    outside local and test."""
    if settings.identity_store != "postgres":
        raise ValueError("the identity worker needs CW_IDENTITY_STORE=postgres")
    if flag_may_be_on(ERASURE_FLAG, settings) and not settings.is_dev:
        settings.erasure_pepper  # noqa: B018 - raises without CW_IDENTITY_ERASURE_PEPPER
    units = PostgresUnitOfWorkFactory(create_engine(settings.database_url, poolclass=NullPool))
    accounts = DeleteProviderAccounts(units, provider or identity_provider(settings))
    switch = enabled or erasure_switch(settings)
    return WorkerComponents(
        consumers=(
            ConsumerComponent(
                group_id=GROUP_ID,
                topics=(DELETION_REQUESTED_TOPIC,),
                handler=erasure_handler(
                    accounts,
                    CheckErasure(units),
                    enabled=switch,
                    eraser_on=postgres_eraser(settings),
                ),
                store_factory=read_first_store,
            ),
            ConsumerComponent(
                group_id=RECORDS_GROUP_ID,
                topics=(DATA_ERASED_TOPIC,),
                handler=sync_handler(records_handler(record_erasure(settings))),
            ),
        )
    )


def postgres_eraser(settings: IdentitySettings) -> EraserOn:
    """The Postgres eraser with the settings' pepper, read when an erasure runs: a worker whose
    flag is off for every tenant starts without one, and an erasure without one fails and is
    retried, then dead-lettered, with nothing erased."""

    def eraser_on(connection: Connection) -> IdentityEraser:
        return PostgresIdentityEraser(connection, pepper=settings.erasure_pepper)

    return eraser_on


def main() -> None:
    run_worker_process(IdentitySettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
