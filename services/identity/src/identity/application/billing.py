"""Start a subscription and take in a provider webhook, through the ``BillingProvider``, on the
billing ledger of the unit of work (``uow.billing``).

``StartSubscription`` asks the provider for a subscription at most once per Idempotency-Key:

1. it records the start (``StartAttempt``, keyed by the tenant and the key) in its own
   transaction before any provider call. A start already recorded under the key is never sent
   again: its subscription is answered when the ledger holds it (or is recorded from the start's
   own note of it), else ``SubscriptionStartPendingError`` (409);
2. the tenant's provider customer is made once and stored at once, in its own transaction, so a
   webhook can match the subscription to the tenant even when a later step fails. Two first
   starts racing each other keep one customer (the second insert does nothing);
3. the provider's answer is noted on the start, then the subscription and the audit entry
   ``subscription.started`` are stored in one transaction. When the webhook recorded the
   subscription first, the start leaves it as the webhook left it.

A failure before the provider was asked for the subscription, or a refusal by the provider
(``BillingProviderRefusedError``: nothing was created), releases the key, so a retry starts
again. Any other failure keeps it: a retry gets the 409 and never a second subscription.

``ReceiveBillingWebhook`` verifies the signature before it reads the body, then:

- a webhook that names no tenant in the subscription's notes is answered as ignored, with a
  warning: there is no tenant whose ledger could hold it;
- otherwise, in one transaction of that tenant: the event is appended (a projection of the
  payload on an allowlist, masked for personal identifiers; never the body), unless the tenant
  holds the same body already (a redelivery, answered as a duplicate with nothing changed). Then:

  - a subscription the tenant holds takes the event's status and quantity, and a change of
    status is the audit entry ``subscription.status_changed`` by ``system:billing-webhook``.
    An event older than the last one applied, or any event after the subscription was
    cancelled (cancelled is final), changes nothing and is audited as
    ``subscription.event_ignored``;
  - a subscription the tenant does not hold is recorded (``subscription.started`` by the same
    actor) only when the payload's customer is the tenant's stored provider customer and the
    tenant exists; otherwise nothing changes, the event is audited as ``subscription.unmatched``
    and the answer is ignored, with a warning. A webhook never creates a subscription from its
    notes alone, and a subscription id another tenant holds is never moved.

Quantities are kept within 1..``max_quantity`` (``CW_PLAN_MAX_QUANTITY``) wherever they come from.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Final
from uuid import uuid4

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from domain_kernel.pii import mask_pii_in
from identity.application.audit import BILLING_WEBHOOK_ACTOR, audit_entry
from identity.domain.billing import (
    MAX_QUANTITY,
    PLANS,
    BillingEvent,
    BillingProvider,
    BillingProviderRefusedError,
    Customer,
    Plan,
    StartAttempt,
    StoredBillingEvent,
    Subscription,
    SubscriptionStatus,
    clamp_quantity,
)
from identity.domain.errors import InvalidWebhookSignatureError, SubscriptionStartPendingError
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from py_common.logging import get_logger

log = get_logger(__name__)

SUBJECT_TYPE = "subscription"
ADOPTED_REASON = "recorded from the provider's webhook"
MAX_PROJECTED_TEXT: Final = 128
"""The longest text a projected field keeps; ids, kinds, statuses and currencies are short."""


class StartSubscription:
    def __init__(
        self,
        provider: BillingProvider,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
        max_quantity: int = MAX_QUANTITY,
    ) -> None:
        self._provider = provider
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._max_quantity = max_quantity

    def run(
        self,
        tenant_id: TenantId,
        plan_key: str,
        *,
        key: str,
        email: str,
        name: str,
        quantity: int = 1,
    ) -> Subscription:
        """Start ``quantity`` units of the plan under the Idempotency-Key ``key``."""
        plan: Plan = PLANS[plan_key]
        quantity = clamp_quantity(quantity, self._max_quantity)
        attempt = StartAttempt(tenant_id, key, plan_key, quantity, self._clock())
        with self._unit_of_work(tenant_id) as uow:
            held = uow.billing.start_attempt(key)
            if held is None and not uow.billing.claim_start(attempt):
                held = uow.billing.start_attempt(key)
            customer = uow.billing.customer()
        if held is not None:
            return self._resume(held)
        try:
            customer = customer or self._store_customer(tenant_id, email=email, name=name)
        except BaseException:
            self._release(tenant_id, key)
            raise
        try:
            created = self._provider.create_subscription(customer, plan, quantity)
        except BillingProviderRefusedError:
            self._release(tenant_id, key)
            raise
        with self._unit_of_work(tenant_id) as uow:
            uow.billing.record_started(
                key,
                provider_subscription_id=created.provider_subscription_id,
                checkout_url=created.checkout_url,
                at=self._clock(),
            )
        return self._record(replace(created, updated_at=self._clock()))

    def _store_customer(self, tenant_id: TenantId, *, email: str, name: str) -> Customer:
        """The provider's new customer for the tenant, stored at once; the one stored first
        when another start stored one meanwhile."""
        made = self._provider.create_customer(tenant_id, email=email, name=name)
        with self._unit_of_work(tenant_id) as uow:
            if uow.billing.add_customer(made, provider=self._provider.name, at=self._clock()):
                return made
            return uow.billing.customer() or made

    def _resume(self, attempt: StartAttempt) -> Subscription:
        """The answer to a start already recorded under its key, without asking the provider."""
        subscription_id = attempt.provider_subscription_id
        if subscription_id is None:
            raise SubscriptionStartPendingError()
        with self._unit_of_work(attempt.tenant_id) as uow:
            found = uow.billing.subscription(subscription_id)
        if found is not None:
            return found
        at = attempt.recorded_at or attempt.created_at
        return self._record(
            Subscription(
                tenant_id=attempt.tenant_id,
                plan_key=attempt.plan_key,
                provider_subscription_id=subscription_id,
                status=SubscriptionStatus.CREATED,
                started_at=at,
                checkout_url=attempt.checkout_url,
                quantity=attempt.quantity,
                updated_at=self._clock(),
            )
        )

    def _record(self, subscription: Subscription) -> Subscription:
        """Store ``subscription`` with its ``subscription.started``, unless the ledger holds it
        already (the webhook recorded it first): then the ledger's is the answer."""
        tenant_id = subscription.tenant_id
        with self._unit_of_work(tenant_id) as uow:
            if not uow.billing.add_subscription(subscription):
                return uow.billing.subscription(subscription.provider_subscription_id) or (
                    subscription
                )
            uow.audit.write(
                audit_entry(
                    "subscription.started",
                    tenant_id=tenant_id,
                    subject_type=SUBJECT_TYPE,
                    subject_id=subscription.provider_subscription_id,
                    at=subscription.updated_at or subscription.started_at,
                    after=_state(subscription),
                )
            )
        return subscription

    def _release(self, tenant_id: TenantId, key: str) -> None:
        """Free ``key`` after the provider created no subscription for it. When that fails,
        the key stays taken (a retry gets the 409) and the original error propagates."""
        try:
            with self._unit_of_work(tenant_id) as uow:
                uow.billing.release_start(key)
        except Exception:
            log.warning("billing_start_release_failed", exc_info=True)


