"""Routes of the notification service. Business logic lives in application use cases.

Preferences are keyed by channel and address and carry no tenant: an opt-out typed on
WhatsApp arrives before we know which tenant the number belongs to, and must be honoured
either way. The address in the path is normalised first, so ``919876543210`` and
``+91 98765 43210`` are one record; an address that cannot be normalised is a 422 problem.
Sends are tenant data and need the header.
"""

from fastapi import APIRouter, HTTPException, status

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, NotificationId, ObligationId
from notification.api.deps import Tenant, Wired
from notification.api.schemas import (
    PreferenceIn,
    PreferenceOut,
    SendIn,
    SendOut,
    TemplateOut,
)
from notification.domain.model import NotificationRequest
from notification.domain.preferences import QuietHours
from notification.domain.templates import TEMPLATES
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/notification", tags=["notification"])


@router.get("/ping", summary="Router liveness")
async def ping() -> dict[str, str]:
    return {"service": "notification", "status": "pong"}


@router.put(
    "/preferences/{channel}/{recipient}",
    summary="Record an opt-in or opt-out for a channel and recipient",
    responses=problem_responses(422),
)
def set_preference(
    channel: Channel, recipient: str, body: PreferenceIn, wired: Wired
) -> PreferenceOut:
    quiet_hours = None
    if body.quiet_hours_start and body.quiet_hours_end:
        quiet_hours = QuietHours.parse(body.quiet_hours_start, body.quiet_hours_end)
    preference = wired.set_opt_in.run(
        channel,
        recipient,
        opted_in=body.opted_in,
        source=body.source,
        language=body.language,
        quiet_hours=quiet_hours,
    )
    return PreferenceOut.from_preference(preference, recipient=recipient)


@router.get(
    "/preferences/{channel}/{recipient}",
    summary="The recorded preference, 404 when the recipient never opted in or out",
    responses=problem_responses(404, 422),
)
def get_preference(channel: Channel, recipient: str, wired: Wired) -> PreferenceOut:
    preference = wired.get_preference.run(channel, recipient)
    if preference is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no preference recorded")
    return PreferenceOut.from_preference(preference, recipient=recipient)


@router.post(
    "/send",
    summary="Send one notification now: dedupe, consent, quiet hours, queue, deliver",
    description=(
        "A failed delivery stays queued and the service retries it; sending the same request "
        "again is a duplicate. In quiet hours the notification is queued for their end."
    ),
    responses=problem_responses(401, 422, 503),
)
def send(body: SendIn, tenant: Tenant, wired: Wired) -> SendOut:
    request = NotificationRequest(
        notification_id=NotificationId(body.notification_id),
        tenant_id=tenant,
        obligation_id=ObligationId(body.obligation_id),
        business_id=BusinessId(body.business_id),
        channel=body.channel,
        recipient=body.recipient,
        template_key=body.template_key,
        params=body.params,
        language=body.language,
    )
    return SendOut.from_outcome(wired.send.run(request))


@router.get("/templates", summary="Every message template with its approval status")
def templates() -> list[TemplateOut]:
    return [TemplateOut.from_template(template) for template in TEMPLATES]
