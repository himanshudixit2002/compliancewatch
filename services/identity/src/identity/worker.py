"""The identity worker: ``python -m identity.worker``, locally ``make worker SERVICE=identity``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what
``cw-mvp worker`` hosts:

- a consumer in group ``identity.erasure`` of ``tenant.deletion.requested``, in two phases
  (``py_common.outbox.read_then_write``). While the flag ``identity.tenant_erasure`` is off for
  the tenant it only logs ``erasure.off``. On, it first deletes every user's account at the
  identity provider with no transaction open (``DeleteProviderAccounts``; an account already gone
  counts as deleted), then erases the tenant on the consumer's connection
  (``PostgresIdentityEraser``: users, sign-in subjects and idempotency keys deleted, consents and
  the billing customer pseudonymised, the tenant marked erased) and writes ``tenant.data.erased``
  (service identity) and its ``tenant.erased`` audit entry, which commit with the
  ``processed_event`` row.
- a consumer in group ``identity.erasure-records`` of ``tenant.data.erased``: each service's
  answer joins the tenant's open deletion request (``RecordErasure``), which completes once
  ``CW_IDENTITY_ERASURE_SERVICES`` have all answered, with its audit entries, in the consumer's
  transaction.

What a handler cannot process goes to ``<topic>.<group>.dlq`` after the consumer's retries. The
consumers write through Postgres, so the worker needs ``CW_IDENTITY_STORE=postgres``. The outbox
relay that publishes identity's events runs on its own (``make relay SERVICE=identity``), or in
``cw-mvp worker``.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.erasure import (
    DATA_ERASED_TOPIC,
    DELETION_REQUESTED_TOPIC,
    SERVICE_PATTERN,
    DeletionRequest,
    erasure_group,
)
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, TenantId
from identity import __version__
from identity.application.erasure import SERVICE, DeleteProviderAccounts, RecordErasure
from identity.composition import identity_provider
from identity.domain.erasure import IdentityEraser
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.infrastructure.erasure import PostgresIdentityEraser
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from identity.settings import IdentitySettings
from py_common.erasure import (
    Enabled,
    ErasureSwitch,
    deletion_request_from,
    erase_and_record,
    log_erasure_off,
)
from py_common.events import EventMessage
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
    """A tenant.data.erased message without its tenant or its service."""


def answering_service(message: EventMessage) -> str:
    """The service a ``tenant.data.erased`` message says erased the tenant."""
    service = message.payload.get("service")
    if not isinstance(service, str) or not SERVICE_PATTERN.fullmatch(service):
        raise MalformedAnswerError(f"tenant.data.erased event {message.event_id} names no service")
    return service


def erasure_handler(
    accounts: DeleteProviderAccounts,
    *,
    enabled: Enabled,
    eraser_on: EraserOn = PostgresIdentityEraser,
    clock: Callable[[], datetime] = utc_now,
) -> Handler:
    """The handler of ``tenant.deletion.requested``: the provider's accounts with no transaction
    open, then the erasure on the consumer's connection. ``eraser_on`` makes the eraser there;
    tests pass the memory store's."""

    def read(message: EventMessage) -> DeletionRequest | None:
        if message.topic != DELETION_REQUESTED_TOPIC:
            log.info("erasure.event_ignored", topic=message.topic, event_id=str(message.event_id))
            return None
        request = deletion_request_from(message)
        if not enabled(request.tenant_id):
            log_erasure_off(SERVICE, request)
            return None
        deletions = accounts.run(request.tenant_id)
        log.info(
            "identity.provider_accounts_deleted",
            tenant_id=str(request.tenant_id),
            deleted=deletions.deleted,
            other_provider=deletions.other_provider,
        )
        return request

    def write(
        message: EventMessage, request: DeletionRequest | None, connection: Connection
    ) -> None:
        if request is None:
            return
        erase_and_record(SERVICE, eraser_on(connection), request, clock=clock)

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
                correlation_id=CorrelationId(message.correlation_id),
            )
        request = recorded.request
        log.info(
            "identity.erasure_recorded",
            tenant_id=str(tenant_id),
            service=service,
            request_id=None if request is None else str(request.id),
            status=None if request is None else request.status.value,
            pending=[] if request is None else list(request.pending(record.expected)),
            changed=recorded.changed,
        )

    return handle


def components(
    settings: IdentitySettings,
    *,
    provider: IdentityProvider | None = None,
    enabled: Enabled | None = None,
) -> WorkerComponents:
    """The two consumers; ``provider`` replaces the identity provider and ``enabled`` the flag
    (tests)."""
    if settings.identity_store != "postgres":
        raise ValueError("the identity worker needs CW_IDENTITY_STORE=postgres")
    units = PostgresUnitOfWorkFactory(create_engine(settings.database_url, poolclass=NullPool))
    accounts = DeleteProviderAccounts(units, provider or identity_provider(settings))
    switch = enabled or ErasureSwitch(settings)
    return WorkerComponents(
        consumers=(
            ConsumerComponent(
                group_id=GROUP_ID,
                topics=(DELETION_REQUESTED_TOPIC,),
                handler=erasure_handler(accounts, enabled=switch),
                store_factory=read_first_store,
            ),
            ConsumerComponent(
                group_id=RECORDS_GROUP_ID,
                topics=(DATA_ERASED_TOPIC,),
                handler=sync_handler(records_handler(RecordErasure(settings.erasure_services))),
            ),
        )
    )


def main() -> None:
    run_worker_process(IdentitySettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
