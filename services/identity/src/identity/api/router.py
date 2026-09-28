"""Routes of the identity service. Business logic lives in application use cases."""

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, status

from domain_kernel.ids import UserId
from identity.api.deps import Tenant, Wired
from identity.api.schemas import (
    ConsentIn,
    ConsentOut,
    ConsentSummaryOut,
    PlanOut,
    SubscriptionIn,
    SubscriptionOut,
    WebhookOut,
)
from identity.domain.billing import PLANS
from identity.domain.errors import BillingDisabledError
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])


@router.get("/ping", summary="Router liveness")
async def ping() -> dict[str, str]:
    return {"service": "identity", "status": "pong"}


@router.post(
    "/consents",
    summary="Record a consent or a withdrawal (append-only)",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 422),
)
def record_consent(body: ConsentIn, tenant: Tenant, wired: Wired) -> ConsentOut:
    record = wired.record_consent.run(
        tenant,
        body.subject,
        body.purpose,
        granted=body.granted,
        source=body.source,
        notice_version=body.notice_version,
        evidence=body.evidence,
        recorded_by=None if body.recorded_by is None else UserId(body.recorded_by),
    )
    return ConsentOut.from_record(record)


@router.get(
    "/consents",
    summary="The current state per purpose for a subject, with the full history",
    responses=problem_responses(401),
)
def consent_status(
    subject: Annotated[str, Query(min_length=1, max_length=254)], tenant: Tenant, wired: Wired
) -> ConsentSummaryOut:
    return ConsentSummaryOut.from_summary(wired.consent_status.run(tenant, subject))


@router.get("/billing/plans", summary="The plans on offer (placeholders until pricing is decided)")
def plans() -> list[PlanOut]:
    return [PlanOut.from_plan(plan) for plan in PLANS.values()]


@router.post(
    "/billing/subscriptions",
    summary="Start a subscription with the billing provider",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 422, 503),
)
def start_subscription(body: SubscriptionIn, tenant: Tenant, wired: Wired) -> SubscriptionOut:
    if wired.start_subscription is None:
        raise BillingDisabledError()
    subscription = wired.start_subscription.run(
        tenant, body.plan_key, email=body.email, name=body.name
    )
    return SubscriptionOut.from_subscription(subscription)


@router.post(
    "/billing/webhook",
    summary="Provider webhook: verified against the webhook secret before it is read",
    responses=problem_responses(401, 503),
)
async def billing_webhook(
    request: Request,
    wired: Wired,
    x_razorpay_signature: Annotated[str, Header()] = "",
) -> WebhookOut:
    if wired.receive_billing_webhook is None:
        raise BillingDisabledError()
    body = await request.body()
    event = wired.receive_billing_webhook.run(body, x_razorpay_signature)
    return WebhookOut(
        kind=event.kind,
        provider_subscription_id=event.provider_subscription_id,
        status=None if event.status is None else event.status.value,
    )
