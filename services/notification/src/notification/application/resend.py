"""Send a failed notification again (``POST /notifications/{id}/resend``).

Only a notification that failed for good can be resent; any other state is refused
(``ResendNotAllowedError``, 409), so a resend never doubles a message that went out or is still
on its way. The notification is queued again, due at once, with a new round of attempts, and
its work queue entry is due with it in the same transaction. The dispatcher then sends it as it
sends everything else: consent and suppression are checked again, and quiet hours still hold it.
"""

from collections.abc import Callable
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import NotificationId, TenantId
from notification.domain.errors import NotificationNotFoundError
from notification.domain.notification import Notification
from notification.domain.repository import UnitOfWorkFactory


class ResendNotification:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, tenant_id: TenantId, notification_id: NotificationId) -> Notification:
        now = self._clock()
        with self._unit_of_work(tenant_id) as unit:
            notification = unit.notifications.get(notification_id)
            if notification is None:
                raise NotificationNotFoundError(str(notification_id))
            queued, events = notification.resend(now)
            unit.notifications.save(queued)
            unit.work.reschedule(queued.id, queued.available_at)
            for event in events:
                unit.events.publish(event)
        return queued
