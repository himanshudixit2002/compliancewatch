"""One notification to one address, from the moment it is queued to its last receipt.

A notification is created queued (or waiting for the recipient's digest) with the moment it may
go out, ``available_at``. Its transitions are pure: each returns the changed notification and
the events the change publishes, and the caller saves both in one unit of work.

- ``sent`` records a delivery the channel accepted and publishes ``notification.sent``.
- ``attempt_failed`` records a failed attempt. While the retry policy allows another, the
  notification stays pending until the backoff has passed; the last one fails it. Every failed
  attempt publishes ``notification.failed``, whose ``will_retry`` says whether anything more
  will be tried: a retry, or on the last attempt a fallback to the recipient's next address.
- ``defer`` moves ``available_at`` (quiet hours); ``suppress`` ends a notification that may not
  go out any more (an opt-out or a suppressed address between queueing and sending).
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Self

from domain_kernel._validation import (
    freeze_mapping,
    require_aware,
    require_bool,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from notification.domain.events import NotificationFailed, NotificationSent
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.occasions import OccasionKind
from notification.domain.policy import RetryPolicy


class DeliveryState(StrEnum):
    QUEUED = "queued"
    DIGEST_PENDING = "digest_pending"
    """Held for the recipient's daily digest."""
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    """Not sent: the address was closed after the notification was queued."""


PENDING_STATES = frozenset({DeliveryState.QUEUED, DeliveryState.DIGEST_PENDING})
"""States of a notification that has still to go out."""
SENT_STATES = frozenset({DeliveryState.SENT, DeliveryState.DELIVERED, DeliveryState.READ})
"""States of a notification the channel accepted."""

