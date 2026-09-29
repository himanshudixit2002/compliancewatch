"""Send one notification now: dedupe, consent, quiet hours, render, deliver, record, publish.

The order is the product rule. A dedupe key the store already holds means the business has had
this message and gets nothing. A recipient who has not opted in gets nothing and no event
(there is nothing to retry). Quiet hours defer: the outcome carries ``scheduled_for`` and the
caller tries again then. Delivery goes through the channel adapter behind
``NotificationChannel``, outside any transaction. A sent receipt is stored as a sent
notification, with its work queue entry completed under the provider's message id so receipts
find their tenant, and publishes ``notification.sent`` through the outbox in the same
transaction. A failed one publishes ``notification.failed``, with ``will_retry`` from the
caller's attempt number, and stores nothing, so the caller's retry is not a duplicate.

The address is normalised first (``normalise_address``): the consent of ``919876543210`` and
of ``+91 98765 43210`` is one record.
"""

from collections.abc import Callable, Mapping
from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import utc_now
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from domain_kernel.protocols import NotificationChannel
from notification.domain.addresses import normalise_address
from notification.domain.errors import UnknownChannelError
from notification.domain.events import NotificationFailed
from notification.domain.ids import DispatchId
from notification.domain.model import NotificationRequest, Outcome, SendOutcome
from notification.domain.notification import Notification
from notification.domain.occasions import Occasion, OccasionKind, dedupe_key
from notification.domain.policy import DEFAULT_RETRY_POLICY
from notification.domain.preferences import (
    DEFAULT_QUIET_HOURS,
    ChannelPreference,
    QuietHours,
)
from notification.domain.repository import UnitOfWorkFactory, WorkEntry
from notification.domain.templates import render

MAX_ATTEMPTS = DEFAULT_RETRY_POLICY.max_attempts


class SendNotification:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        channels: Mapping[Channel, NotificationChannel],
        *,
        quiet_hours: QuietHours = DEFAULT_QUIET_HOURS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._channels = channels
        self._quiet_hours = quiet_hours
        self._clock = clock

    def run(self, request: NotificationRequest, *, attempt: int = 1) -> SendOutcome:
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
        if preference is None or not preference.opted_in:
            return SendOutcome(Outcome.NOT_OPTED_IN, request.notification_id, key)
        language = request.language or preference.language
        quiet = _quiet_hours(preference, self._quiet_hours)
        if quiet.is_quiet(now):
            return SendOutcome(
                Outcome.DEFERRED,
                request.notification_id,
                key,
                scheduled_for=quiet.next_allowed(now),
                language=language,
            )
        channel = self._channels.get(request.channel)
        if channel is None:
            raise UnknownChannelError(request.channel.value)
        message = render(
            request.template_key,
            request.channel,
            language,
            request.params,
            recipient=address,
            dedupe_key=key,
        )
        receipt = channel.send(message)
        if receipt.status is DeliveryStatus.SENT:
            self._record_sent(request, message, receipt, key, now)
            return SendOutcome(
                Outcome.SENT, request.notification_id, key, receipt, language=language
            )
        with self._unit_of_work(request.tenant_id) as unit:
            unit.events.publish(
                NotificationFailed(
                    tenant_id=request.tenant_id,
                    notification_id=request.notification_id,
                    obligation_id=request.obligation_id,
                    business_id=request.business_id,
                    channel=request.channel,
                    dedupe_key=key.value,
                    error=receipt.error,
                    attempts=attempt,
                    will_retry=attempt < MAX_ATTEMPTS,
                    failed_at=receipt.at,
                )
            )
        return SendOutcome(Outcome.FAILED, request.notification_id, key, receipt, language=language)

    def _record_sent(
        self,
        request: NotificationRequest,
        message: RenderedMessage,
        receipt: DeliveryReceipt,
        key: DedupeKey,
        now: datetime,
    ) -> None:
        queued = Notification.queue(
            notification_id=request.notification_id,
            tenant_id=request.tenant_id,
            business_id=request.business_id,
            obligation_id=request.obligation_id,
            recipient_id=None,
            channel=request.channel,
            address=message.recipient,
            occasion=OccasionKind.MANUAL,
            template_key=request.template_key,
            language=message.language,
            params=request.params,
            dedupe_key=key,
            now=now,
        )
        sent, events = queued.sent(DispatchId.new(), receipt.provider_message_id, receipt.at)
        with self._unit_of_work(request.tenant_id) as unit:
            # A concurrent send of the same key that recorded first has published the event;
            # this delivery went out as well, and nothing more is written for it.
            if not unit.notifications.add_if_absent(sent):
                return
            unit.work.add(WorkEntry.of(queued))
            unit.work.complete(sent.id, provider_message_id=receipt.provider_message_id)
            for event in events:
                unit.events.publish(event)


def _quiet_hours(preference: ChannelPreference, default: QuietHours) -> QuietHours:
    return preference.quiet_hours if preference.quiet_hours != DEFAULT_QUIET_HOURS else default
