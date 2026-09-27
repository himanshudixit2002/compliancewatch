"""The Postgres unit of work: one transaction with the tenant setting for row-level security."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Self

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource, UnitOfWork
from identity.infrastructure.models import TENANT_SETTING, ConsentRow


class SqlAlchemyConsentRepository:
    def __init__(self, session: Session, tenant_id: TenantId) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def add(self, record: ConsentRecord) -> None:
        self._session.add(
            ConsentRow(
                id=record.id.value,
                tenant_id=record.tenant_id.value,
                subject=record.subject,
                purpose=record.purpose.value,
                granted=record.granted,
                source=record.source.value,
                notice_version=record.notice_version,
                evidence=record.evidence,
                recorded_by=None if record.recorded_by is None else record.recorded_by.value,
                recorded_at=record.recorded_at,
            )
        )
        self._session.flush()

    def history(self, subject: str, purpose: ConsentPurpose | None = None) -> list[ConsentRecord]:
        statement = (
            select(ConsentRow)
            .where(ConsentRow.subject == subject)
            .order_by(ConsentRow.recorded_at, ConsentRow.id)
        )
        if purpose is not None:
            statement = statement.where(ConsentRow.purpose == purpose.value)
        return [_to_record(row) for row in self._session.scalars(statement).all()]


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session, tenant_id: TenantId) -> None:
        session.connection().execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
        self.consents = SqlAlchemyConsentRepository(session, tenant_id)


class PostgresUnitOfWorkFactory:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, tenant_id)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def _to_record(row: ConsentRow) -> ConsentRecord:
    return ConsentRecord(
        id=ConsentId(row.id),
        tenant_id=TenantId(row.tenant_id),
        subject=row.subject,
        purpose=ConsentPurpose(row.purpose),
        granted=row.granted,
        source=ConsentSource(row.source),
        recorded_at=row.recorded_at,
        notice_version=row.notice_version,
        evidence=row.evidence,
        recorded_by=None if row.recorded_by is None else UserId(row.recorded_by),
    )
