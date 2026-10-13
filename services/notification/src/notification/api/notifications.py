"""A tenant's notifications: a business's history page by page, one notification, and a resend.

Notifications are tenant data: every route acts for one tenant (``deps.Tenant``: a user's token
names it, otherwise the ``x-tenant-id`` header) and sees only its tenant's notifications. The
history is newest first; ``state`` keeps one state, and the ``cursor`` of a page's ``next_cursor``
reads the next. Only a notification that failed for good can be resent, by a tenant admin for
their own tenant or by the regulatory team's admin for the tenant ``x-tenant-id`` names
(``deps.Resender``), with a reason and an ``Idempotency-Key``: it is queued again, the resend is
audited as ``notification.resent``, and the dispatcher sends it within seconds, checking consent
and quiet hours as it does for any other. A retry with the same key and body gets the first answer
back for 24 hours and queues nothing more.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from domain_kernel.ids import BusinessId, NotificationId
from notification.api.deps import Resender, Tenant, Wired
from notification.api.schemas import NotificationKeyset, NotificationOut, ResendIn
from notification.domain.notification import DeliveryState, Notification
from notification.domain.repository import PageAfter
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/notification", tags=["notification"])

LIST_SCOPE = "notification.notifications"
RESEND_PROBLEMS = {**problem_responses(401, 403, 404, 409, 422), **IDEMPOTENCY_RESPONSES}


def _keyset(notification: Notification) -> NotificationKeyset:
    return NotificationKeyset(created_at=notification.created_at, id=notification.id.value)


@router.get(
    "/notifications",
    summary="A business's notifications, newest first, a page at a time",
    responses=problem_responses(401, 403, 422),
)
def list_notifications(
    tenant: Tenant,
    wired: Wired,
    page: Pagination,
    business_id: Annotated[UUID, Query(description="The business the notifications are about")],
    state: Annotated[DeliveryState | None, Query(description="Keep only this state")] = None,
) -> Page[NotificationOut]:
    after = page.after(LIST_SCOPE, NotificationKeyset)
    found = wired.list_notifications.run(
        tenant,
        BusinessId(business_id),
        state=state,
        limit=page.limit + 1,
        after=None if after is None else PageAfter(after.created_at, NotificationId(after.id)),
    )
    items, next_cursor = page_of(found, page.limit, LIST_SCOPE, _keyset)
    return Page[NotificationOut](
        items=[NotificationOut.from_notification(notification) for notification in items],
        next_cursor=next_cursor,
    )


@router.get(
    "/notifications/{notification_id}",
    summary="One notification of the tenant, 404 when it has none by that id",
    responses=problem_responses(401, 403, 404),
)
def get_notification(notification_id: UUID, tenant: Tenant, wired: Wired) -> NotificationOut:
    found = wired.get_notification.run(tenant, NotificationId(notification_id))
    return NotificationOut.from_notification(found)


@router.post(
    "/notifications/{notification_id}/resend",
    summary=(
        "Queue a notification that failed for good again, for a reason (tenant admins, admins); "
        "409 in any other state"
    ),
    response_model=NotificationOut,
    responses=RESEND_PROBLEMS,
)
def resend_notification(
    notification_id: UUID, body: ResendIn, caller: Resender, key: IdempotencyKey, wired: Wired
) -> JSONResponse:
    """The resend is written to the tenant's audit trail as ``notification.resent`` with the
    reason and the actor. ``recipient``, when given, must be the notification's own address
    (422 otherwise). A retry with the same ``Idempotency-Key`` and body gets the first answer
    back (``Idempotent-Replayed: true``); the same key with another body is a 422."""

    def produce() -> NotificationOut:
        return NotificationOut.from_notification(
            wired.resend.run(
                caller.tenant_id,
                NotificationId(notification_id),
                reason=body.reason,
                actor=caller.actor,
                recipient=body.recipient,
                correlation_id=caller.correlation_id,
            )
        )

    return run_idempotent(wired.idempotency, caller.tenant_id, key, status.HTTP_200_OK, produce)