type Transition = tuple["Notification", tuple[DomainEvent, ...]]
type FailedAttempt = tuple["Notification", tuple[DomainEvent, ...], datetime | None]
"""The notification, its events, and when it is tried again (None after the last attempt)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Notification:
    id: NotificationId
    tenant_id: TenantId
    business_id: BusinessId
    obligation_id: ObligationId
    recipient_id: RecipientId | None
    """None for a send addressed straight to a number or mailbox (``POST /send``)."""
    channel: Channel
    address: str
    """Normalised (``normalise_address``)."""
    occasion: OccasionKind
    template_key: str
    language: str
    params: Mapping[str, object] = field(hash=False)
    """The template's values: strings, numbers, booleans, lists and objects of those."""
    dedupe_key: DedupeKey
    state: DeliveryState
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    attempts: int = 0
    """Delivery attempts made so far."""
    dispatch_id: DispatchId | None = None
    provider_message_id: str = ""
    error: str = ""
    """Why the last attempt failed or why the notification was suppressed; '' otherwise."""
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    failed_at: datetime | None = None
    fallback_of: NotificationId | None = None
    """The notification whose failure this one falls back from, on another address."""

    def __post_init__(self) -> None:
        require_instance(self.id, NotificationId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        if self.recipient_id is not None:
            require_instance(self.recipient_id, RecipientId, "recipient_id")
        require_instance(self.channel, Channel, "channel")
        require_text(self.address, "address")
        require_instance(self.occasion, OccasionKind, "occasion")
        require_text(self.template_key, "template_key")
        require_text(self.language, "language")
        params = freeze_mapping(self.params, "params")
        for name, value in params.items():
            _require_json(value, f"params[{name!r}]")
        object.__setattr__(self, "params", params)
        require_instance(self.dedupe_key, DedupeKey, "dedupe_key")
        require_instance(self.state, DeliveryState, "state")
        for name in ("available_at", "created_at", "updated_at"):
            require_aware(getattr(self, name), name)
        for name in ("sent_at", "delivered_at", "read_at", "failed_at"):
            moment = getattr(self, name)
            if moment is not None:
                require_aware(moment, name)
        require_int(self.attempts, "attempts", minimum=0)
        if self.dispatch_id is not None:
            require_instance(self.dispatch_id, DispatchId, "dispatch_id")
        require_instance(self.provider_message_id, str, "provider_message_id")
        require_instance(self.error, str, "error")
        if self.fallback_of is not None:
            require_instance(self.fallback_of, NotificationId, "fallback_of")
        if self.state in SENT_STATES and self.sent_at is None:
            raise InvariantViolationError(f"a {self.state.value} notification needs sent_at")
        if self.state is DeliveryState.FAILED and self.failed_at is None:
            raise InvariantViolationError("a failed notification needs failed_at")

    @classmethod
    def queue(
        cls,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        obligation_id: ObligationId,
        recipient_id: RecipientId | None,
        channel: Channel,
        address: str,
        occasion: OccasionKind,
        template_key: str,
        language: str,
        params: Mapping[str, object],
        dedupe_key: DedupeKey,
        now: datetime,
        available_at: datetime | None = None,
        digest: bool = False,
        notification_id: NotificationId | None = None,
        fallback_of: NotificationId | None = None,
    ) -> Self:
        """A new notification that may go out at ``available_at`` (``now`` when not given),
        held for the digest when ``digest`` is set."""
        require_bool(digest, "digest")
        return cls(
            id=notification_id or NotificationId.new(),
            tenant_id=tenant_id,
            business_id=business_id,
            obligation_id=obligation_id,
            recipient_id=recipient_id,
            channel=channel,
            address=address,
            occasion=occasion,
            template_key=template_key,
            language=language,
            params=params,
            dedupe_key=dedupe_key,
            state=DeliveryState.DIGEST_PENDING if digest else DeliveryState.QUEUED,
            available_at=now if available_at is None else available_at,
            created_at=now,
            updated_at=now,
            fallback_of=fallback_of,
        )

    @property
    def is_pending(self) -> bool:
        return self.state in PENDING_STATES

    def sent(self, dispatch_id: DispatchId, provider_message_id: str, at: datetime) -> Transition:
        """The channel accepted the message."""
        self._require_pending("sent")
        sent = replace(
            self,
            state=DeliveryState.SENT,
            attempts=self.attempts + 1,
            dispatch_id=dispatch_id,
            provider_message_id=provider_message_id,
            error="",
            sent_at=at,
            updated_at=at,
        )
        event = NotificationSent(
            tenant_id=self.tenant_id,
            notification_id=self.id,
            obligation_id=self.obligation_id,
            business_id=self.business_id,
            channel=self.channel,
            dedupe_key=self.dedupe_key.value,
            sent_at=at,
            language=self.language,
            provider_message_id=provider_message_id,
        )
        return sent, (event,)

    def attempt_failed(
        self, error: str, at: datetime, policy: RetryPolicy, *, fallback: bool = False
    ) -> FailedAttempt:
        """One more failed attempt. Before the last it stays pending until the backoff has
        passed; the last fails it, and ``fallback`` says whether another address takes over."""
        self._require_pending("failed")
        require_text(error, "error", strip=False)
        require_bool(fallback, "fallback")
        attempts = self.attempts + 1
        final = policy.is_final(attempts)
        retry_at = None if final else at + policy.backoff(attempts)
        failed = replace(
            self,
            state=DeliveryState.FAILED if final else self.state,
            attempts=attempts,
            available_at=self.available_at if retry_at is None else retry_at,
            error=error,
            failed_at=at if final else None,
            updated_at=at,
        )
        event = NotificationFailed(
            tenant_id=self.tenant_id,
            notification_id=self.id,
            obligation_id=self.obligation_id,
            business_id=self.business_id,
            channel=self.channel,
            dedupe_key=self.dedupe_key.value,
            error=error,
            attempts=attempts,
            will_retry=not final or fallback,
            failed_at=at,
        )
        return failed, (event,), retry_at

    def defer(self, until: datetime, at: datetime) -> Transition:
        """Hold the notification until ``until``, such as the end of quiet hours."""
        self._require_pending("deferred")
        require_aware(until, "until")
        return replace(self, available_at=until, updated_at=at), ()

    def suppress(self, reason: str, at: datetime) -> Transition:
        """End a notification that may not go out any more."""
        self._require_pending("suppressed")
        require_text(reason, "reason")
        return replace(self, state=DeliveryState.SUPPRESSED, error=reason, updated_at=at), ()

    def _require_pending(self, what: str) -> None:
        if not self.is_pending:
            raise InvariantViolationError(
                f"notification {self.id} is {self.state.value} and cannot be {what}"
            )


def _require_json(value: object, name: str) -> None:
    """``value`` is what JSON can carry: text, a finite number, a boolean, null, or a list or an
    object of those."""
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvariantViolationError(f"{name} must be a finite number")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _require_json(item, f"{name}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvariantViolationError(f"{name} must have text keys")
            _require_json(item, f"{name}[{key!r}]")
        return
    raise InvariantViolationError(f"{name} must be JSON, got {value.__class__.__name__}")
