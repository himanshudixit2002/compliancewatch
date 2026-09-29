"""Reconcile what the providers report after they took a message, and when people wrote to us.

``ReconcileReceipts.run(channel, receipts, inbound)`` takes the reports the WhatsApp bot
forwards from Meta's webhook (and, for email, the provider's feedback):

1. Every inbound time is recorded against its normalised address
   (``PreferenceRepository.record_inbound``): the person wrote to us then, which opens the
   24-hour WhatsApp customer service window during which the dispatcher may send free text. An
   address that cannot be normalised is skipped.
2. Every receipt finds its tenant through the work index by the provider's message id, and in a
   unit of work of that tenant the notifications the message carried
   (``NotificationRepository.by_provider_message``; the members of a batch or a digest share
   it). ``Notification.apply_receipt`` moves each on: delivered and read only forward, and a
   failure fails one that was sent and not yet delivered. A failure publishes
   ``notification.failed`` and queues the fallback on the recipient's next open address, due at
   once (``application.fallback``), as the dispatcher does after its last attempt.
3. A message id no notification carries (the bot's own replies, or a notification the retention
   sweep removed) is counted as unknown and otherwise ignored; so is a report that changes
   nothing, such as a late ``delivered`` after ``read``.
4. Every closed address (a permanent bounce or a complaint the email provider reported) is
   suppressed for every tenant (``SuppressionRepository.add``), whether or not its message was
   matched, so nothing more is sent to it until support lifts the suppression.

Each report is counted (``notification_receipts_total``). The tenant's receipts commit in one
unit, so a redelivered webhook applies nothing twice.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from notification.application.fallback import queue_fallback
from notification.domain.addresses import normalise_address
from notification.domain.errors import InvalidAddressError
from notification.domain.ports import NO_METRICS, DeliveryMetrics, ReceiptResult
from notification.domain.preferences import Suppression, SuppressionReason
from notification.domain.receipts import Receipt
from notification.domain.repository import UnitOfWork, UnitOfWorkFactory, WorkIndex


@dataclass(frozen=True, slots=True)
class InboundTime:
    """The address wrote to us at ``at``, as the channel knows it (normalised here)."""

    address: str
    at: datetime


@dataclass(frozen=True, slots=True)
class ClosedAddress:
    """The provider reported that the address must not get mail any more."""

    address: str
    reason: SuppressionReason
    at: datetime
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Reconciled:
    """What one batch of reports did: receipts applied, receipts that changed nothing, receipts
    for messages no notification carries, inbound times recorded and addresses suppressed."""

    applied: int = 0
    unchanged: int = 0
    unknown: int = 0
    inbound: int = 0
    suppressed: int = 0


class ReconcileReceipts:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        work_index: WorkIndex,
        *,
        metrics: DeliveryMetrics = NO_METRICS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._work_index = work_index
        self._metrics = metrics
        self._clock = clock

    def run(
        self,
        channel: Channel,
        receipts: Sequence[Receipt] = (),
        inbound: Sequence[InboundTime] = (),
        closed: Sequence[ClosedAddress] = (),
    ) -> Reconciled:
        recorded, suppressed = self._record_addresses(channel, inbound, closed)
        by_tenant: dict[TenantId, list[Receipt]] = {}
        unknown = 0
        for receipt in receipts:
            tenant_id = self._work_index.tenant_for_provider_message(receipt.provider_message_id)
            if tenant_id is None:
                unknown += 1
                self._metrics.receipt(channel, receipt.kind, ReceiptResult.UNKNOWN)
                continue
            by_tenant.setdefault(tenant_id, []).append(receipt)
        applied = unchanged = 0
        for tenant_id, tenant_receipts in by_tenant.items():
            with self._unit_of_work(tenant_id) as unit:
                for receipt in sorted(tenant_receipts, key=lambda receipt: receipt.at):
                    result = self._apply(unit, channel, receipt)
                    self._metrics.receipt(channel, receipt.kind, result)
                    applied += result is ReceiptResult.APPLIED
                    unchanged += result is ReceiptResult.UNCHANGED
                    unknown += result is ReceiptResult.UNKNOWN
        return Reconciled(applied, unchanged, unknown, recorded, suppressed)

    def _record_addresses(
        self, channel: Channel, inbound: Sequence[InboundTime], closed: Sequence[ClosedAddress]
    ) -> tuple[int, int]:
        """Record the inbound times and the suppressions in one shared unit; an address that
        cannot be normalised is skipped."""
        wrote = [
            (address, item.at)
            for item in inbound
            if (address := _normalised(channel, item.address)) is not None
        ]
        suppressions = [
            Suppression(channel, address, item.reason, item.at, detail=item.detail)
            for item in closed
            if (address := _normalised(channel, item.address)) is not None
        ]
        if not wrote and not suppressions:
            return 0, 0
        with self._unit_of_work.shared() as unit:
            for address, at in wrote:
                unit.preferences.record_inbound(channel, address, at)
            for suppression in suppressions:
                unit.suppressions.add(suppression)
        return len(wrote), len(suppressions)

    def _apply(self, unit: UnitOfWork, channel: Channel, receipt: Receipt) -> ReceiptResult:
        carried = unit.notifications.by_provider_message(receipt.provider_message_id)
        if not carried:
            return ReceiptResult.UNKNOWN
        result = ReceiptResult.UNCHANGED
        for notification in carried:
            if notification.channel is not channel:
                continue
            fallback = None
            if receipt.is_failure and notification.accepts_failure:
                recipient = (
                    None
                    if notification.recipient_id is None
                    else unit.recipients.get(notification.recipient_id)
                )
                fallback = queue_fallback(unit, notification, recipient, self._clock())
            updated, events = notification.apply_receipt(
                receipt.kind, receipt.at, error=receipt.error, fallback=fallback is not None
            )
            if updated is notification:
                continue
            unit.notifications.save(updated)
            for event in events:
                unit.events.publish(event)
            result = ReceiptResult.APPLIED
        return result


def _normalised(channel: Channel, address: str) -> str | None:
    try:
        return normalise_address(channel, address)
    except InvalidAddressError:
        return None
