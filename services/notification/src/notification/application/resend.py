"""Send a failed notification again (``POST /notifications/{id}/resend``), for a reason.

Only a notification that failed for good can be resent; any other state is refused
(``ResendNotAllowedError``, 409), so a resend never doubles a message that went out or is still
on its way. The notification is queued again, due at once, with a new round of attempts, and
its work queue entry is due with it in the same transaction. The dispatcher then sends it as it
sends everything else: consent and suppression are checked again, and quiet hours still hold it.

A resend is an admin's act on a tenant's data, so it carries a reason and is audited: the unit
writes ``notification.resent`` with the reason, the actor, the channel and the attempts the
failed round took, and never the address. A notification goes to one address; ``recipient``,
when given, must be that address (normalised as the notification keeps it), else nothing is
queued (``ResendRecipientMismatchError``, 422): the admin says which address they mean, and a
resend never reaches another.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.events import utc_now
from domain_kernel.ids import NotificationId, TenantId
from notification.domain.addresses import normalise_address
from notification.domain.errors import NotificationNotFoundError, ResendRecipientMismatchError
from notification.domain.notification import Notification
from notification.domain.repository import UnitOfWorkFactory

RESENT_ACTION: Final = "notification.resent"
SUBJECT: Final = "notification"


class ResendNotification:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        notification_id: NotificationId,
        *,
        reason: str,
        actor: AuditActor,
        recipient: str | None = None,
        correlation_id: str | None = None,
    ) -> Notification:
        """The notification, queued again; ``reason`` and ``actor`` go to the audit entry."""
        if not reason.strip():
            raise ValueError("a resend needs a reason")
        now = self._clock()
        with self._unit_of_work(tenant_id) as unit:
            notification = unit.notifications.get(notification_id)
            if notification is None:
                raise NotificationNotFoundError(str(notification_id))
            if recipient is not None and (
                normalise_address(notification.channel, recipient) != notification.address
            ):
                raise ResendRecipientMismatchError(str(notification_id))
            queued, events = notification.resend(now)
            unit.notifications.save(queued)
            unit.work.reschedule(queued.id, queued.available_at)
            for event in events:
                unit.events.publish(event)
            unit.audit.write(
                AuditEntry(
                    action=RESENT_ACTION,
                    tenant_id=tenant_id,
                    subject_type=SUBJECT,
                    subject_id=str(notification.id),
                    actor=actor,
                    reason=reason,
                    before={
                        "state": notification.state.value,
                        "attempts": notification.attempts,
                        "error": notification.error,
                    },
                    after={
                        "state": queued.state.value,
                        "attempts": queued.attempts,
                        "channel": queued.channel.value,
                        "recipient_named": recipient is not None,
                    },
                    occurred_at=now,
                    correlation_id=correlation_id,
                )
            )
        return queued
