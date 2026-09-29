"""Send what is due: claim, check, gather, fill, deliver, record.

``DispatchDue.run()`` claims the work entries due now (``WorkIndex.claim``, with a lease, so two
dispatchers never take one entry) and handles them tenant by tenant:

1. In a unit of work of the tenant, each notification is read back; one that is no longer
   pending only has its entry completed. The address is checked again, since consent can be
   withdrawn after queueing: an address that opted out or was suppressed meanwhile ends the
   notification as suppressed. In quiet hours the notification is due again when they end.
2. The rest is gathered per recipient, channel, address and business. One notification keeps
   its own template; two or more go as one ``batch_summary`` (``digest.compose``). A send
   addressed straight to a number (``POST /send``) always goes alone. Notifications held for a
   recipient's digest are gathered per recipient, channel and address across businesses, and go
   as one ``daily_digest``, or ``ca_digest`` for a CA firm's people, even when there is only
   one. A dispatcher gathers only the entries it claimed, so a digest longer than one claim
   (``DEFAULT_CLAIM_LIMIT``) goes out as more than one message.
3. Outside any transaction the values are filled (``values.message_values``) with the rule
   version's facts, which the ``RuleVersionReader`` reads from the rulebook and caches, and with
   links into the web app (``CW_WEB_BASE_URL``). When the rulebook cannot answer, the
   notifications are due again a minute later and no attempt is spent.
4. The channel delivers the message.
5. In a second unit, a sent message marks each notification sent, completes its entry under
   the provider's message id (receipts find the tenant through it) and publishes
   ``notification.sent``. A failed one spends an attempt: the notification is due again after
   the retry policy's backoff (60 s, then 300 s), and the last attempt fails it and queues a
   fallback to the recipient's next open address on another channel (``fallback_of``); a
   fallback does not fall back again. Every failed attempt publishes ``notification.failed``,
   whose ``will_retry`` says whether a retry or a fallback follows. A message that cannot be
   rendered (a missing value, a template the channel does not have, a value that is not what
   its template expects) fails without retries.

A notification that another dispatcher sent meanwhile, because this one's lease ran out while
it was sending, is left as it is and counted (``notification_duplicate_sent_total``).

``SendNow`` serves ``POST /send``: it queues the one notification, due at once (or when quiet
hours end), leased to itself, and hands it to ``DispatchDue.dispatch``.
"""

import hashlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, RuleVersionId, TenantId
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from domain_kernel.protocols import NotificationChannel
from notification.application.consent import closed_reason, open_in, quiet_hours_for
from notification.domain.digest import SummaryItem, compose
from notification.domain.errors import (
    DependencyUnavailableError,
    MissingPlaceholderError,
    UnknownTemplateError,
)
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import SENT_STATES, DeliveryState, Notification
from notification.domain.occasions import OccasionKind, fallback_key
from notification.domain.policy import (
    DEFAULT_BATCH_POLICY,
    DEFAULT_RETRY_POLICY,
    WORK_LEASE,
    BatchPolicy,
    RetryPolicy,
)
from notification.domain.ports import (
    NO_METRICS,
    AttemptResult,
    DeliveryMetrics,
    RuleVersionFacts,
    RuleVersionReader,
)
from notification.domain.preferences import DEFAULT_QUIET_HOURS, QuietHours
from notification.domain.recipients import Recipient
from notification.domain.repository import UnitOfWork, UnitOfWorkFactory, WorkEntry, WorkIndex
from notification.domain.templates import render
from notification.domain.values import message_values

DEPENDENCY_BACKOFF = timedelta(seconds=60)
"""How long notifications wait when the rulebook could not fill them."""
NO_RETRIES = RetryPolicy(max_attempts=1)
"""The policy of a message that cannot be rendered: another attempt would fail the same way."""
DEFAULT_CLAIM_LIMIT = 100


class DeliveryOutcome(StrEnum):
    SENT = "sent"
    RETRY = "retry"
    """The attempt failed; the notifications are due again at ``available_at``."""
    FAILED = "failed"
    """The last attempt failed."""
    SUPPRESSED = "suppressed"
    DEFERRED = "deferred"
    """Quiet hours: due again at ``available_at``."""
    RESCHEDULED = "rescheduled"
    """The rulebook could not answer: due again at ``available_at``, no attempt spent."""
    SKIPPED = "skipped"
    """No longer pending when claimed."""


@dataclass(frozen=True, slots=True)
class Delivery:
    """What became of one message and the notifications it carried."""

    notification_ids: tuple[NotificationId, ...]
    outcome: DeliveryOutcome
    receipt: DeliveryReceipt | None = None
    available_at: datetime | None = None


