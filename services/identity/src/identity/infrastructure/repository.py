"""The Postgres units of work: one transaction with the tenant setting for row-level security
(or none, for the subject index), with the outbox writer as the event sink, and one without a
tenant for channel consents."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Self

from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.access import Role, Scope
from domain_kernel.events import DomainEvent
from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.domain.channel_consent import (
    ChannelConsentRecord,
    ChannelUnitOfWork,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource
from identity.domain.errors import InternalTenantExistsError, SubjectRegisteredError
from identity.domain.repository import UnitOfWork
from identity.domain.service_clients import ServiceClient
from identity.domain.tenancy import (
    Contact,
    SubjectEntry,
    Tenant,
    TenantKind,
    TenantStatus,
    User,
    UserStatus,
)
from identity.infrastructure.models import (
    INTERNAL_TENANT_INDEX,
    TENANT_SETTING,
    ChannelConsentRow,
    ConsentRow,
    ServiceClientRow,
    TenantRow,
    UserRow,
    UserSubjectRow,
)
from py_common.outbox import OutboxWriter


class SqlAlchemyConsentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

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


class SqlAlchemyTenantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant: Tenant) -> None:
        """Insert ``tenant``; a second internal tenant is ``InternalTenantExistsError``."""
        self._session.add(
            TenantRow(
                id=tenant.id.value,
                kind=tenant.kind.value,
                name=tenant.name,
                region=tenant.region,
                status=tenant.status.value,
                created_at=tenant.created_at,
            )
        )
        try:
            self._session.flush()
        except IntegrityError as exc:
            if INTERNAL_TENANT_INDEX in str(exc.orig):
                raise InternalTenantExistsError() from exc
            raise

    def get(self, tenant_id: TenantId) -> Tenant | None:
        row = self._session.get(TenantRow, tenant_id.value)
        if row is None:
            return None
        return Tenant(
            id=TenantId(row.id),
            kind=TenantKind(row.kind),
            name=row.name,
            created_at=row.created_at,
            region=row.region,
            status=TenantStatus(row.status),
        )


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> None:
        self._session.add(_user_row(user))
        self._session.flush()

    def save(self, user: User) -> None:
        self._session.merge(_user_row(user))
        self._session.flush()

    def get(self, user_id: UserId) -> User | None:
        row = self._session.get(UserRow, user_id.value)
        return None if row is None else _to_user(row)

    def list(self) -> list[User]:
        rows = self._session.scalars(select(UserRow).order_by(UserRow.created_at, UserRow.id))
        return [_to_user(row) for row in rows]


class SqlAlchemySubjectIndex:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: SubjectEntry) -> None:
        """Insert unless the provider's subject is taken; two sign-ups racing for one subject
        still make one row, and the second gets ``SubjectRegisteredError``."""
        statement = (
            insert(UserSubjectRow)
            .values(
                provider=entry.provider,
                provider_subject=entry.provider_subject,
                user_id=entry.user_id.value,
                tenant_id=entry.tenant_id.value,
            )
            .on_conflict_do_nothing(index_elements=["provider", "provider_subject"])
            .returning(UserSubjectRow.provider)
        )
        if self._session.execute(statement).scalar_one_or_none() is None:
            raise SubjectRegisteredError()

    def find(self, provider: str, provider_subject: str) -> SubjectEntry | None:
        row = self._session.get(UserSubjectRow, (provider, provider_subject))
        if row is None:
            return None
        return SubjectEntry(
            row.provider, row.provider_subject, UserId(row.user_id), TenantId(row.tenant_id)
        )


class SqlAlchemyServiceClientRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, client: ServiceClient) -> None:
        self._session.add(_client_row(client))
        self._session.flush()

    def save(self, client: ServiceClient) -> None:
        self._session.merge(_client_row(client))
        self._session.flush()

    def get(self, client_id: str) -> ServiceClient | None:
        row = self._session.get(ServiceClientRow, client_id)
        return None if row is None else _to_client(row)

    def list(self) -> list[ServiceClient]:
        rows = self._session.scalars(select(ServiceClientRow).order_by(ServiceClientRow.client_id))
        return [_to_client(row) for row in rows]


class OutboxSink:
    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DomainEvent) -> None:
        self._writer.write(self._connection, event)


class SqlAlchemyUnitOfWork:
    """One transaction. The tenant setting is set only when a tenant is given; without one,
    row-level security hides every tenant row and the subject index is what is left."""

    def __init__(self, session: Session, tenant_id: TenantId | None, writer: OutboxWriter) -> None:
        connection = session.connection()
        if tenant_id is not None:
            connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": TENANT_SETTING, "value": str(tenant_id)},
            )
        self.consents = SqlAlchemyConsentRepository(session)
        self.tenants = SqlAlchemyTenantRepository(session)
        self.users = SqlAlchemyUserRepository(session)
        self.subjects = SqlAlchemySubjectIndex(session)
        self.service_clients = SqlAlchemyServiceClientRepository(session)
        self.events = OutboxSink(connection, writer)


class PostgresUnitOfWorkFactory:
    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    def __call__(self, tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def channel_unit_of_work(self) -> "PostgresChannelUnitOfWorkFactory":
        """The tenant-less unit of work for channel consents, on the same engine."""
        return PostgresChannelUnitOfWorkFactory(self._engine)

    @contextmanager
    def _open(self, tenant_id: TenantId | None) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, tenant_id, self._writer)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def _user_row(user: User) -> UserRow:
    return UserRow(
        id=user.id.value,
        tenant_id=user.tenant_id.value,
        provider=user.provider,
        provider_subject=user.provider_subject,
        email=user.contact.email,
        phone=user.contact.phone,
        display_name=user.display_name,
        roles=sorted(role.value for role in user.roles),
        status=user.status.value,
        session_version=user.session_version,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _to_user(row: UserRow) -> User:
    return User(
        id=UserId(row.id),
        tenant_id=TenantId(row.tenant_id),
        provider=row.provider,
        provider_subject=row.provider_subject,
        contact=Contact(email=row.email, phone=row.phone),
        roles=frozenset(Role(role) for role in row.roles),
        created_at=row.created_at,
        updated_at=row.updated_at,
        display_name=row.display_name,
        status=UserStatus(row.status),
        session_version=row.session_version,
    )


def _client_row(client: ServiceClient) -> ServiceClientRow:
    return ServiceClientRow(
        client_id=client.client_id,
        secret_sha256=client.secret_sha256,
        scopes=sorted(scope.value for scope in client.scopes),
        created_at=client.created_at,
        revoked_at=client.revoked_at,
    )


def _to_client(row: ServiceClientRow) -> ServiceClient:
    """A stored client; a scope this code no longer knows is left out, so it grants nothing."""
    known = {scope.value: scope for scope in Scope}
    return ServiceClient(
        client_id=row.client_id,
        secret_sha256=row.secret_sha256,
        scopes=frozenset(known[value] for value in row.scopes if value in known),
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


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
