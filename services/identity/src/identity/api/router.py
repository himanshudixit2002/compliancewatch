"""Routes of the identity service. Business logic lives in application use cases."""

from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from domain_kernel.ids import UserId
from identity.api.deps import ChannelAccess, Tenant, Wired
from identity.api.schemas import (
    E164_PATTERN,
    ChannelConsentIn,
    ChannelConsentOut,
    ChannelConsentSummaryOut,
    ConsentIn,
    ConsentOut,
    ConsentSummaryOut,
    PlanOut,
    SubscriptionIn,
    SubscriptionOut,
    WebhookOut,
)
from identity.domain.billing import PLANS
from identity.domain.channel_consent import ConsentChannel
from identity.domain.errors import BillingDisabledError
from py_common.auth.fastapi import CurrentPrincipal
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])


@router.get("/ping", summary="Router liveness")
async def ping() -> dict[str, str]:
    return {"service": "identity", "status": "pong"}


@router.post(
    "/consents",
    summary="Record a consent or a withdrawal (append-only)",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 403, 422),
)
def record_consent(
    body: ConsentIn, tenant: Tenant, principal: CurrentPrincipal, wired: Wired
) -> ConsentOut:
    """A caller a verified token names is who recorded the consent (None for a service), and the
    body's ``recorded_by`` is ignored; without a token the body names them, as before."""
    if principal.is_authenticated:
        recorded_by = principal.user_id
    else:
        recorded_by = None if body.recorded_by is None else UserId(body.recorded_by)
    record = wired.record_consent.run(
        tenant,
        body.subject,
        body.purpose,
        granted=body.granted,
        source=body.source,
        notice_version=body.notice_version,
        evidence=body.evidence,
        recorded_by=recorded_by,
    )
    return ConsentOut.from_record(record)


@router.get(
    "/consents",
    summary="The current state per purpose for a subject, with the full history",
    responses=problem_responses(401, 403),
)
def consent_status(
    subject: Annotated[str, Query(min_length=1, max_length=254)],
    tenant: Tenant,
    wired: Wired,
    channel: Annotated[
        Literal["whatsapp", "email"] | None,
        Query(description="With address: ask whether the address is the subject's own contact"),
    ] = None,
    address: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=254,
            description="An address on channel; address_matches says whether it is the subject's",
        ),
    ] = None,
) -> ConsentSummaryOut:
    summary = wired.consent_status.run(
        tenant, subject, channel=channel or "", address=address or ""
    )
    return ConsentSummaryOut.from_summary(summary)


@router.post(
    "/channel-consents",
    summary="Record a keyword opt-in or opt-out for a number no tenant owns yet (service token)",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": ChannelConsentOut, "description": "The message was recorded already"},
        **problem_responses(401, 403, 422, 503),
    },
    dependencies=[ChannelAccess],
)
def record_channel_consent(
    body: ChannelConsentIn, wired: Wired, response: Response
) -> ChannelConsentOut:
    recorded = wired.record_channel_consent.run(
        body.channel,
        body.subject,
        body.purpose,
        granted=body.granted,
        source=body.source,
        notice_version=body.notice_version,
        evidence=body.evidence,
        message_id=body.message_id,
    )
    if not recorded.created:
        response.status_code = status.HTTP_200_OK
    return ChannelConsentOut.from_record(recorded.record)


@router.get(
    "/channel-consents/{channel}/{subject}",
    summary="A number's current state per purpose on a channel, with the history (service token)",
    responses=problem_responses(401, 403, 422, 503),
    dependencies=[ChannelAccess],
)
def channel_consent_status(
    channel: ConsentChannel,
    subject: Annotated[str, Path(pattern=E164_PATTERN, description="E.164 number")],
    wired: Wired,
) -> ChannelConsentSummaryOut:
    return ChannelConsentSummaryOut.from_summary(wired.channel_consent_status.run(channel, subject))


@router.get("/billing/plans", summary="The plans on offer (placeholders until pricing is decided)")
def plans() -> list[PlanOut]:
    return [PlanOut.from_plan(plan) for plan in PLANS.values()]


@router.post(
    "/billing/subscriptions",
    summary="Start a subscription with the billing provider",
    status_code=status.HTTP_201_CREATED,
    response_model=SubscriptionOut,
    responses={**problem_responses(401, 403, 422, 503), **IDEMPOTENCY_RESPONSES},
)
def start_subscription(
    body: SubscriptionIn, tenant: Tenant, key: IdempotencyKey, wired: Wired
) -> JSONResponse:
    """A retry with the same Idempotency-Key and body gets the first answer back for 24 hours
    and starts nothing at the provider; the same key with another body is a 422. A key whose
    start failed after the provider may have created the subscription is never sent to it
    again: the retry gets 409 identity-subscription-start-pending."""
    start = wired.start_subscription
    if start is None:
        raise BillingDisabledError()

    def produce() -> SubscriptionOut:
        subscription = start.run(
            tenant,
            body.plan_key,
            key=key.key,
            email=body.email,
            name=body.name,
            quantity=body.quantity,
        )
        return SubscriptionOut.from_subscription(subscription)

    return run_idempotent(wired.idempotency, tenant, key, status.HTTP_201_CREATED, produce)


@router.post(
    "/billing/webhook",
    summary="Provider webhook: verified against the webhook secret before it is read",
    responses=problem_responses(401, 503),
)
async def billing_webhook(
    request: Request,
    wired: Wired,
    x_razorpay_signature: Annotated[str, Header()] = "",
    x_razorpay_event_id: Annotated[str, Header(max_length=128)] = "",
) -> WebhookOut:
    """A verified webhook that changed nothing is answered with ``ignored``: it names no tenant,
    a subscription the tenant does not hold and may not adopt, or it is older than the last
    event applied or follows a cancellation. A body the tenant received before is answered with
    ``duplicate``. Either way the answer is 200, so the provider stops redelivering it."""
    receive = wired.receive_billing_webhook
    if receive is None:
        raise BillingDisabledError()
    body = await request.body()
    receipt = await run_in_threadpool(
        partial(receive.run, event_id=x_razorpay_event_id), body, x_razorpay_signature
    )
    event = receipt.event
    return WebhookOut(
        kind=event.kind,
        provider_subscription_id=event.provider_subscription_id,
        status=None if event.status is None else event.status.value,
        ignored=receipt.ignored,
        duplicate=receipt.duplicate,
    )
