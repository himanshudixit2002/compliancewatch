"""The tenant's data export: everything the profile service holds for one tenant.

Identity assembles a tenant's export on download by calling ``GET /v1/profile/data-export`` on
each service. ``ExportTenantData`` reads the profile's part in one unit of work opened for the
tenant, so row-level security keeps every other tenant out in Postgres and the memory store
filters by tenant. Each section is read a page at a time (``EXPORT_PAGE_SIZE`` rows, oldest
first, then the key) and the pages are joined:

- ``nodes``: the hierarchy, entities with their PAN, registrations with their GSTIN, locations;
- ``attributes``: every stored value, known, unsure or not applicable, per financial year;
- ``versions``: the history row each save wrote;
- ``review_tasks``: open and closed.

Rows are JSON-safe: ids and datetimes as text, sets as sorted lists, decimals as text. The
tenant's id is in the export once, not on each row. Nothing here writes an audit entry: identity
records the export when it is downloaded.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import EntityId, TenantId
from profile_service.domain.model import NodeAttribute, ProfileNode, ProfileVersion, ReviewTask
from profile_service.domain.repository import (
    AttributeCursor,
    NodeCursor,
    UnitOfWorkFactory,
    VersionCursor,
)

SERVICE: Final = "profile"
EXPORT_PAGE_SIZE: Final = 500
SECTIONS: Final = ("nodes", "attributes", "versions", "review_tasks")

type Row = dict[str, Any]


@dataclass(frozen=True, slots=True)
class TenantDataExport:
    service: str
    tenant_id: TenantId
    generated_at: datetime
    sections: Mapping[str, Sequence[Row]]


class ExportTenantData:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
        page_size: int = EXPORT_PAGE_SIZE,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._page_size = page_size

    def run(self, tenant_id: TenantId) -> TenantDataExport:
        generated_at = self._clock()
        size = self._page_size
        with self._unit_of_work(tenant_id) as uow:
            profiles = uow.profiles
            nodes = _read_all(profiles.export_nodes, _node_cursor, size)
            attributes = _read_all(profiles.export_attributes, _attribute_cursor, size)
            versions = _read_all(profiles.export_versions, _version_cursor, size)
            tasks = _read_all(profiles.export_review_tasks, _task_cursor, size)
        sections: dict[str, list[Row]] = {
            "nodes": [_node(node) for node in nodes],
            "attributes": [_attribute(value) for value in attributes],
            "versions": [_version(row) for row in versions],
            "review_tasks": [_review_task(task) for task in tasks],
        }
        return TenantDataExport(
            service=SERVICE,
            tenant_id=tenant_id,
            generated_at=generated_at,
            sections=MappingProxyType(sections),
        )


def _read_all[T, C](
    fetch: Callable[[C | None, int], Sequence[T]], cursor: Callable[[T], C], size: int
) -> list[T]:
    """Every row ``fetch`` pages through, ``size`` at a time, each page starting after the
    cursor of the last row read."""
    found: list[T] = []
    while True:
        page = fetch(cursor(found[-1]) if found else None, size)
        found.extend(page)
        if len(page) < size:
            return found


def _node_cursor(node: ProfileNode) -> NodeCursor:
    return (node.created_at, node.id)


def _attribute_cursor(value: NodeAttribute) -> AttributeCursor:
    record = value.record
    if record.updated_at is None:  # NodeAttribute refuses it; the check narrows the type
        raise ValueError(f"{record.key}: an exported value has updated_at")
    fy = "" if record.as_of_fy is None else record.as_of_fy.label
    return (record.updated_at, value.node_id, record.key, fy)


def _version_cursor(row: ProfileVersion) -> VersionCursor:
    return (row.at, row.node_id, row.version)


def _task_cursor(task: ReviewTask) -> NodeCursor:
    return (task.created_at, task.id)


def _node(node: ProfileNode) -> Row:
    return {
        "id": json_safe(node.id),
        "level": json_safe(node.level),
        "key": node.key,
        "name": node.name,
        "parent_id": json_safe(node.parent_id),
        "version": node.version,
        "created_at": json_safe(node.created_at),
        "updated_at": json_safe(node.updated_at),
    }


def _attribute(value: NodeAttribute) -> Row:
    record = value.record
    return {
        "node_id": json_safe(value.node_id),
        "key": record.key,
        "as_of_fy": json_safe(record.as_of_fy),
        "state": json_safe(record.state),
        "value": json_safe(record.value),
        "source": json_safe(record.source),
        "updated_at": json_safe(record.updated_at),
    }


def _version(row: ProfileVersion) -> Row:
    return {
        "node_id": json_safe(row.node_id),
        "version": row.version,
        "changed_attributes": list(row.changed_attributes),
        "attributes": json_safe(row.attributes),
        "source": row.source,
        "changed_by": json_safe(row.changed_by),
        "at": json_safe(row.at),
    }


def _review_task(task: ReviewTask) -> Row:
    return {
        "id": json_safe(task.id),
        "node_id": json_safe(task.node_id),
        "attribute_key": task.attribute_key,
        "reason": json_safe(task.reason),
        "as_of_fy": json_safe(task.as_of_fy),
        "open": task.open,
        "created_at": json_safe(task.created_at),
    }


def json_safe(value: object) -> Any:
    """``value`` as JSON: ids and UUIDs as text, datetimes in UTC and dates as ISO 8601, decimals
    as text, enums as their values, a financial year as its label, tuples as lists and sets as
    sorted lists of text (as the Postgres store keeps them)."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, str):
        return value
    if isinstance(value, EntityId):
        return str(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, FinancialYear):
        return value.label
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return str(value)
