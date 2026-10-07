"""A tenant's data as the notification service holds it, for the tenant's data export.

Identity assembles the export and calls ``GET /v1/notification/data-export`` for the tenant; this
use case reads what that answer carries, in one tenant unit of work (row-level security in
Postgres, the tenant's rows only in memory):

- ``recipients``: the tenant's recipients with their addresses in order and the businesses each
  hears about, oldest first;
- ``preferences``: the channel_preference rows of the addresses the tenant's recipients hold
  (consent, source, language, quiet hours, the last time the address wrote to us), by channel and
  address. Preferences belong to no tenant, so they are selected by those addresses and no other
  address's is read;
- ``notifications``: the tenant's notifications, oldest first, with their template values and
  delivery history. The dedupe key, an internal key of the occasion, is left out.

Suppressions, the address directory and the work index are the service's own bookkeeping across
tenants and are not exported. Each section is read ``EXPORT_PAGE_SIZE`` rows at a time and the
pages are joined. Rows are JSON-safe: ids as strings, times in ISO 8601, enums as their values.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from domain_kernel.events import utc_now
from domain_kernel.ids import EntityId, TenantId
from notification.domain.notification import Notification
from notification.domain.preferences import QuietHours
from notification.domain.recipients import Recipient
from notification.domain.repository import (
    ExportAfter,
    PreferenceRecord,
    UnitOfWork,
    UnitOfWorkFactory,
)

SERVICE_NAME: Final = "notification"
EXPORT_PAGE_SIZE: Final = 500
SECTIONS: Final = ("recipients", "preferences", "notifications")

type Row = dict[str, Any]


@dataclass(frozen=True, slots=True)
class TenantDataExport:
    service: str
    tenant_id: TenantId
    generated_at: datetime
    sections: Mapping[str, list[Row]]


class ExportTenantData:
    """``page_size`` is how many rows each read takes; tests make it small to cross pages."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
        page_size: int = EXPORT_PAGE_SIZE,
    ) -> None:
        if page_size < 1:
            raise ValueError(f"page_size must be at least 1, got {page_size}")
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._page_size = page_size

    def run(self, tenant_id: TenantId) -> TenantDataExport:
        with self._unit_of_work(tenant_id) as unit:
            sections = {
                "recipients": [_recipient(r) for r in self._recipients(unit)],
                "preferences": [_preference(p) for p in self._preferences(unit)],
                "notifications": [_notification(n) for n in self._notifications(unit)],
            }
        return TenantDataExport(
            service=SERVICE_NAME,
            tenant_id=tenant_id,
            generated_at=self._clock(),
            sections=sections,
        )

    def _recipients(self, unit: UnitOfWork) -> list[Recipient]:
        found: list[Recipient] = []
        after: ExportAfter | None = None
        while True:
            page = unit.recipients.export_recipients(after, self._page_size)
            found.extend(page)
            if len(page) < self._page_size:
                return found
            after = ExportAfter(page[-1].created_at, page[-1].id.value)

    def _preferences(self, unit: UnitOfWork) -> list[PreferenceRecord]:
        found: list[PreferenceRecord] = []
        after = None
        while True:
            page = unit.recipients.export_preferences(after, self._page_size)
            found.extend(page)
            if len(page) < self._page_size:
                return found
            after = page[-1].key

    def _notifications(self, unit: UnitOfWork) -> list[Notification]:
        found: list[Notification] = []
        after: ExportAfter | None = None
        while True:
            page = unit.notifications.export_notifications(after, self._page_size)
            found.extend(page)
            if len(page) < self._page_size:
                return found
            after = ExportAfter(page[-1].created_at, page[-1].id.value)


def _moment(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat()


def _id(value: EntityId | None) -> str | None:
    return None if value is None else str(value.value)


def _clock_time(quiet_hours: QuietHours) -> tuple[str, str]:
    return quiet_hours.start.strftime("%H:%M"), quiet_hours.end.strftime("%H:%M")


def _recipient(recipient: Recipient) -> Row:
    return {
        "id": str(recipient.id.value),
        "tenant_id": str(recipient.tenant_id.value),
        "user_id": _id(recipient.user_id),
        "role": recipient.role.value,
        "language": recipient.language,
        "digest_mode": recipient.digest_mode.value,
        "org_label": recipient.org_label,
        "addresses": [
            {"channel": a.channel.value, "address": a.address, "position": a.position}
            for a in recipient.addresses
        ],
        "businesses": [
            {"business_id": str(link.business_id.value), "label": link.label}
            for link in recipient.businesses
        ],
        "created_at": recipient.created_at.isoformat(),
        "updated_at": recipient.updated_at.isoformat(),
    }


def _preference(record: PreferenceRecord) -> Row:
    start, end = _clock_time(record.quiet_hours)
    return {
        "channel": record.channel.value,
        "address": record.address,
        "opted_in": record.opted_in,
        "source": None if record.source is None else record.source.value,
        "language": record.language,
        "quiet_hours_start": start,
        "quiet_hours_end": end,
        "updated_at": _moment(record.updated_at),
        "last_inbound_at": _moment(record.last_inbound_at),
    }


def _notification(notification: Notification) -> Row:
    return {
        "id": str(notification.id.value),
        "tenant_id": str(notification.tenant_id.value),
        "business_id": str(notification.business_id.value),
        "obligation_id": str(notification.obligation_id.value),
        "recipient_id": _id(notification.recipient_id),
        "channel": notification.channel.value,
        "address": notification.address,
        "occasion": notification.occasion.value,
        "template_key": notification.template_key,
        "language": notification.language,
        "params": _plain(notification.params),
        "state": notification.state.value,
        "attempts": notification.attempts,
        "available_at": notification.available_at.isoformat(),
        "dispatch_id": _id(notification.dispatch_id),
        "provider_message_id": notification.provider_message_id,
        "error": notification.error,
        "fallback_of": _id(notification.fallback_of),
        "created_at": notification.created_at.isoformat(),
        "updated_at": notification.updated_at.isoformat(),
        "sent_at": _moment(notification.sent_at),
        "delivered_at": _moment(notification.delivered_at),
        "read_at": _moment(notification.read_at),
        "failed_at": _moment(notification.failed_at),
    }


def _plain(value: object) -> Any:
    """Template values as JSON: read-only mappings and tuples become dicts and lists."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value
