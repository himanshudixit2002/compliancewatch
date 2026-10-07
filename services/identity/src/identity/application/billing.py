"""Start a subscription and take in a provider webhook, through the ``BillingProvider``.

Both write an audit entry of the subscription's tenant: ``subscription.started`` by the caller
when the provider has created it, and ``subscription.status_changed`` by
``system:billing-webhook`` when a verified webhook moves a subscription this service knows to
another status. The ledger itself stays in memory until its table lands.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.application.audit import BILLING_WEBHOOK_ACTOR, audit_entry
from identity.domain.billing import (
    PLANS,
    BillingEvent,
    BillingProvider,
    Customer,
    Plan,
    Subscription,
)
from identity.domain.errors import InvalidWebhookSignatureError
from identity.domain.repository import UnitOfWorkFactory


@dataclass
class BillingLedger:
    """What the service remembers about billing until its own table lands: in memory."""

    customers: dict[TenantId, Customer] = field(default_factory=dict)
    subscriptions: dict[str, Subscription] = field(default_factory=dict)
    events: list[BillingEvent] = field(default_factory=list)


class StartSubscription:
    def __init__(
        self,
        provider: BillingProvider,
        ledger: BillingLedger,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._provider = provider
        self._ledger = ledger
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, tenant_id: TenantId, plan_key: str, *, email: str, name: str) -> Subscription:
        plan: Plan = PLANS[plan_key]
        customer = self._ledger.customers.get(tenant_id)
        if customer is None:
            customer = self._provider.create_customer(tenant_id, email=email, name=name)
            self._ledger.customers[tenant_id] = customer
        subscription = self._provider.create_subscription(customer, plan)
        with self._unit_of_work(tenant_id) as uow:
            uow.audit.write(
                audit_entry(
                    "subscription.started",
                    tenant_id=tenant_id,
                    subject_type="subscription",
                    subject_id=subscription.provider_subscription_id,
                    at=self._clock(),
                    after={"plan_key": subscription.plan_key, "status": subscription.status.value},
                )
            )
        self._ledger.subscriptions[subscription.provider_subscription_id] = subscription
        return subscription


class ReceiveBillingWebhook:
    def __init__(
        self,
        provider: BillingProvider,
        ledger: BillingLedger,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._provider = provider
        self._ledger = ledger
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, body: bytes, signature: str) -> BillingEvent:
        if not self._provider.verify_webhook(body, signature):
            raise InvalidWebhookSignatureError()
        event = self._provider.parse_event(body)
        self._ledger.events.append(event)
        current = self._ledger.subscriptions.get(event.provider_subscription_id)
        if current is not None and event.status is not None:
            if event.status is not current.status:
                with self._unit_of_work(current.tenant_id) as uow:
                    uow.audit.write(
                        audit_entry(
                            "subscription.status_changed",
                            tenant_id=current.tenant_id,
                            subject_type="subscription",
                            subject_id=current.provider_subscription_id,
                            at=self._clock(),
                            before={"status": current.status.value},
                            after={"status": event.status.value},
                            reason=event.kind,
                            actor=BILLING_WEBHOOK_ACTOR,
                        )
                    )
            self._ledger.subscriptions[event.provider_subscription_id] = Subscription(
                tenant_id=current.tenant_id,
                plan_key=current.plan_key,
                provider_subscription_id=current.provider_subscription_id,
                status=event.status,
                started_at=current.started_at,
                checkout_url=current.checkout_url,
            )
        return event
