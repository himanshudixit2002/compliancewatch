"""Send one notification now (``POST /send``): dedupe, consent, quiet hours, queue, deliver.

The order is the product rule. A dedupe key the store already holds means the business has had
this message and gets nothing. An address that has not opted in, or is suppressed, gets nothing
and nothing is stored. A template the channel does not have, or a value it needs and the
request does not give, is refused before anything is stored. Otherwise the notification is
queued like any other, due at once, or at the end of quiet hours (``deferred``, with
``scheduled_for``), and the dispatcher delivers it from the queue.

A send due now is leased to this call and handed straight to ``DispatchDue.dispatch``, alone,
outside the batching window. What the dispatcher makes of it is the outcome: ``sent`` with the
provider's message id, or ``failed`` with the channel's error. A failed notification stays
queued and the service retries it after the retry policy's backoff; the caller does not retry,
and sending the same request again is a ``duplicate``.

The address is normalised first (``normalise_address``): the consent of ``919876543210`` and
of ``+91 98765 43210`` is one record.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from domain_kernel.events import utc_now
from notification.application.consent import closed_reason, quiet_hours_for
from notification.application.dispatch import Delivery, DeliveryOutcome, DispatchDue
from notification.domain.addresses import normalise_address
from notification.domain.errors import UnknownChannelError
from notification.domain.model import NotificationRequest, Outcome, SendOutcome
from notification.domain.notification import Notification
from notification.domain.occasions import Occasion, OccasionKind, dedupe_key
from notification.domain.policy import WORK_LEASE
from notification.domain.preferences import DEFAULT_QUIET_HOURS, QuietHours
from notification.domain.repository import UnitOfWorkFactory, WorkEntry
from notification.domain.templates import render

OUTCOMES = {
    DeliveryOutcome.SENT: Outcome.SENT,
    DeliveryOutcome.RETRY: Outcome.FAILED,
    DeliveryOutcome.FAILED: Outcome.FAILED,
    DeliveryOutcome.SUPPRESSED: Outcome.NOT_OPTED_IN,
    DeliveryOutcome.DEFERRED: Outcome.DEFERRED,
    DeliveryOutcome.RESCHEDULED: Outcome.DEFERRED,
    DeliveryOutcome.SKIPPED: Outcome.DUPLICATE,
}
"""What the caller hears of each thing the dispatcher can make of the notification."""


class SendNow:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        dispatcher: DispatchDue,
        *,
        quiet_hours: QuietHours = DEFAULT_QUIET_HOURS,
        clock: Callable[[], datetime] = utc_now,
        lease: timedelta = WORK_LEASE,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._dispatcher = dispatcher
        self._quiet_hours = quiet_hours
        self._clock = clock
        self._lease = lease

    def run(self, request: NotificationRequest) -> SendOutcome:
        now = self._clock()
        address = normalise_address(request.channel, request.recipient)
        key = request.dedupe_key or dedupe_key(
            Occasion.manual(request.obligation_id, request.template_key),
            request.business_id,
            None,
            request.channel,
        )
        with self._unit_of_work(request.tenant_id) as unit:
            if unit.notifications.by_dedupe_key(key) is not None:
                return SendOutcome(Outcome.DUPLICATE, request.notification_id, key)
            preference = unit.preferences.get(request.channel, address)
            if preference is None or closed_reason(unit, request.channel, address):
                return SendOutcome(Outcome.NOT_OPTED_IN, request.notification_id, key)
            language = request.language or preference.language
            if not self._dispatcher.can_send(request.channel):
                raise UnknownChannelError(request.channel.value)
            # Refuses an unknown template or a missing value before anything is stored.
            render(
                request.template_key,
                request.channel,
                language,
                request.params,
                recipient=address,
                dedupe_key=key,
            )
            available_at = quiet_hours_for(preference, self._quiet_hours).next_allowed(now)
            notification = Notification.queue(
                notification_id=request.notification_id,
                tenant_id=request.tenant_id,
                business_id=request.business_id,
                obligation_id=request.obligation_id,
                recipient_id=None,
                channel=request.channel,
                address=address,
                occasion=OccasionKind.MANUAL,
                template_key=request.template_key,
                language=language,
                params=request.params,
                dedupe_key=key,
                now=now,
                available_at=available_at,
            )
            if not unit.notifications.add_if_absent(notification):
                return SendOutcome(Outcome.DUPLICATE, request.notification_id, key)
            due_now = available_at <= now
            entry = WorkEntry.of(notification, lease_until=now + self._lease if due_now else None)
            unit.work.add(entry)
        if not due_now:
            return SendOutcome(
                Outcome.DEFERRED,
                notification.id,
                key,
                scheduled_for=available_at,
                language=language,
            )
        (delivery,) = self._dispatcher.dispatch([entry], now)
        return _outcome(delivery, notification)


def _outcome(delivery: Delivery, notification: Notification) -> SendOutcome:
    outcome = OUTCOMES[delivery.outcome]
    return SendOutcome(
        outcome,
        notification.id,
        notification.dedupe_key,
        receipt=delivery.receipt,
        scheduled_for=delivery.available_at if outcome is Outcome.DEFERRED else None,
        language=notification.language,
    )
