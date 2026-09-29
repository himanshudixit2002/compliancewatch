"""The Postgres units of work: one transaction with the tenant setting for row-level security,
and one without a tenant for channel consents."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Self

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.domain.channel_consent import (
    ChannelConsentRecord,
    ChannelUnitOfWork,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource, UnitOfWork
from identity.infrastructure.models import TENANT_SETTING, ChannelConsentRow, ConsentRow


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

    @property
    def channel_unit_of_work(self) -> "PostgresChannelUnitOfWorkFactory":
        """The tenant-less unit of work for channel consents, on the same engine."""
        return PostgresChannelUnitOfWorkFactory(self._engine)

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


class SqlAlchemyChannelConsentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: ChannelConsentRecord) -> ChannelConsentRecord:
        """Insert unless the partial unique index on (channel, message_id) already holds the
        message, so two deliveries of one message racing each other still make one row."""
        statement = (
            insert(ChannelConsentRow)
            .values(
                id=record.id.value,
                channel=record.channel.value,
                subject=record.subject,
                purpose=record.purpose.value,
                granted=record.granted,
                source=record.source.value,
                notice_version=record.notice_version,
                evidence=record.evidence,
                message_id=record.message_id,
                recorded_at=record.recorded_at,
            )
            .on_conflict_do_nothing(
                index_elements=["channel", "message_id"],
                index_where=ChannelConsentRow.message_id != "",
            )
            .returning(ChannelConsentRow.id)
        )
        if self._session.execute(statement).scalar_one_or_none() is not None:
            return record
        existing = self.by_message(record.channel, record.message_id)
        if existing is None:  # pragma: no cover - the conflict names a stored row
            raise RuntimeError("channel consent insert conflicted with no stored message")
        return existing

    def by_message(self, channel: ConsentChannel, message_id: str) -> ChannelConsentRecord | None:
        row = self._session.scalars(
            select(ChannelConsentRow).where(
                ChannelConsentRow.channel == channel.value,
                ChannelConsentRow.message_id == message_id,
                ChannelConsentRow.message_id != "",
            )
        ).one_or_none()
        return None if row is None else _to_channel_record(row)

    def history(
        self, channel: ConsentChannel, subject: str, purpose: ConsentPurpose | None = None
    ) -> list[ChannelConsentRecord]:
        statement = (
            select(ChannelConsentRow)
            .where(ChannelConsentRow.channel == channel.value, ChannelConsentRow.subject == subject)
            .order_by(ChannelConsentRow.recorded_at, ChannelConsentRow.id)
        )
        if purpose is not None:
            statement = statement.where(ChannelConsentRow.purpose == purpose.value)
        return [_to_channel_record(row) for row in self._session.scalars(statement).all()]


class SqlAlchemyChannelUnitOfWork:
    def __init__(self, session: Session) -> None:
        self.channel_consents = SqlAlchemyChannelConsentRepository(session)


class PostgresChannelUnitOfWorkFactory:
    """One transaction without the tenant setting: channel_consent has no tenant."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __call__(self) -> AbstractContextManager[ChannelUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[ChannelUnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyChannelUnitOfWork(session)


def _to_channel_record(row: ChannelConsentRow) -> ChannelConsentRecord:
    return ChannelConsentRecord(
        id=ConsentId(row.id),
        channel=ConsentChannel(row.channel),
        subject=row.subject,
        purpose=ConsentPurpose(row.purpose),
        granted=row.granted,
        source=ConsentSource(row.source),
        recorded_at=row.recorded_at,
        notice_version=row.notice_version,
        evidence=row.evidence,
        message_id=row.message_id,
    )
