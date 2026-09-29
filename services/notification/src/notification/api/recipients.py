"""Recipients of a tenant's businesses: who hears about which business, on which addresses.

Recipients are tenant data: every route needs the ``x-tenant-id`` header and sees only its
tenant's recipients. Registering replaces the recipient whole, so the caller sends everything it
knows each time (the web app does at onboarding and when a person changes their settings).
Registering an address gives no consent: it still needs its opt-in on the preferences route.
A business's recipients are listed by id; the ``cursor`` of a page's ``next_cursor`` reads the
next.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from domain_kernel.ids import BusinessId, UserId
from notification.api.deps import Tenant, Wired
from notification.api.schemas import RecipientIn, RecipientKeyset, RecipientOut
from notification.application.recipients import RecipientRegistration
from notification.domain.ids import RecipientId
from notification.domain.recipients import BusinessLink, Recipient
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/notification", tags=["notification"])

LIST_SCOPE = "notification.recipients"


def _keyset(recipient: Recipient) -> RecipientKeyset:
    return RecipientKeyset(id=recipient.id.value)


@router.get(
    "/recipients",
    summary="The recipients that follow a business, by id, a page at a time",
    responses=problem_responses(401, 422),
)
def list_recipients(
    tenant: Tenant,
    wired: Wired,
    page: Pagination,
    business_id: Annotated[UUID, Query(description="The business the recipients hear about")],
) -> Page[RecipientOut]:
    after = page.after(LIST_SCOPE, RecipientKeyset)
    found = wired.list_recipients.run(
        tenant,
        BusinessId(business_id),
        limit=page.limit + 1,
        after=None if after is None else RecipientId(after.id),
    )
    items, next_cursor = page_of(found, page.limit, LIST_SCOPE, _keyset)
    return Page[RecipientOut](
        items=[RecipientOut.from_recipient(recipient) for recipient in items],
        next_cursor=next_cursor,
    )


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
