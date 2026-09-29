"""A tenant's notifications: a business's history page by page, one notification, and a resend.

Notifications are tenant data: every route needs the ``x-tenant-id`` header and sees only its
tenant's notifications. The history is newest first; ``state`` keeps one state, and the
``cursor`` of a page's ``next_cursor`` reads the next. Only a notification that failed for good
can be resent; it is queued again and the dispatcher sends it within seconds, checking consent
and quiet hours as it does for any other.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.ids import BusinessId, NotificationId
from notification.api.deps import Tenant, Wired
from notification.api.schemas import NotificationKeyset, NotificationOut
from notification.domain.notification import DeliveryState, Notification
from notification.domain.repository import PageAfter
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/notification", tags=["notification"])

LIST_SCOPE = "notification.notifications"


def _keyset(notification: Notification) -> NotificationKeyset:
    return NotificationKeyset(created_at=notification.created_at, id=notification.id.value)


@router.get(
    "/notifications",
    summary="A business's notifications, newest first, a page at a time",
    responses=problem_responses(401, 422),
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
    responses=problem_responses(401, 404),
)
def get_notification(notification_id: UUID, tenant: Tenant, wired: Wired) -> NotificationOut:
    found = wired.get_notification.run(tenant, NotificationId(notification_id))
    return NotificationOut.from_notification(found)


@router.post(
    "/notifications/{notification_id}/resend",
    summary="Queue a notification that failed for good again; 409 in any other state",
    responses=problem_responses(401, 404, 409),
)
def resend_notification(notification_id: UUID, tenant: Tenant, wired: Wired) -> NotificationOut:
    return NotificationOut.from_notification(
        wired.resend.run(tenant, NotificationId(notification_id))
    )