class Outcome(StrEnum):
    APPLIED = "applied"
    IGNORED = "ignored"
    """Older than the last event applied, or after the subscription was cancelled."""
    UNMATCHED = "unmatched"
    """Names a subscription the tenant does not hold and may not adopt."""


@dataclass(frozen=True, slots=True)
class WebhookReceipt:
    """What became of a verified webhook: ``ignored`` when it changed nothing (it names no
    tenant, no subscription the tenant may hold, or it is stale or after a cancellation),
    ``duplicate`` when the tenant had received the same body before."""

    event: BillingEvent
    ignored: bool = False
    duplicate: bool = False


class ReceiveBillingWebhook:
    def __init__(
        self,
        provider: BillingProvider,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
        max_quantity: int = MAX_QUANTITY,
    ) -> None:
        self._provider = provider
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._max_quantity = max_quantity

    def run(self, body: bytes, signature: str, *, event_id: str = "") -> WebhookReceipt:
        """``event_id`` is the provider's id of the delivery (``x-razorpay-event-id``), kept in
        the stored projection."""
        if not self._provider.verify_webhook(body, signature):
            raise InvalidWebhookSignatureError()
        event = self._provider.parse_event(body)
        tenant_id = event.tenant_id
        if tenant_id is None:
            log.warning(
                "billing_webhook_ignored",
                reason="no tenant_id in the subscription's notes",
                kind=event.kind,
                provider_subscription_id=event.provider_subscription_id,
            )
            return WebhookReceipt(event, ignored=True)
        now = self._clock()
        stored = StoredBillingEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            provider_subscription_id=event.provider_subscription_id,
            kind=event.kind,
            status=event.status,
            occurred_at=event.occurred_at,
            received_at=now,
            body_sha256=hashlib.sha256(body).hexdigest(),
            raw_event=projected_payload(body, event_id=event_id),
        )
        outcome = Outcome.APPLIED
        with self._unit_of_work(tenant_id) as uow:
            if not uow.billing.append_event(stored):
                log.info(
                    "billing_webhook_duplicate",
                    kind=event.kind,
                    provider_subscription_id=event.provider_subscription_id,
                )
                return WebhookReceipt(event, duplicate=True)
            if event.provider_subscription_id:
                outcome = _Apply(uow, tenant_id, event, now, self._max_quantity).run()
        if outcome is Outcome.UNMATCHED:
            log.warning(
                "billing_webhook_unmatched",
                reason="the subscription is not the tenant's",
                kind=event.kind,
                provider_subscription_id=event.provider_subscription_id,
            )
        return WebhookReceipt(event, ignored=outcome is not Outcome.APPLIED)


