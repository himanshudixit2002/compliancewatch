"""Read a tenant's notifications back: one by id, or a business's page by page, newest first."""

from collections.abc import Sequence

from domain_kernel.ids import BusinessId, NotificationId, TenantId
from notification.domain.errors import NotificationNotFoundError
from notification.domain.notification import DeliveryState, Notification
from notification.domain.repository import PageAfter, UnitOfWorkFactory


class GetNotification:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, notification_id: NotificationId) -> Notification:
        with self._unit_of_work(tenant_id) as unit:
            notification = unit.notifications.get(notification_id)
        if notification is None:
            raise NotificationNotFoundError(str(notification_id))
        return notification


class ListNotifications:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        tenant_id: TenantId,
        business_id: BusinessId,
        *,
        state: DeliveryState | None = None,
        limit: int,
        after: PageAfter | None = None,
    ) -> Sequence[Notification]:
        """At most ``limit`` of the business's notifications, newest first, after ``after``."""
        with self._unit_of_work(tenant_id) as unit:
            return unit.notifications.page(business_id, state=state, limit=limit, after=after)
