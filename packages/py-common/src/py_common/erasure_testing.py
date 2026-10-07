"""Test helpers for the erasure consumers (``py_common.erasure``): ``FakeIdentity``, the check a
consumer's verifier answers, and ``assert_nothing_left``, the catalog's check of an erasure on
Postgres that each service's integration test runs."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol

from sqlalchemy import Connection, text

from domain_kernel.erasure import ErasureCheck, Retained
from domain_kernel.ids import EventId, TenantId


@dataclass
class FakeIdentity:
    """Identity as an erasure consumer's verifier sees it: every tenant is ``status`` and
    ``sent`` is the event its open deletion request was sent as (None: no open request). It
    notes every tenant it was asked about in ``asked``."""

    sent: EventId | None
    status: str = "deletion_requested"
    internal: bool = False
    asked: list[TenantId] = field(default_factory=list)

    def check(self, tenant_id: TenantId) -> ErasureCheck:
        self.asked.append(tenant_id)
        return ErasureCheck(
            tenant_id, self.status, internal=self.internal, deletion_event_id=self.sent
        )


TENANT_COLUMNS_SQL: Final = (
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE table_schema = :schema AND (column_name = 'tenant_id' "
    "OR column_name LIKE '%\\_tenant\\_id') ORDER BY table_name, column_name"
)
"""Every column of a schema that names a tenant: ``tenant_id``, or ``<something>_tenant_id``."""


def tenant_columns(connection: Connection, schema: str) -> list[tuple[str, str]]:
    """``(table, column)`` for every column of ``schema`` that names a tenant, by the catalog."""
    rows = connection.execute(text(TENANT_COLUMNS_SQL), {"schema": schema})
    return [(str(row.table_name), str(row.column_name)) for row in rows]


class ErasureAnswer(Protocol):
    """What an erasure said it did: ``Erased``, or the ``TenantDataErased`` that carries it."""

    @property
    def tables(self) -> Mapping[str, int]: ...

    @property
    def retained(self) -> tuple[Retained, ...]: ...


def assert_nothing_left(
    connection: Connection, schema: str, tenant_id: TenantId, erased: ErasureAnswer
) -> dict[str, int]:
    """The catalog's check of an erasure, on a connection that sees every row (the schema's
    owner): every table of ``schema`` with a tenant column is one the eraser erased or one it
    retained with a reason, and no table it did not retain holds a row naming the tenant.
    Answers the rows each retained table still holds of the tenant."""
    columns = tenant_columns(connection, schema)
    assert columns, f"{schema} has no tenant columns: is it migrated?"
    kept = {item.table: item.reason for item in erased.retained}
    unknown = sorted({table for table, _ in columns} - set(erased.tables) - set(kept))
    assert not unknown, (
        f"tables of {schema} with a tenant column the eraser neither erases nor retains: "
        f"{unknown}; erase them, or retain them with a reason"
    )
    left: dict[str, int] = {}
    retained: dict[str, int] = {}
    for table, column in columns:
        found = int(
            connection.execute(
                text(f'SELECT count(*) FROM "{schema}"."{table}" WHERE "{column}" = :tenant'),
                {"tenant": tenant_id.value},
            ).scalar_one()
        )
        if table in kept:
            assert kept[table].strip(), f"{table} is retained without a reason"
            retained[f"{table}.{column}"] = found
        elif found:
            left[f"{table}.{column}"] = found
    assert left == {}, f"rows of the erased tenant left in {schema}: {left}"
    return retained
