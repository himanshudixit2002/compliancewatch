"""Send one notification: dedupe, consent, quiet hours, render, deliver, record, publish.

The order is the product rule. A dedupe key already in the sent log means the business has
had this message and gets nothing. A recipient who has not opted in gets nothing and no event
(there is nothing to retry). Quiet hours defer: the outcome carries ``scheduled_for`` and the
caller (the digest scheduler, when it exists) tries again then. Delivery goes through the
channel adapter behind ``NotificationChannel``; a sent receipt becomes ``notification.sent``,
a failed one ``notification.failed`` with ``will_retry`` left to the caller's retry policy.
"""

from collections.abc import Callable, Mapping
from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import utc_now
from domain_kernel.notifications import DeliveryStatus
from domain_kernel.protocols import NotificationChannel
from notification.domain.errors import UnknownChannelError
from notification.domain.events import NotificationFailed, NotificationSent
from notification.domain.model import EventSink, NotificationRequest, Outcome, SendOutcome, SentLog
from notification.domain.preferences import (
    DEFAULT_QUIET_HOURS,
    ChannelPreference,
    PreferenceRepository,
    QuietHours,
)
from notification.domain.templates import render


class SendNotification:
    def __init__(
        self,
        preferences: PreferenceRepository,
        sent_log: SentLog,
        events: EventSink,
        channels: Mapping[Channel, NotificationChannel],
        *,
        quiet_hours: QuietHours = DEFAULT_QUIET_HOURS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._preferences = preferences
        self._sent_log = sent_log
        self._events = events
        self._channels = channels
        self._quiet_hours = quiet_hours
        self._clock = clock

    def run(self, request: NotificationRequest, *, attempt: int = 1) -> SendOutcome:
        now = self._clock()
        key = request.dedupe_key or _key_for(request)
        if self._sent_log.seen(key):
            return SendOutcome(Outcome.DUPLICATE, request.notification_id, key)
        preference = self._preferences.get(request.channel, request.recipient)
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
            recipient=request.recipient,
            dedupe_key=key,
        )
        receipt = channel.send(message)
        if receipt.status is DeliveryStatus.SENT:
            self._sent_log.record(key, receipt.at)
            self._events.publish(
                NotificationSent(
                    tenant_id=request.tenant_id,
                    notification_id=request.notification_id,
                    obligation_id=request.obligation_id,
                    business_id=request.business_id,
                    channel=request.channel,
                    dedupe_key=key.value,
                    sent_at=receipt.at,
                    language=message.language,
                    provider_message_id=receipt.provider_message_id,
                )
            )
            return SendOutcome(
                Outcome.SENT, request.notification_id, key, receipt, language=language
            )
        self._events.publish(
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


MAX_ATTEMPTS = 3


def _key_for(request: NotificationRequest) -> DedupeKey:
    import hashlib

    material = (
        f"{request.obligation_id}|{request.business_id}|{request.channel.value}|"
        f"{request.template_key}"
    )
    return DedupeKey(hashlib.sha256(material.encode("utf-8")).hexdigest())


def _quiet_hours(preference: ChannelPreference, default: QuietHours) -> QuietHours:
    return preference.quiet_hours if preference.quiet_hours != DEFAULT_QUIET_HOURS else default