class _Apply:
    """One verified event against the tenant's ledger, inside its unit of work."""

    def __init__(
        self,
        uow: UnitOfWork,
        tenant_id: TenantId,
        event: BillingEvent,
        now: datetime,
        max_quantity: int,
    ) -> None:
        self.uow = uow
        self.tenant_id = tenant_id
        self.event = event
        self.now = now
        self.quantity = (
            None if event.quantity is None else clamp_quantity(event.quantity, max_quantity)
        )

    def run(self) -> Outcome:
        current = self.uow.billing.subscription(self.event.provider_subscription_id)
        if current is None:
            return self.adopt()
        return self.change(current)

    def change(self, current: Subscription) -> Outcome:
        event = self.event
        if event.status is None and self.quantity is None:
            return Outcome.APPLIED
        if current.status is SubscriptionStatus.CANCELLED:
            if event.status is SubscriptionStatus.CANCELLED:
                return Outcome.APPLIED
            return self.ignore(current, "the subscription is cancelled; cancelled is final")
        if current.last_event_at is not None and event.occurred_at < current.last_event_at:
            return self.ignore(current, "older than the last event applied")
        status = event.status or current.status
        quantity = self.quantity or current.quantity
        changed = replace(
            current,
            status=status,
            quantity=quantity,
            updated_at=self.now,
            last_event_at=event.occurred_at,
            past_due_since=_past_due_since(status, current, event.occurred_at),
        )
        self.uow.billing.update_subscription(changed)
        if status is not current.status:
            self.audit(
                "subscription.status_changed",
                before={"status": current.status.value, "quantity": current.quantity},
                after={"status": status.value, "quantity": quantity},
                reason=event.kind,
            )
        return Outcome.APPLIED

    def adopt(self) -> Outcome:
        """Record a subscription the ledger lacks, when it is provably the tenant's: the
        payload's customer is the tenant's stored customer, and the tenant exists."""
        event = self.event
        if event.status is None or event.plan_key is None or event.plan_key not in PLANS:
            return self.unmatched("it names no status or no plan on offer")
        customer = self.uow.billing.customer()
        if (
            customer is None
            or not event.customer_id
            or customer.provider_customer_id != event.customer_id
        ):
            return self.unmatched("its customer is not the tenant's provider customer")
        if self.uow.tenants.get(self.tenant_id) is None:
            return self.unmatched("the tenant does not exist")
        adopted = Subscription(
            tenant_id=self.tenant_id,
            plan_key=event.plan_key,
            provider_subscription_id=event.provider_subscription_id,
            status=event.status,
            started_at=event.occurred_at,
            quantity=self.quantity or 1,
            updated_at=self.now,
            last_event_at=event.occurred_at,
            past_due_since=(
                event.occurred_at if event.status is SubscriptionStatus.PAST_DUE else None
            ),
        )
        if not self.uow.billing.add_subscription(adopted):
            # The start stored it meanwhile (then it is the tenant's), or another tenant holds it.
            current = self.uow.billing.subscription(event.provider_subscription_id)
            if current is None:
                return self.unmatched("another tenant holds the subscription id")
            return self.change(current)
        self.audit("subscription.started", after=_state(adopted), reason=ADOPTED_REASON)
        return Outcome.APPLIED

    def ignore(self, current: Subscription, why: str) -> Outcome:
        self.audit(
            "subscription.event_ignored",
            before={"status": current.status.value, "quantity": current.quantity},
            after=_event_state(self.event, self.quantity),
            reason=f"{self.event.kind}: {why}",
        )
        return Outcome.IGNORED

    def unmatched(self, why: str) -> Outcome:
        self.audit(
            "subscription.unmatched",
            after=_event_state(self.event, self.quantity),
            reason=f"{self.event.kind}: {why}",
        )
        return Outcome.UNMATCHED

    def audit(
        self,
        action: str,
        *,
        reason: str,
        before: Mapping[str, object] | None = None,
        after: Mapping[str, object] | None = None,
    ) -> None:
        self.uow.audit.write(
            audit_entry(
                action,
                tenant_id=self.tenant_id,
                subject_type=SUBJECT_TYPE,
                subject_id=self.event.provider_subscription_id,
                at=self.now,
                before=None if before is None else dict(before),
                after=None if after is None else dict(after),
                reason=reason,
                actor=BILLING_WEBHOOK_ACTOR,
            )
        )


