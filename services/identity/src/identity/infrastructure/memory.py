"""In-memory consent store: tests, demos and the app before Postgres."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from domain_kernel.ids import TenantId
from identity.domain.consent import ConsentPurpose, ConsentRecord, UnitOfWork


class MemoryConsentRepository:
    def __init__(self, records: list[ConsentRecord], tenant_id: TenantId) -> None:
        self._records = records
        self._tenant = tenant_id

    def add(self, record: ConsentRecord) -> None:
        self._records.append(record)

    def history(self, subject: str, purpose: ConsentPurpose | None = None) -> list[ConsentRecord]:
        return [
            r
            for r in self._records
            if r.tenant_id == self._tenant
            and r.subject == subject
            and (purpose is None or r.purpose is purpose)
        ]


class MemoryUnitOfWork:
    def __init__(self, records: list[ConsentRecord], tenant_id: TenantId) -> None:
        self.consents = MemoryConsentRepository(records, tenant_id)


class MemoryStore:
    def __init__(self) -> None:
        self.records: list[ConsentRecord] = []

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        yield MemoryUnitOfWork(self.records, tenant_id)

    def ping(self) -> bool:
        return True
