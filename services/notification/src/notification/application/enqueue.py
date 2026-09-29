"""Queue one obligation event's notification for each recipient of the business.

For every recipient that follows the business (``RecipientRepository.for_business``):

1. The first open address in the recipient's order is chosen: opted in and not suppressed. A
   recipient with none gets nothing.
2. The occasion's key for the recipient and that address's channel (``occasions.dedupe_key``)
   is written with the notification, and the store keeps it unique: a redelivered event, or a
   second event about the same occasion, finds the key taken, is counted as a duplicate and
   queues nothing.
3. An event that does not name the obligation's title, such as a closure, takes it from the
   obligation's earlier notification.
4. The notification is due at the end of the batching window. One queued for the same person,
   channel and business while an earlier one still waits joins it and is due with it, so the
   dispatcher sends them together as one summary.
5. Its work queue entry is written in the same transaction.

``run(notice)`` opens a unit of work of the notice's tenant; ``run_in(unit, notice)`` works in
one the caller holds, such as the consumer's inbox transaction, so the notifications and the
inbox row commit together.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId
from notification.application.consent import open_in
from notification.domain.ids import RecipientId
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import dedupe_key
from notification.domain.policy import DEFAULT_BATCH_POLICY, BatchPolicy
from notification.domain.ports import NO_METRICS, DeliveryMetrics, QueueResult
from notification.domain.repository import UnitOfWork, UnitOfWorkFactory, WorkEntry
from notification.domain.routing import ObligationNotice


@dataclass(frozen=True, slots=True)
class Enqueued:
    """What one notice queued: notifications written, duplicates found, and recipients left out
    because none of their addresses is open."""

    queued: int = 0
    duplicates: int = 0
    unreachable: int = 0


class EnqueueNotifications:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        batch: BatchPolicy = DEFAULT_BATCH_POLICY,
        metrics: DeliveryMetrics = NO_METRICS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._batch = batch
        self._metrics = metrics
        self._clock = clock

    def run(self, notice: ObligationNotice) -> Enqueued:
        with self._unit_of_work(notice.tenant_id) as unit:
            return self.run_in(unit, notice)

    def run_in(self, unit: UnitOfWork, notice: ObligationNotice) -> Enqueued:
        if unit.tenant_id != notice.tenant_id:
            raise InvariantViolationError("the notice belongs to another tenant than the unit")
        now = self._clock()
        is_open = open_in(unit)
        params = dict(notice.params)
        if not params.get("title"):
            earlier = unit.notifications.latest_params(notice.occasion.obligation_id)
            if earlier and earlier.get("title"):
                params["title"] = earlier["title"]
        queued = duplicates = unreachable = 0
        for recipient in unit.recipients.for_business(notice.business_id):
            address = recipient.primary_address(is_open)
            if address is None:
                unreachable += 1
                continue
            notification = Notification.queue(
                tenant_id=notice.tenant_id,
                business_id=notice.business_id,
                obligation_id=notice.occasion.obligation_id,
                recipient_id=recipient.id,
                channel=address.channel,
                address=address.address,
                occasion=notice.occasion.kind,
                template_key=notice.template_key,
                language=recipient.language,
                params=params,
                dedupe_key=dedupe_key(
                    notice.occasion, notice.business_id, recipient.id, address.channel
                ),
                now=now,
                available_at=self._due_at(
                    unit, recipient.id, address.channel, notice.business_id, now
                ),
            )
            if unit.notifications.add_if_absent(notification):
                unit.work.add(WorkEntry.of(notification))
                queued += 1
                self._metrics.enqueued(address.channel, QueueResult.QUEUED)
            else:
                duplicates += 1
                self._metrics.enqueued(address.channel, QueueResult.DUPLICATE)
        return Enqueued(queued, duplicates, unreachable)

    def _due_at(
        self,
        unit: UnitOfWork,
        recipient_id: RecipientId,
        channel: Channel,
        business_id: BusinessId,
        now: datetime,
    ) -> datetime:
        """The end of the window, or the time of the batch still waiting for the recipient."""
        end = now + self._batch.window
        waiting = [
            notification.available_at
            for notification in unit.notifications.due_for(recipient_id, channel, end)
            if notification.state is DeliveryState.QUEUED
            and notification.business_id == business_id
            and notification.available_at > now
        ]
        return min(waiting, default=end)
