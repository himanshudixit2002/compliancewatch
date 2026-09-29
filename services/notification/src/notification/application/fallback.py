"""The fallback of a notification that failed for good: the same message on the recipient's next
open address on another channel.

The dispatcher queues it after the last attempt failed, and the receipts after a provider
reported a failure of a message it had taken. Either way the fallback is due at once, keyed from
the failed notification (``occasions.fallback_key``) so that it is made once; for a recipient
who hears by digest it goes as a digest on the new address. A fallback does not fall back again,
which stops a WhatsApp to email to WhatsApp loop, and a send addressed straight to a number has
no recipient to fall back to.
"""

from datetime import datetime

from notification.application.consent import open_in
from notification.domain.notification import Notification
from notification.domain.occasions import fallback_key
from notification.domain.recipients import Recipient
from notification.domain.repository import UnitOfWork, WorkEntry


def queue_fallback(
    unit: UnitOfWork, failed: Notification, recipient: Recipient | None, now: datetime
) -> Notification | None:
    """Queue the fallback of ``failed`` in ``unit``; None when there is none to queue."""
    if recipient is None or failed.fallback_of is not None:
        return None
    address = recipient.fallback_after(failed.channel, open_in(unit))
    if address is None:
        return None
    fallback = Notification.queue(
        tenant_id=failed.tenant_id,
        business_id=failed.business_id,
        obligation_id=failed.obligation_id,
        recipient_id=failed.recipient_id,
        channel=address.channel,
        address=address.address,
        occasion=failed.occasion,
        template_key=failed.template_key,
        language=failed.language,
        params=failed.params,
        dedupe_key=fallback_key(failed.dedupe_key, address.channel),
        now=now,
        digest=recipient.by_digest,
        fallback_of=failed.id,
    )
    if not unit.notifications.add_if_absent(fallback):
        return None
    unit.work.add(WorkEntry.of(fallback))
    return fallback
