"""Delivery receipts: what the providers report after they took a message.

``POST /receipts/email`` takes what Amazon SES reports through SNS: bounces, complaints and
deliveries. SNS posts the message as JSON in a text/plain body with the HTTP basic credentials
of the subscription URL (``https://sns:<secret>@<host>/v1/notification/receipts/email``); the
password is ``CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN``, so the secret never appears in the path
that logs and spans record. The message's signature is verified before it is read. A permanent
bounce or a complaint suppresses the mailbox for every tenant, and a subscription confirmation
is logged for the maintainer to open once.

``POST /receipts/whatsapp`` takes what the WhatsApp bot forwards from Meta's webhook: the
statuses of the messages the service sent (sent, delivered, read, failed) and the times numbers
wrote to the business, which open the 24-hour customer service window. It names no tenant, so
it is guarded by the bot's shared secret (``x-cw-bot-token``, ``CW_NOTIFICATION_BOT_TOKEN``):
no configured token is a 503, a missing or wrong one a 401. With ``CW_AUTH_MODE`` dual or token
the bot may send its service token with the notification:receipts scope instead, and token mode
accepts only that. A status for a message the service did not send, such as the bot's own
replies, is counted as unknown and otherwise ignored.
"""

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from domain_kernel.channels import Channel
from notification.api.deps import BotAccess, FeedbackAccess, Wired
from notification.api.schemas import EmailFeedbackOut, ReceiptsOut, WhatsAppReceiptsIn
from notification.application.receipts import InboundTime
from notification.domain.receipts import Receipt, ReceiptKind, from_whatsapp, whatsapp_error
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/notification", tags=["notification"])


@router.post(
    "/receipts/whatsapp",
    summary="Record the WhatsApp statuses and inbound times the bot forwards",
    dependencies=[BotAccess],
    responses=problem_responses(401, 403, 422, 503),
)
def whatsapp_receipts(body: WhatsAppReceiptsIn, wired: Wired) -> ReceiptsOut:
    receipts: list[Receipt] = []
    ignored = 0
    for status in body.statuses:
        kind = from_whatsapp(status.status)
        if kind is None:
            ignored += 1
            continue
        failed = kind is ReceiptKind.FAILED
        receipts.append(
            Receipt(
                provider_message_id=status.provider_message_id,
                kind=kind,
                at=status.at,
                error=whatsapp_error(status.error_code, status.error_title) if failed else "",
            )
        )
    reconciled = wired.reconcile.run(
        Channel.WHATSAPP,
        receipts,
        [InboundTime(item.address, item.at) for item in body.inbound],
    )
    return ReceiptsOut(
        applied=reconciled.applied,
        unchanged=reconciled.unchanged,
        unknown=reconciled.unknown,
        ignored=ignored,
        inbound=reconciled.inbound,
    )


SNS_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "text/plain": {
                "schema": {"type": "string", "description": "The SNS message, JSON as text"}
            }
        },
    }
}


@router.post(
    "/receipts/email",
    summary="Record the SES bounces, complaints and deliveries that SNS posts",
    dependencies=[FeedbackAccess],
    responses=problem_responses(401, 422, 503),
    openapi_extra=SNS_BODY,
)
async def email_receipts(request: Request, wired: Wired) -> EmailFeedbackOut:
    body = (await request.body()).decode("utf-8", "replace")
    outcome = await run_in_threadpool(wired.email_feedback.run, body)
    reconciled = outcome.reconciled
    return EmailFeedbackOut(
        kind=outcome.kind.value,
        applied=reconciled.applied,
        unchanged=reconciled.unchanged,
        unknown=reconciled.unknown,
        suppressed=reconciled.suppressed,
    )
