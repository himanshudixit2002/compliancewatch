"""Start a subscription and take in a provider webhook, through the ``BillingProvider``, on the
billing ledger of the unit of work (``uow.billing``).

``StartSubscription`` asks the provider for the tenant's customer (once per tenant) and a
subscription, then records both and the audit entry ``subscription.started`` in one
transaction. The provider's calls cannot join that transaction: when it fails after the provider
created the subscription, the first webhook about it adopts it (below), so the ledger still learns
of it and its changes are audited. The route wraps the use case in an ``Idempotency-Key``, so a
retried request never asks the provider for a second subscription.

``ReceiveBillingWebhook`` verifies the signature before it reads the body, then:

- a webhook that names no tenant in the subscription's notes is answered as ignored, with a
  warning: there is no tenant whose ledger could hold it;
- otherwise, in one transaction of that tenant: the event is appended with its payload masked for
  personal identifiers (``domain_kernel.pii``), unless the tenant holds the same body already (a
  redelivery, answered as a duplicate with nothing changed); the subscription takes the event's
  status and quantity, and a change of status is the audit entry ``subscription.status_changed``
  by ``system:billing-webhook``. A subscription the ledger does not hold, whose notes name one of
  the plans, is adopted with ``subscription.started`` by the same actor.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from domain_kernel.pii import mask_pii_in
from identity.application.audit import BILLING_WEBHOOK_ACTOR, audit_entry
from identity.domain.billing import (
    PLANS,
    BillingEvent,
    BillingProvider,
    Plan,
    StoredBillingEvent,
    Subscription,
)
from identity.domain.errors import InvalidWebhookSignatureError
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from py_common.logging import get_logger

log = get_logger(__name__)

SUBJECT_TYPE = "subscription"
ADOPTED_REASON = "recorded from the provider's webhook"


class StartSubscription:
    def __init__(
        self,
        provider: BillingProvider,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._provider = provider
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self, tenant_id: TenantId, plan_key: str, *, email: str, name: str, quantity: int = 1
    ) -> Subscription:
        plan: Plan = PLANS[plan_key]
        with self._unit_of_work(tenant_id) as uow:
            customer = uow.billing.customer()
        new_customer = customer is None
        if customer is None:
            customer = self._provider.create_customer(tenant_id, email=email, name=name)
        created = self._provider.create_subscription(customer, plan, quantity)
        now = self._clock()
        subscription = replace(created, updated_at=now)
        with self._unit_of_work(tenant_id) as uow:
            if new_customer and uow.billing.customer() is None:
                uow.billing.add_customer(customer, provider=self._provider.name, at=now)
            uow.billing.save_subscription(subscription)
            uow.audit.write(
                audit_entry(
                    "subscription.started",
                    tenant_id=tenant_id,
                    subject_type=SUBJECT_TYPE,
                    subject_id=subscription.provider_subscription_id,
                    at=now,
                    after=_state(subscription),
                )
            )
        return subscription


@dataclass(frozen=True, slots=True)
class WebhookReceipt:
    """What became of a verified webhook: ``ignored`` when it names no tenant, ``duplicate``
    when the tenant had received the same body before."""

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
    ) -> None:
        self._provider = provider
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, body: bytes, signature: str) -> WebhookReceipt:
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
            raw_event=masked_payload(body),
        )
        with self._unit_of_work(tenant_id) as uow:
            if not uow.billing.append_event(stored):
                log.info(
                    "billing_webhook_duplicate",
                    kind=event.kind,
                    provider_subscription_id=event.provider_subscription_id,
                )
                return WebhookReceipt(event, duplicate=True)
            if event.provider_subscription_id:
                _apply(uow, tenant_id, event, now)
        return WebhookReceipt(event)


def _apply(uow: UnitOfWork, tenant_id: TenantId, event: BillingEvent, now: datetime) -> None:
    """Move the subscription to the event's status and quantity, or adopt one the ledger lacks."""
    current = uow.billing.subscription(event.provider_subscription_id)
    if current is None:
        if event.status is None or event.plan_key is None or event.plan_key not in PLANS:
            return
        adopted = Subscription(
            tenant_id=tenant_id,
            plan_key=event.plan_key,
            provider_subscription_id=event.provider_subscription_id,
            status=event.status,
            started_at=event.occurred_at,
            quantity=event.quantity or 1,
            updated_at=now,
        )
        uow.billing.save_subscription(adopted)
        uow.audit.write(
            audit_entry(
                "subscription.started",
                tenant_id=tenant_id,
                subject_type=SUBJECT_TYPE,
                subject_id=adopted.provider_subscription_id,
                at=now,
                after=_state(adopted),
                reason=ADOPTED_REASON,
                actor=BILLING_WEBHOOK_ACTOR,
            )
        )
        return
    status = event.status or current.status
    quantity = event.quantity or current.quantity
    if status is current.status and quantity == current.quantity:
        return
    changed = replace(current, status=status, quantity=quantity, updated_at=now)
    uow.billing.save_subscription(changed)
    if status is not current.status:
        uow.audit.write(
            audit_entry(
                "subscription.status_changed",
                tenant_id=tenant_id,
                subject_type=SUBJECT_TYPE,
                subject_id=current.provider_subscription_id,
                at=now,
                before={"status": current.status.value, "quantity": current.quantity},
                after={"status": status.value, "quantity": quantity},
                reason=event.kind,
                actor=BILLING_WEBHOOK_ACTOR,
            )
        )


def _state(subscription: Subscription) -> dict[str, object]:
    return {
        "plan_key": subscription.plan_key,
        "status": subscription.status.value,
        "quantity": subscription.quantity,
    }


def masked_payload(body: bytes) -> Mapping[str, object]:
    """The webhook's JSON object with every text in it masked as audit rows are
    (``mask_pii_in``); a body that is not a JSON object is kept masked as ``{"body": text}``."""
    text = body.decode("utf-8", errors="replace")
    try:
        data: object = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {"body": mask_pii_in(text)}
    masked = mask_pii_in(data)
    return masked if isinstance(masked, dict) else {"body": mask_pii_in(text)}
