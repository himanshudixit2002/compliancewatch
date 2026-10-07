"""The notification worker: ``python -m notification.worker``, locally
``make worker SERVICE=notification``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what a
process that hosts several services adds to its own:

- a consumer in group ``notification.obligations`` of obligation.created, obligation.due_soon,
  obligation.rescheduled and obligation.closed. Each event becomes a notice
  (``infrastructure.events_in``), and ``EnqueueNotifications.run_in`` queues its notifications
  in the consumer's own transaction (``SqlAlchemyUnitOfWork.on_connection``), so they and the
  ``processed_event`` row commit together and a redelivered event queues nothing twice. An
  event that sends nothing (a manual reschedule, the user's own completion) is only marked
  processed. An event of a tenant the service has erased queues nothing and is only marked
  processed (``py_common.erasure.skip_erased``, outcome ``erased_tenant``). A message the
  handler cannot read goes to ``<topic>.notification.obligations.dlq`` after the consumer's
  retries.
- a consumer in group ``notification.erasure`` of ``tenant.deletion.requested``
  (``py_common.erasure``): while the flag ``identity.tenant_erasure`` is off for the tenant it
  only logs ``erasure.off``; on, it checks the event with identity (one identity did not send is
  refused, audited and dead-lettered), then deletes the tenant's notifications with their
  receipts and work, its recipients and their addresses and businesses, its directory rows, the
  opt-ins of addresses no other tenant holds, its idempotency keys and published events
  (``infrastructure.erasure.PostgresNotificationEraser``, which states the rule), keeps the
  opt-outs and the suppressions, and writes ``tenant.data.erased`` (service notification), its
  ``tenant.erased`` audit entry and the erased marker with the ``processed_event`` row.
- the dispatcher, ``DispatchDue.run``, every ``CW_NOTIFICATION_DISPATCH_INTERVAL_SECONDS``
  (5 seconds): it sends what is due, several workers side by side included. The daily digests
  are due at ``CW_NOTIFICATION_DIGEST_AT`` (09:00 IST) and go out through it too.
- the retention sweep, ``PurgeExpired.run``, daily at 03:00 IST: it deletes notifications older
  than two years and empties the values of those older than 30 days, one tenant at a time.

The consumer writes through Postgres, so the worker needs ``CW_NOTIFICATION_STORE=postgres``.
The outbox relay that publishes notification.sent and notification.failed runs on its own
(``make relay SERVICE=notification``).
"""

from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import time

from sqlalchemy import Connection

from domain_kernel.channels import Channel
from domain_kernel.ids import TenantId
from notification import __version__
from notification.application.dispatch import DispatchDue
from notification.application.enqueue import EnqueueNotifications
from notification.application.retention import PurgeExpired
from notification.composition import wire
from notification.domain.channels import ChannelAdapter
from notification.domain.ports import RuleVersionReader
from notification.domain.preferences import IST
from notification.domain.repository import UnitOfWork
from notification.domain.routing import TOPICS
from notification.infrastructure.erasure import PostgresNotificationEraser
from notification.infrastructure.events_in import notice_from
from notification.infrastructure.repository import SqlAlchemyUnitOfWork
from notification.settings import NotificationSettings
from py_common.erasure import (
    Enabled,
    ErasedOn,
    ErasureVerifier,
    erased_on_connection,
    erasure_component,
    erasure_switch,
    skip_erased,
    verifier_from,
)
from py_common.events import EventMessage
from py_common.logging import get_logger
from py_common.outbox import sync_handler
from py_common.outbox.sync import SyncHandler
from py_common.runtime import (
    ConsumerComponent,
    PeriodicComponent,
    WorkerComponents,
    daily_at,
    run_worker_process,
)

GROUP_ID = "notification.obligations"
DISPATCH_JOB = "notification-dispatch"
RETENTION_JOB = "notification-retention"
RETENTION_AT = time(3, 0, tzinfo=IST)
"""03:00 IST, when little else runs."""
SERVICE_NAME = "notification-worker"
ERASURE_SERVICE = "notification"

log = get_logger(__name__)

UnitOnConnection = Callable[[Connection, TenantId], AbstractContextManager[UnitOfWork]]
"""A unit of work of the tenant inside the transaction the connection has begun."""


def obligation_handler(
    enqueue: EnqueueNotifications,
    *,
    unit_on: UnitOnConnection = SqlAlchemyUnitOfWork.on_connection,
    erased_on: ErasedOn = erased_on_connection,
) -> SyncHandler:
    """The handler of the obligation events: queue each event's notifications on the
    consumer's connection, unless the event's tenant is erased here. ``unit_on`` opens the unit
    there and ``erased_on`` reads the erased markers; tests pass the memory store's."""

    def handle(message: EventMessage, connection: Connection) -> None:
        notice = notice_from(message)
        if notice is None:
            log.info(
                "notification.event_ignored", topic=message.topic, event_id=str(message.event_id)
            )
            return
        with unit_on(connection, notice.tenant_id) as unit:
            queued = enqueue.run_in(unit, notice)
        log.info(
            "notification.event_queued",
            topic=message.topic,
            event_id=str(message.event_id),
            queued=queued.queued,
            duplicates=queued.duplicates,
            unreachable=queued.unreachable,
        )

    return skip_erased(ERASURE_SERVICE, handle, erased_on=erased_on)


def dispatch_job(dispatch: DispatchDue) -> Callable[[], None]:
    """One run of the dispatcher, logged when it handled anything."""

    def run() -> None:
        deliveries = dispatch.run()
        if deliveries:
            outcomes = Counter(delivery.outcome.value for delivery in deliveries)
            log.info("notification.dispatched", messages=len(deliveries), **outcomes)

    return run


def retention_job(purge: PurgeExpired) -> Callable[[], None]:
    """One retention sweep, logged with what it removed."""

    def run() -> None:
        swept = purge.run()
        log.info(
            "notification.retention_swept",
            tenants=swept.tenants,
            purged=swept.purged,
            stripped=swept.stripped,
        )

    return run


def components(
    settings: NotificationSettings,
    *,
    channels: Mapping[Channel, ChannelAdapter] | None = None,
    rules: RuleVersionReader | None = None,
    erasure: Enabled | None = None,
    verifier: ErasureVerifier | None = None,
) -> WorkerComponents:
    """The two consumers, the dispatcher loop and the retention sweep; ``channels`` and
    ``rules`` replace the configured channels and rulebook reader, ``erasure`` the flag of the
    erasure consumer and ``verifier`` identity's check."""
    if settings.notification_store != "postgres":
        raise ValueError("the notification worker needs CW_NOTIFICATION_STORE=postgres")
    wiring = wire(settings, channels=channels, rules=rules)
    return WorkerComponents(
        consumers=(
            ConsumerComponent(
                group_id=GROUP_ID,
                topics=TOPICS,
                handler=sync_handler(obligation_handler(wiring.enqueue)),
            ),
            erasure_component(
                ERASURE_SERVICE,
                PostgresNotificationEraser,
                enabled=erasure or erasure_switch(settings),
                verifier=verifier or verifier_from(settings),
            ),
        ),
        periodic=(
            PeriodicComponent(
                DISPATCH_JOB,
                dispatch_job(wiring.dispatch),
                interval_seconds=settings.notification_dispatch_interval_seconds,
            ),
            PeriodicComponent(
                RETENTION_JOB, retention_job(wiring.purge), next_run=daily_at(RETENTION_AT)
            ),
        ),
    )


def main() -> None:
    run_worker_process(
        NotificationSettings(service_name=SERVICE_NAME), components, version=__version__
    )


if __name__ == "__main__":
    main()
