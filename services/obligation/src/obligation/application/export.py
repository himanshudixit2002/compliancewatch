"""What the obligation service holds of one tenant, for the tenant's data export.

Identity assembles a tenant's export by asking every service for its part. ``ExportTenantData``
answers for this one: the tenant's obligations in any status (``obligations``), the change log
of every one of them (``changes``) and the comments on them (``comments``), each section oldest
first and then by id. Each section is read in keyset pages of ``EXPORT_PAGE_SIZE`` rows inside
one unit of work of the tenant, so row-level security keeps every row to that tenant and no read
is unbounded. Rows are plain JSON values: ids as strings, instants and days in ISO 8601, enums as
their values, sequences as lists, a period as its start, end and label. The tenant's own id is
the export's and so is left off every row. Writing nothing, it records no audit entry: identity
writes ``data_request.exported`` for the export as a whole.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final
from uuid import UUID

from domain_kernel.events import utc_now
from domain_kernel.ids import EntityId, TenantId
from obligation.domain.repository import ExportAfter, UnitOfWorkFactory

SERVICE_NAME: Final = "obligation"
EXPORT_PAGE_SIZE: Final = 500
"""The rows one read of a section returns; the use case reads pages until one comes back
short."""
OBLIGATIONS: Final = "obligations"
CHANGES: Final = "changes"
COMMENTS: Final = "comments"
SECTIONS: Final = (OBLIGATIONS, CHANGES, COMMENTS)
LEFT_OFF: Final = frozenset({"tenant_id"})
"""Fields no row carries: the tenant is the export's."""

type ExportRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class TenantDataExport:
    """One service's part of a tenant's data export: every section, empty when the tenant has
    nothing in it."""

    service: str
    tenant_id: TenantId
    generated_at: datetime
    sections: Mapping[str, Sequence[ExportRow]]


class ExportTenantData:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Callable[[], datetime] = utc_now,
        *,
        page_size: int = EXPORT_PAGE_SIZE,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._page_size = page_size

    def run(self, tenant_id: TenantId) -> TenantDataExport:
        generated_at = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            obligations = _read_all(
                uow.obligations.export_page,
                lambda obligation: ExportAfter(obligation.created_at, obligation.id.value),
                self._page_size,
            )
            changes = _read_all(
                uow.history.export_page,
                lambda change: ExportAfter(change.occurred_at, change.id.value),
                self._page_size,
            )
            comments = _read_all(
                uow.comments.export_page,
                lambda comment: ExportAfter(comment.created_at, comment.id.value),
                self._page_size,
            )
        return TenantDataExport(
            service=SERVICE_NAME,
            tenant_id=tenant_id,
            generated_at=generated_at,
            sections={
                OBLIGATIONS: [export_row(obligation) for obligation in obligations],
                CHANGES: [export_row(change) for change in changes],
                COMMENTS: [export_row(comment) for comment in comments],
            },
        )


def _read_all[T](
    page: Callable[[ExportAfter | None, int], Sequence[T]],
    key: Callable[[T], ExportAfter],
    page_size: int,
) -> list[T]:
    """Every row of a section, a page at a time, each page starting after the last row of the
    one before."""
    found: list[T] = []
    after: ExportAfter | None = None
    while True:
        rows = page(after, page_size)
        found.extend(rows)
        if len(rows) < page_size:
            return found
        after = key(rows[-1])


def export_row(record: object) -> ExportRow:
    """A domain record as a row of the export: its fields by name, the tenant's id left off."""
    if not is_dataclass(record) or isinstance(record, type):
        raise TypeError(f"{type(record).__name__} is not a domain record")
    return {
        field.name: json_value(getattr(record, field.name))
        for field in fields(record)
        if field.name not in LEFT_OFF
    }


def json_value(value: object) -> Any:
    """``value`` as a JSON value: ids and UUIDs as strings, instants in UTC and days in ISO 8601,
    decimals as strings, enums as their values, sequences as lists, records as objects."""
    if isinstance(value, Enum):
        return json_value(value.value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, EntityId):
        return str(value.value)
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list | tuple | frozenset | set):
        items = [json_value(item) for item in value]
        return items if isinstance(value, list | tuple) else sorted(items, key=str)
    if isinstance(value, Mapping):
        return {str(name): json_value(item) for name, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value)}
    raise TypeError(f"{type(value).__name__} has no JSON form in the export")