def obligation_link(base_url: str, obligation_id: ObligationId) -> str:
    return f"{base_url.rstrip('/')}/obligations/{obligation_id}"


def business_link(base_url: str, business_id: BusinessId) -> str:
    return f"{base_url.rstrip('/')}/obligations?business_id={business_id}"


def summary_link(base_url: str, business_ids: Sequence[BusinessId]) -> str:
    """The link of a summary: the business's obligations, or every obligation the person can see
    when the summary spans businesses (a CA firm's digest)."""
    distinct = list(dict.fromkeys(business_ids))
    if len(distinct) == 1:
        return business_link(base_url, distinct[0])
    return f"{base_url.rstrip('/')}/obligations"


@dataclass(slots=True)
class _Batch:
    """Notifications that go out as one message, with their claimed entries."""

    recipient: Recipient | None
    digest: bool = False
    """The notifications were held for the recipient's digest."""
    entries: list[WorkEntry] = field(default_factory=list)
    members: list[Notification] = field(default_factory=list)

    def add(self, entry: WorkEntry, notification: Notification) -> None:
        """Add the notification, keeping the batch in the order the notifications were made."""
        pairs = sorted(
            [*self.pairs(), (entry, notification)],
            key=lambda pair: (pair[1].created_at, pair[1].id.value),
        )
        self.entries = [entry for entry, _ in pairs]
        self.members = [member for _, member in pairs]

    @property
    def first(self) -> Notification:
        return self.members[0]

    @property
    def ids(self) -> tuple[NotificationId, ...]:
        return tuple(notification.id for notification in self.members)

    def pairs(self) -> Iterator[tuple[WorkEntry, Notification]]:
        return zip(self.entries, self.members, strict=True)


@dataclass(frozen=True, slots=True)
class _Rendered:
    message: RenderedMessage
    values: Mapping[NotificationId, Mapping[str, object]]