def _past_due_since(
    status: SubscriptionStatus, current: Subscription, occurred_at: datetime
) -> datetime | None:
    """When the subscription turned past due: kept while it stays past due, the event's time
    when it turns past due now, None once it is not."""
    if status is not SubscriptionStatus.PAST_DUE:
        return None
    if current.status is SubscriptionStatus.PAST_DUE and current.past_due_since is not None:
        return current.past_due_since
    return occurred_at


def _state(subscription: Subscription) -> dict[str, object]:
    return {
        "plan_key": subscription.plan_key,
        "status": subscription.status.value,
        "quantity": subscription.quantity,
    }


def _event_state(event: BillingEvent, quantity: int | None) -> dict[str, object]:
    return {
        "status": None if event.status is None else event.status.value,
        "quantity": quantity,
        "plan_key": event.plan_key,
        "occurred_at": event.occurred_at.isoformat(),
    }


SUBSCRIPTION_FIELDS: Final = (
    "id",
    "entity",
    "customer_id",
    "plan_id",
    "status",
    "quantity",
    "current_start",
    "current_end",
    "start_at",
    "end_at",
    "charge_at",
    "ended_at",
    "created_at",
    "paid_count",
    "total_count",
    "remaining_count",
)
SUBSCRIPTION_NOTES: Final = ("tenant_id", "plan_key")
PAYMENT_FIELDS: Final = (
    "id",
    "entity",
    "amount",
    "amount_refunded",
    "currency",
    "status",
    "invoice_id",
    "order_id",
    "created_at",
)
INVOICE_FIELDS: Final = (
    "id",
    "entity",
    "amount",
    "amount_paid",
    "amount_due",
    "currency",
    "status",
    "subscription_id",
    "billing_start",
    "billing_end",
    "paid_at",
    "created_at",
)
TOP_FIELDS: Final = ("event", "created_at", "account_id")


def projected_payload(body: bytes, *, event_id: str = "") -> Mapping[str, object]:
    """What the ledger keeps of a webhook: the event's kind, its time and id, and of the
    subscription, payment and invoice entities only their ids, plan, status, quantity, times,
    amounts and currency (and the subscription's notes ``tenant_id`` and ``plan_key``), masked
    for personal identifiers (``mask_pii_in``). Nothing else of the body is kept: names, emails,
    phone numbers, VPAs, addresses and card or bank details never reach the table. A body that
    is not a JSON object keeps nothing but the event id."""
    try:
        data: object = json.loads(body)
    except ValueError:
        data = None
    projected: dict[str, Any] = {}
    if event_id:
        projected["event_id"] = event_id[:MAX_PROJECTED_TEXT]
    if not isinstance(data, dict):
        return projected
    projected.update(_pick(data, TOP_FIELDS))
    payload = _mapping(data.get("payload"))
    subscription = _pick(_entity(payload, "subscription"), SUBSCRIPTION_FIELDS)
    notes = _pick(_mapping(_entity(payload, "subscription").get("notes")), SUBSCRIPTION_NOTES)
    if notes:
        subscription["notes"] = notes
    entities = {
        "subscription": subscription,
        "payment": _pick(_entity(payload, "payment"), PAYMENT_FIELDS),
        "invoice": _pick(_entity(payload, "invoice"), INVOICE_FIELDS),
    }
    kept = {name: {"entity": entity} for name, entity in entities.items() if entity}
    if kept:
        projected["payload"] = kept
    masked = mask_pii_in(projected)
    return masked if isinstance(masked, dict) else {}


def _entity(payload: Mapping[str, object], name: str) -> dict[str, Any]:
    return _mapping(_mapping(payload.get(name)).get("entity"))


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _pick(source: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, Any]:
    """The scalar values of ``fields`` in ``source``: short text, whole numbers, booleans and
    nulls. A nested value is never kept."""
    picked: dict[str, Any] = {}
    for name in fields:
        if name not in source:
            continue
        value = source[name]
        if value is None or isinstance(value, bool | int):
            picked[name] = value
        elif isinstance(value, str):
            picked[name] = value[:MAX_PROJECTED_TEXT]
    return picked
