"""The tenant's data export on the memory store: only the asked tenant's rows, every section
present even when empty, each oldest first and then by id, rows as plain JSON values, and every
row read across several keyset pages."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from domain_kernel.ids import TenantId, UserId
from obligation.application.export import (
    SECTIONS,
    ExportTenantData,
    TenantDataExport,
    export_row,
)
from obligation.domain.model import Obligation
from obligation.domain.repository import ExportAfter
from obligation.infrastructure.memory import MemoryObligationRepository, MemoryStore
from obligation.testing import TenantRecords, tenant_records

MADE = datetime(2000, 1, 5, 4, 30, tzinfo=UTC)
GENERATED = datetime(2000, 3, 1, 12, 0, tzinfo=UTC)
OWNER = UserId(UUID(int=0x0E1))


def store_with(store: MemoryStore, *records: TenantRecords) -> None:
    for record in records:
        with store(record.obligation.tenant_id) as uow:
            uow.obligations.add(record.obligation)
            for change in record.changes:
                uow.history.append(change)
            uow.comments.add(record.comment)


def export(store: MemoryStore, tenant: TenantId, page_size: int = 500) -> TenantDataExport:
    return ExportTenantData(store, lambda: GENERATED, page_size=page_size).run(tenant)


def ids(rows: object) -> list[str]:
    assert isinstance(rows, list)
    return [row["id"] for row in rows]


def test_the_export_holds_only_the_asked_tenants_rows_oldest_first() -> None:
    store, tenant, other = MemoryStore(), TenantId.new(), TenantId.new()
    later = tenant_records(tenant, MADE + timedelta(days=1))
    earlier = tenant_records(tenant, MADE, closed_by=OWNER)
    theirs = tenant_records(other, MADE)
    store_with(store, later, theirs, earlier)

    found = export(store, tenant)

    assert (found.service, found.tenant_id, found.generated_at) == ("obligation", tenant, GENERATED)
    assert tuple(found.sections) == SECTIONS
    sections = found.sections
    assert ids(sections["obligations"]) == [
        str(earlier.obligation.id.value),
        str(later.obligation.id.value),
    ]
    assert ids(sections["changes"]) == [
        str(change.id.value) for change in (*earlier.changes, *later.changes)
    ]
    assert ids(sections["comments"]) == [
        str(earlier.comment.id.value),
        str(later.comment.id.value),
    ]
    text = json.dumps(sections)
    assert str(other.value) not in text, "another tenant's id"
    assert str(theirs.obligation.id.value) not in text
    assert all("tenant_id" not in row for rows in sections.values() for row in rows)


def test_rows_carry_the_record_fields_as_json_values() -> None:
    store, tenant = MemoryStore(), TenantId.new()
    records = tenant_records(tenant, MADE, closed_by=OWNER)
    store_with(store, records)

    sections = export(store, tenant).sections
    obligation, closed = records.obligation, records.changes[-1]

    assert sections["obligations"] == [
        {
            "id": str(obligation.id.value),
            "business_id": str(obligation.business_id.value),
            "rule_version_id": str(obligation.rule_version_id.value),
            "decision_id": str(obligation.decision_id.value),
            "title": "Example return (synthetic)",
            "steps": ["Reconcile", "File"],
            "evidence_type": "filing_acknowledgement",
            "period": {"start": "2000-01-01", "end": "2000-02-01", "label": "2000-01"},
            "due_at": "2000-02-20T18:29:59+00:00",
            "status": "done",
            "created_at": "2000-01-05T04:30:00+00:00",
            "updated_at": "2000-01-05T04:31:00+00:00",
            "closed_at": "2000-01-05T04:31:00+00:00",
            "closed_reason": "completed",
            "closed_by": str(OWNER.value),
            "profile_version": 1,
            "assignee_id": None,
        }
    ]
    assert sections["changes"][-1] == export_row(closed)
    assert sections["changes"][-1]["kind"] == "closed"
    assert sections["changes"][-1]["status_after"] == "done"
    assert sections["comments"] == [
        {
            "id": str(records.comment.id.value),
            "obligation_id": str(obligation.id.value),
            "author_id": str(OWNER.value),
            "author_label": "owner",
            "body": "Example comment (synthetic)",
            "created_at": "2000-01-05T04:30:00+00:00",
        }
    ]
    json.dumps(sections)


def test_a_tenant_with_nothing_gets_every_section_empty() -> None:
    store = MemoryStore()
    store_with(store, tenant_records(TenantId.new(), MADE))

    found = export(store, TenantId.new())

    assert found.sections == {section: [] for section in SECTIONS}


@pytest.mark.parametrize("count", [4, 5])
def test_every_row_is_read_across_pages(count: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pages of two: a short last page, and a last page that is full, so one more read comes
    back empty. Rows made at one instant are ordered by id."""
    store, tenant = MemoryStore(), TenantId.new()
    records = [tenant_records(tenant, MADE + timedelta(hours=index // 2)) for index in range(count)]
    store_with(store, *records)
    reads: list[ExportAfter | None] = []
    page = MemoryObligationRepository.export_page

    def counted(
        self: MemoryObligationRepository, after: ExportAfter | None, limit: int
    ) -> Sequence[Obligation]:
        reads.append(after)
        return page(self, after, limit)

    monkeypatch.setattr(MemoryObligationRepository, "export_page", counted)

    found = export(store, tenant, page_size=2)

    expected = sorted(records, key=lambda r: (r.obligation.created_at, r.obligation.id.value))
    assert ids(found.sections["obligations"]) == [str(r.obligation.id.value) for r in expected]
    comments = sorted((r.comment for r in records), key=lambda c: (c.created_at, c.id.value))
    assert ids(found.sections["comments"]) == [str(c.id.value) for c in comments]
    assert len(found.sections["changes"]) == count
    assert len(reads) == count // 2 + 1
    assert reads[0] is None
    assert reads[1] == ExportAfter(
        expected[1].obligation.created_at, expected[1].obligation.id.value
    )


def test_the_page_size_is_at_least_one() -> None:
    with pytest.raises(ValueError, match="page_size"):
        ExportTenantData(MemoryStore(), page_size=0)
