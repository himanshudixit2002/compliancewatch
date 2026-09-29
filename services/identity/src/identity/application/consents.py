"""Record a consent or a withdrawal, and answer what a subject has agreed to."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource, ConsentState
from identity.domain.errors import NoticeVersionRequiredError
from identity.domain.repository import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class ConsentSummary:
    subject: str
    states: tuple[ConsentState, ...]
    history: tuple[ConsentRecord, ...]

    def granted(self, purpose: ConsentPurpose) -> bool:
        return any(state.purpose is purpose and state.granted for state in self.states)


class RecordConsent:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        subject: str,
        purpose: ConsentPurpose,
        *,
        granted: bool,
        source: ConsentSource,
        notice_version: str = "",
        evidence: str = "",
        recorded_by: UserId | None = None,
    ) -> ConsentRecord:
        if granted and not notice_version.strip():
            raise NoticeVersionRequiredError(purpose.value)
        record = ConsentRecord(
            id=ConsentId.new(),
            tenant_id=tenant_id,
            subject=subject,
            purpose=purpose,
            granted=granted,
            source=source,
            recorded_at=self._clock(),
            notice_version=notice_version.strip(),
            evidence=evidence,
            recorded_by=recorded_by,
        )
        with self._unit_of_work(tenant_id) as uow:
            uow.consents.add(record)
        return record


class ConsentStatus:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, subject: str) -> ConsentSummary:
        with self._unit_of_work(tenant_id) as uow:
            history = tuple(uow.consents.history(subject))
        latest: dict[ConsentPurpose, ConsentRecord] = {}
        for record in history:
            latest[record.purpose] = record
        states = tuple(
            ConsentState(
                purpose=record.purpose,
                granted=record.granted,
                notice_version=record.notice_version,
                since=record.recorded_at,
                source=record.source,
            )
            for record in latest.values()
        )
        return ConsentSummary(subject, states, history)