class DispatchDue:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        work_index: WorkIndex,
        channels: Mapping[Channel, NotificationChannel],
        *,
        rules: RuleVersionReader,
        web_base_url: str,
        quiet_hours: QuietHours = DEFAULT_QUIET_HOURS,
        retry: RetryPolicy = DEFAULT_RETRY_POLICY,
        batch: BatchPolicy = DEFAULT_BATCH_POLICY,
        metrics: DeliveryMetrics = NO_METRICS,
        clock: Callable[[], datetime] = utc_now,
        lease: timedelta = WORK_LEASE,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._work_index = work_index
        self._channels = channels
        self._rules = rules
        self._web_base_url = web_base_url
        self._quiet_hours = quiet_hours
        self._retry = retry
        self._batch = batch
        self._metrics = metrics
        self._clock = clock
        self._lease = lease

    def can_send(self, channel: Channel) -> bool:
        return channel in self._channels

    def run(self, *, limit: int = DEFAULT_CLAIM_LIMIT) -> tuple[Delivery, ...]:
        """Claim what is due now, at most ``limit`` entries, and send it."""
        now = self._clock()
        return self.dispatch(self._work_index.claim(limit=limit, now=now, lease=self._lease), now)

    def dispatch(self, entries: Sequence[WorkEntry], now: datetime) -> tuple[Delivery, ...]:
        """Send the notifications of ``entries``, which the caller holds leased."""
        by_tenant: dict[TenantId, list[WorkEntry]] = {}
        for entry in entries:
            by_tenant.setdefault(entry.tenant_id, []).append(entry)
        deliveries: list[Delivery] = []
        for tenant_id, tenant_entries in by_tenant.items():
            with self._unit_of_work(tenant_id) as unit:
                batches = self._prepare(unit, tenant_entries, now, deliveries)
            deliveries.extend(self._send(tenant_id, batch, now) for batch in batches)
        return tuple(deliveries)

    def _prepare(
        self,
        unit: UnitOfWork,
        entries: Sequence[WorkEntry],
        now: datetime,
        deliveries: list[Delivery],
    ) -> list[_Batch]:
        """Read the notifications back, settle the ones that cannot go now, gather the rest."""
        recipients: dict[RecipientId, Recipient | None] = {}
        groups: dict[tuple[object, ...], _Batch] = {}
        for entry in entries:
            notification = unit.notifications.get(entry.id)
            if notification is None or not notification.is_pending:
                message_id = "" if notification is None else notification.provider_message_id
                unit.work.complete(entry.id, provider_message_id=message_id)
                deliveries.append(Delivery((entry.id,), DeliveryOutcome.SKIPPED))
                continue
            recipient = None
            if notification.recipient_id is not None:
                if notification.recipient_id not in recipients:
                    recipients[notification.recipient_id] = unit.recipients.get(
                        notification.recipient_id
                    )
                recipient = recipients[notification.recipient_id]
            digest = recipient is not None and notification.state is DeliveryState.DIGEST_PENDING
            together: object = notification.id if recipient is None else recipient.id
            scope: object = "digest" if digest else notification.business_id
            key = (together, notification.channel, notification.address, scope)
            groups.setdefault(key, _Batch(recipient, digest)).add(entry, notification)
        ready: list[_Batch] = []
        for batch in groups.values():
            channel, address = batch.first.channel, batch.first.address
            closed = closed_reason(unit, channel, address)
            if closed:
                for notification in batch.members:
                    suppressed, _ = notification.suppress(closed, now)
                    unit.notifications.save(suppressed)
                    unit.work.complete(notification.id)
                    self._metrics.attempted(channel, AttemptResult.SUPPRESSED)
                deliveries.append(Delivery(batch.ids, DeliveryOutcome.SUPPRESSED))
                continue
            quiet = quiet_hours_for(unit.preferences.get(channel, address), self._quiet_hours)
            if quiet.is_quiet(now):
                until = quiet.next_allowed(now)
                _put_back(unit, batch.members, until, now)
                deliveries.append(Delivery(batch.ids, DeliveryOutcome.DEFERRED, available_at=until))
                continue
            ready.append(batch)
        return ready

    def _send(self, tenant_id: TenantId, batch: _Batch, now: datetime) -> Delivery:
        try:
            rendered = self._render(batch)
        except DependencyUnavailableError:
            later = now + DEPENDENCY_BACKOFF
            with self._unit_of_work(tenant_id) as unit:
                current = [unit.notifications.get(n.id) for n in batch.members]
                _put_back(unit, [n for n in current if n is not None and n.is_pending], later, now)
            return Delivery(batch.ids, DeliveryOutcome.RESCHEDULED, available_at=later)
        except (MissingPlaceholderError, UnknownTemplateError, InvariantViolationError) as exc:
            receipt = DeliveryReceipt(DeliveryStatus.FAILED, now, error=f"not rendered: {exc}")
            return self._record(tenant_id, batch, receipt, {}, now, NO_RETRIES)
        adapter = self._channels.get(batch.first.channel)
        if adapter is None:
            error = f"no channel adapter for {batch.first.channel.value}"
            receipt = DeliveryReceipt(DeliveryStatus.FAILED, now, error=error)
        else:
            receipt = adapter.send(rendered.message)
        return self._record(tenant_id, batch, receipt, rendered.values, now, self._retry)

    def _render(self, batch: _Batch) -> _Rendered:
        first = batch.first
        filled = {
            notification.id: self._values(notification, batch) for notification in batch.members
        }
        if len(batch.members) == 1 and not batch.digest:
            key, values = filled[first.id]
            message = render(
                key,
                first.channel,
                first.language,
                values,
                recipient=first.address,
                dedupe_key=first.dedupe_key,
            )
            return _Rendered(message, {first.id: values})
        assert batch.recipient is not None, "only a recipient's notifications are gathered"
        composition = compose(
            [
                SummaryItem(notification.business_id, *filled[notification.id])
                for notification in batch.members
            ],
            first.channel,
            batch.recipient,
            digest=batch.digest,
            language=first.language,
            policy=self._batch,
        )
        link = summary_link(self._web_base_url, [n.business_id for n in batch.members])
        message = render(
            composition.template_key,
            first.channel,
            first.language,
            {**composition.params, "link": link},
            recipient=first.address,
            dedupe_key=_batch_key(batch.members),
        )
        return _Rendered(message, {id_: values for id_, (_, values) in filled.items()})

    def _values(self, notification: Notification, batch: _Batch) -> tuple[str, dict[str, object]]:
        if notification.occasion is OccasionKind.MANUAL:
            return notification.template_key, dict(notification.params)
        params = notification.params
        label = (
            "" if batch.recipient is None else batch.recipient.label_for(notification.business_id)
        )
        return message_values(
            notification.template_key,
            notification.language,
            params,
            business_name=label,
            link=obligation_link(self._web_base_url, notification.obligation_id),
            rule=self._facts(params.get("rule_version_id")),
            source=self._facts(params.get("source_rule_version_id")),
        )

    def _facts(self, value: object) -> RuleVersionFacts | None:
        if not value:
            return None
        try:
            rule_version_id = RuleVersionId(UUID(str(value)))
        except ValueError:
            return None
        return self._rules.get(rule_version_id)

    def _record(
        self,
        tenant_id: TenantId,
        batch: _Batch,
        receipt: DeliveryReceipt,
        values: Mapping[NotificationId, Mapping[str, object]],
        now: datetime,
        policy: RetryPolicy,
    ) -> Delivery:
        with self._unit_of_work(tenant_id) as unit:
            if receipt.status is DeliveryStatus.SENT:
                return self._record_sent(unit, batch, receipt, values)
            return self._record_failed(unit, batch, receipt, now, policy)

    def _record_sent(
        self,
        unit: UnitOfWork,
        batch: _Batch,
        receipt: DeliveryReceipt,
        values: Mapping[NotificationId, Mapping[str, object]],
    ) -> Delivery:
        dispatch_id = DispatchId.new()
        for entry, queued in batch.pairs():
            current = unit.notifications.get(queued.id)
            if current is None:
                continue
            if not current.is_pending:
                if current.state in SENT_STATES:
                    self._metrics.duplicate_sent(current.channel)
                continue
            sent, events = current.sent(
                dispatch_id,
                receipt.provider_message_id,
                receipt.at,
                params={**current.params, **values.get(current.id, {})},
            )
            unit.notifications.save(sent)
            unit.work.complete(sent.id, provider_message_id=receipt.provider_message_id)
            for event in events:
                unit.events.publish(event)
            self._metrics.attempted(sent.channel, AttemptResult.SENT)
            lag = (receipt.at - entry.available_at).total_seconds()
            self._metrics.delivery_lag(sent.channel, max(lag, 0.0))
        return Delivery(batch.ids, DeliveryOutcome.SENT, receipt)

    def _record_failed(
        self,
        unit: UnitOfWork,
        batch: _Batch,
        receipt: DeliveryReceipt,
        now: datetime,
        policy: RetryPolicy,
    ) -> Delivery:
        retry_at: datetime | None = None
        for queued in batch.members:
            current = unit.notifications.get(queued.id)
            if current is None or not current.is_pending:
                continue
            fallback = None
            if policy.is_final(current.attempts + 1):
                fallback = self._fallback(unit, current, batch.recipient, now)
            failed, events, retry_at = current.attempt_failed(
                receipt.error, now, policy, fallback=fallback is not None
            )
            unit.notifications.save(failed)
            if retry_at is None:
                unit.work.complete(failed.id)
            else:
                unit.work.reschedule(failed.id, retry_at)
            for event in events:
                unit.events.publish(event)
            result = AttemptResult.FAILED if retry_at is None else AttemptResult.RETRY
            self._metrics.attempted(failed.channel, result)
        outcome = DeliveryOutcome.FAILED if retry_at is None else DeliveryOutcome.RETRY
        return Delivery(batch.ids, outcome, receipt, available_at=retry_at)

    def _fallback(
        self,
        unit: UnitOfWork,
        failed: Notification,
        recipient: Recipient | None,
        now: datetime,
    ) -> Notification | None:
        """Queue the notification again on the recipient's next open address, due now; one held
        for the digest goes in the digest on that address."""
        if recipient is None or failed.fallback_of is not None:
            return None
        address = recipient.fallback_after(failed.channel, open_in(unit))
        if address is None:
            return None
        fallback = Notification.queue(
            tenant_id=failed.tenant_id,
            business_id=failed.business_id,
            obligation_id=failed.obligation_id,
            recipient_id=failed.recipient_id,
            channel=address.channel,
            address=address.address,
            occasion=failed.occasion,
            template_key=failed.template_key,
            language=failed.language,
            params=failed.params,
            dedupe_key=fallback_key(failed.dedupe_key, address.channel),
            now=now,
            digest=failed.state is DeliveryState.DIGEST_PENDING,
            fallback_of=failed.id,
        )
        if not unit.notifications.add_if_absent(fallback):
            return None
        unit.work.add(WorkEntry.of(fallback))
        return fallback


def _put_back(
    unit: UnitOfWork, notifications: Sequence[Notification], until: datetime, now: datetime
) -> None:
    """Due again at ``until``, with no attempt spent."""
    for notification in notifications:
        deferred, _ = notification.defer(until, now)
        unit.notifications.save(deferred)
        unit.work.reschedule(notification.id, until)


def _batch_key(notifications: Sequence[Notification]) -> DedupeKey:
    """The key of a message that carries several notifications: from theirs, in order."""
    material = "|".join(notification.dedupe_key.value for notification in notifications)
    return DedupeKey(hashlib.sha256(material.encode("utf-8")).hexdigest())
