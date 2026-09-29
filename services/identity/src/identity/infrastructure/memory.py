"""In-memory consent stores: tests, demos and the app before Postgres."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from domain_kernel.ids import TenantId
from identity.domain.channel_consent import (
    ChannelConsentRecord,
    ChannelUnitOfWork,
    ConsentChannel,
)
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


class MemoryChannelConsentRepository:
    def __init__(self, records: list[ChannelConsentRecord]) -> None:
        self._records = records

    def add(self, record: ChannelConsentRecord) -> ChannelConsentRecord:
        existing = self.by_message(record.channel, record.message_id)
        if existing is not None:
            return existing
        self._records.append(record)
        return record

    def by_message(self, channel: ConsentChannel, message_id: str) -> ChannelConsentRecord | None:
        if not message_id:
            return None
        return next(
            (r for r in self._records if r.channel is channel and r.message_id == message_id),
            None,
        )

    def history(
        self, channel: ConsentChannel, subject: str, purpose: ConsentPurpose | None = None
    ) -> list[ChannelConsentRecord]:
        return [
            r
            for r in self._records
            if r.channel is channel
            and r.subject == subject
            and (purpose is None or r.purpose is purpose)
        ]


class MemoryChannelUnitOfWork:
    def __init__(self, records: list[ChannelConsentRecord]) -> None:
        self.channel_consents = MemoryChannelConsentRepository(records)


class MemoryChannelStore:
    """Channel consents without a tenant. Records are kept only when the unit of work ends
    without an error, as a Postgres transaction would."""

    def __init__(self) -> None:
        self.records: list[ChannelConsentRecord] = []

    def __call__(self) -> AbstractContextManager[ChannelUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[ChannelUnitOfWork]:
        pending = list(self.records)
        yield MemoryChannelUnitOfWork(pending)
        self.records[:] = pending
