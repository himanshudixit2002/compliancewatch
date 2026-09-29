"""Recipients of a tenant's businesses: who hears about which business, on which addresses.

Recipients are tenant data: every route needs the ``x-tenant-id`` header and sees only its
tenant's recipients. Registering replaces the recipient whole, so the caller sends everything it
knows each time (the web app does at onboarding and when a person changes their settings).
Registering an address gives no consent: it still needs its opt-in on the preferences route.
"""

from uuid import UUID

from fastapi import APIRouter, Response, status

from domain_kernel.ids import BusinessId, UserId
from notification.api.deps import Tenant, Wired
from notification.api.schemas import RecipientIn, RecipientOut
from notification.application.recipients import RecipientRegistration
from notification.domain.ids import RecipientId
from notification.domain.recipients import BusinessLink
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/notification", tags=["notification"])


@router.put(
    "/recipients/{recipient_id}",
    summary="Register a recipient, or replace it: role, language, digest, addresses, businesses",
    responses=problem_responses(401, 422),
)
def put_recipient(
    recipient_id: UUID, body: RecipientIn, tenant: Tenant, wired: Wired
) -> RecipientOut:
    registration = RecipientRegistration(
        tenant_id=tenant,
        recipient_id=RecipientId(recipient_id),
        role=body.role,
        user_id=None if body.user_id is None else UserId(body.user_id),
        language=body.language,
        digest_mode=body.digest_mode,
        org_label=body.org_label,
        addresses=[(address.channel, address.address) for address in body.addresses],
        businesses=[
            BusinessLink(BusinessId(link.business_id), link.label) for link in body.businesses
        ],
    )
    return RecipientOut.from_recipient(wired.register_recipient.run(registration))


@router.get(
    "/recipients/{recipient_id}",
    summary="A recipient of the tenant, 404 when it has none by that id",
    responses=problem_responses(401, 404),
)
def get_recipient(recipient_id: UUID, tenant: Tenant, wired: Wired) -> RecipientOut:
    return RecipientOut.from_recipient(wired.get_recipient.run(tenant, RecipientId(recipient_id)))


@router.delete(
    "/recipients/{recipient_id}",
    summary="Remove a recipient with its addresses and business links",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=problem_responses(401, 404),
)
def delete_recipient(recipient_id: UUID, tenant: Tenant, wired: Wired) -> Response:
    wired.remove_recipient.run(tenant, RecipientId(recipient_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
