"""The Postgres units of work: one transaction with the tenant setting for row-level security
(or none, for the subject index), with the billing ledger, the data requests, the outbox writer
as the event sink and ``py_common.audit``'s writer as the audit sink, and one without a tenant
for channel consents.

Tenant, user and consent reads also name the unit of work's tenant in the query. Row-level
security applies only to a role that does not bypass it, and the dev stack connects as the
database's owner, so the filter keeps tenants apart there too; with no tenant they find nothing,
as row-level security would."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from typing import Any, Self

from sqlalchemy import (
    Connection,
    Engine,
    Select,
    create_engine,
    delete,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.access import Role, Scope
from domain_kernel.events import DomainEvent
from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.domain.billing import (
    Customer,
    StartAttempt,
    StoredBillingEvent,
    Subscription,
    SubscriptionStatus,
)
from identity.domain.channel_consent import (
    ChannelConsentRecord,
    ChannelUnitOfWork,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource
from identity.domain.data_requests import (
    DataRequest,
    DataRequestId,
    DataRequestKind,
    DataRequestSource,
    DataRequestStatus,
    OpenRequests,
    counts_by_kind,
)
from identity.domain.errors import InternalTenantExistsError, SubjectRegisteredError
from identity.domain.pages import ExportAfter
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
    BillingCustomerRow,
    BillingEventRow,
    BillingStartRow,
    BillingSubscriptionRow,
    ChannelConsentRow,
    ConsentRow,
    DataRequestRow,
    ServiceClientRow,
    TenantRow,
    UserRow,
    UserSubjectRow,
)
from py_common.audit.writer import PostgresAuditSink
from py_common.outbox import OutboxWriter


class SqlAlchemyConsentRepository:
    def __init__(self, session: Session, tenant_id: TenantId | None) -> None:
        self._session = session
        self._tenant = tenant_id

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
        if self._tenant is None:
            return []
        statement = (
            select(ConsentRow)
            .where(ConsentRow.tenant_id == self._tenant.value, ConsentRow.subject == subject)
            .order_by(ConsentRow.recorded_at, ConsentRow.id)
        )
        if purpose is not None:
            statement = statement.where(ConsentRow.purpose == purpose.value)
        return [_to_record(row) for row in self._session.scalars(statement).all()]

    def page(self, after: ExportAfter | None, limit: int) -> list[ConsentRecord]:
        if self._tenant is None:
            return []
        statement = _paged(
            select(ConsentRow).where(ConsentRow.tenant_id == self._tenant.value),
            (ConsentRow.recorded_at, ConsentRow.id),
            after,
            limit,
        )
        return [_to_record(row) for row in self._session.scalars(statement).all()]


def _paged[R](
    statement: Select[R],
    order: tuple[Any, Any],
    after: ExportAfter | None,
    limit: int,
) -> Select[R]:
    """``statement`` oldest first by ``order`` (a time column, then the id), at most ``limit``
    rows, after ``after``: one page of an export."""
    if after is not None:
        statement = statement.where(tuple_(*order) > tuple_(after.at, after.id))
    return statement.order_by(*order).limit(limit)


class SqlAlchemyDataRequestRepository:
    """The tenant's data requests. Reads name the tenant too, as the other repositories do;
    with no tenant they find nothing and writes are refused by the policy."""

    def __init__(self, session: Session, tenant_id: TenantId | None) -> None:
        self._session = session
        self._tenant = tenant_id

    def add(self, request: DataRequest) -> None:
        self._session.add(_data_request_row(request))
        self._session.flush()

    def save(self, request: DataRequest) -> None:
        if self._tenant is None:
            return
        self._session.execute(
            update(DataRequestRow)
            .where(
                DataRequestRow.id == request.id.value,
                DataRequestRow.tenant_id == self._tenant.value,
                DataRequestRow.tenant_id == request.tenant_id.value,
            )
            .values(
                status=request.status.value,
                services_done=list(request.services_done),
                completed_at=request.completed_at,
            )
            .execution_options(synchronize_session=False)
        )

    def get(self, request_id: DataRequestId) -> DataRequest | None:
        return self._one(request_id, lock=False)

    def lock(self, request_id: DataRequestId) -> DataRequest | None:
        return self._one(request_id, lock=True)

    def _one(self, request_id: DataRequestId, *, lock: bool) -> DataRequest | None:
        if self._tenant is None:
            return None
        statement = (
            select(DataRequestRow)
            .where(
                DataRequestRow.id == request_id.value,
                DataRequestRow.tenant_id == self._tenant.value,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        row = self._session.scalars(statement).one_or_none()
        return None if row is None else _to_data_request(row)

    def page(self, after: ExportAfter | None, limit: int) -> list[DataRequest]:
        if self._tenant is None:
            return []
        statement = _paged(
            select(DataRequestRow).where(DataRequestRow.tenant_id == self._tenant.value),
            (DataRequestRow.requested_at, DataRequestRow.id),
            after,
            limit,
        )
        return [_to_data_request(row) for row in self._session.scalars(statement)]

    def list(self) -> list[DataRequest]:
        if self._tenant is None:
            return []
        rows = self._session.scalars(
            select(DataRequestRow)
            .where(DataRequestRow.tenant_id == self._tenant.value)
            .order_by(DataRequestRow.requested_at.desc(), DataRequestRow.id.desc())
            .execution_options(populate_existing=True)
        )
        return [_to_data_request(row) for row in rows]

    def open_deletion(self) -> DataRequest | None:
        if self._tenant is None:
            return None
        row = self._session.scalars(
            select(DataRequestRow)
            .where(
                DataRequestRow.tenant_id == self._tenant.value,
                DataRequestRow.kind == DataRequestKind.DELETION.value,
                DataRequestRow.status != DataRequestStatus.COMPLETED.value,
            )
            .order_by(DataRequestRow.requested_at.desc(), DataRequestRow.id.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else _to_data_request(row)


def _data_request_row(request: DataRequest) -> DataRequestRow:
    return DataRequestRow(
        id=request.id.value,
        tenant_id=request.tenant_id.value,
        kind=request.kind.value,
        source=request.source.value,
        requested_by=request.requested_by,
        reason=request.reason,
        requested_at=request.requested_at,
        deadline_at=request.deadline_at,
        status=request.status.value,
        services_done=list(request.services_done),
        completed_at=request.completed_at,
    )


def _to_data_request(row: DataRequestRow) -> DataRequest:
    return DataRequest(
        id=DataRequestId(row.id),
        tenant_id=TenantId(row.tenant_id),
        kind=DataRequestKind(row.kind),
        source=DataRequestSource(row.source),
        requested_by=row.requested_by,
        reason=row.reason,
        requested_at=row.requested_at,
        deadline_at=row.deadline_at,
        status=DataRequestStatus(row.status),
        services_done=tuple(sorted(set(row.services_done))),
        completed_at=row.completed_at,
    )


OPEN_REQUESTS_SQL = "SELECT kind, open, overdue FROM identity.data_requests_open()"
"""The directory function infra/dev/postgres/roles.sql makes: counts of every tenant's open
requests, which row-level security would hide from this service's own role."""


class PostgresDataRequestDirectory:
    """``DataRequestDirectory`` through ``identity.data_requests_open()``, which runs as the
    NOLOGIN role cw_identity_directory and answers counts only. Until the role step has made the
    function, the read fails and the gauges report nothing."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def open_counts(self) -> list[OpenRequests]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(OPEN_REQUESTS_SQL)).all()
        return counts_by_kind(
            OpenRequests(DataRequestKind(row.kind), int(row.open), int(row.overdue))
            for row in rows
            if row.kind in {kind.value for kind in DataRequestKind}
        )


class SqlAlchemyTenantRepository:
    def __init__(self, session: Session, tenant_id: TenantId | None) -> None:
        self._session = session
        self._tenant = tenant_id

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
        if tenant_id != self._tenant:
            return None
        row = self._session.get(TenantRow, tenant_id.value)
        return None if row is None else _to_tenant(row)

    def lock(self, tenant_id: TenantId) -> Tenant | None:
        """The tenant, read with SELECT ... FOR UPDATE: its row stays locked until the
        transaction ends."""
        if tenant_id != self._tenant:
            return None
        row = self._session.scalars(
            select(TenantRow)
            .where(TenantRow.id == tenant_id.value)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else _to_tenant(row)

    def save(self, tenant: Tenant) -> None:
        if tenant.id != self._tenant:
            return
        self._session.execute(
            update(TenantRow)
            .where(TenantRow.id == tenant.id.value)
            .values(status=tenant.status.value, name=tenant.name)
            .execution_options(synchronize_session=False)
        )


class SqlAlchemyUserRepository:
    def __init__(self, session: Session, tenant_id: TenantId | None) -> None:
        self._session = session
        self._tenant = tenant_id

    def add(self, user: User) -> None:
        self._session.add(_user_row(user))
        self._session.flush()

    def save(self, user: User) -> None:
        self._session.merge(_user_row(user))
        self._session.flush()

    def get(self, user_id: UserId) -> User | None:
        if self._tenant is None:
            return None
        row = self._session.scalars(
            select(UserRow).where(
                UserRow.id == user_id.value, UserRow.tenant_id == self._tenant.value
            )
        ).one_or_none()
        return None if row is None else _to_user(row)

    def page(self, after: ExportAfter | None, limit: int) -> list[User]:
        if self._tenant is None:
            return []
        statement = _paged(
            select(UserRow).where(UserRow.tenant_id == self._tenant.value),
            (UserRow.created_at, UserRow.id),
            after,
            limit,
        )
        return [_to_user(row) for row in self._session.scalars(statement)]

    def list(self) -> list[User]:
        if self._tenant is None:
            return []
        rows = self._session.scalars(
            select(UserRow)
            .where(UserRow.tenant_id == self._tenant.value)
            .order_by(UserRow.created_at, UserRow.id)
        )
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


class SqlAlchemyBillingRepository:
    """The tenant's billing ledger. Reads name the tenant too (the dev stack's owner role is not
    held to row-level security); with no tenant they find nothing and writes are refused by the
    policy."""

    def __init__(self, session: Session, tenant_id: TenantId | None) -> None:
        self._session = session
        self._tenant = tenant_id

    def customer(self) -> Customer | None:
        if self._tenant is None:
            return None
        row = self._session.get(BillingCustomerRow, self._tenant.value)
        if row is None:
            return None
        return Customer(TenantId(row.tenant_id), row.provider_customer_id, row.email, row.name)

    def add_customer(self, customer: Customer, *, provider: str, at: datetime) -> bool:
        """Insert unless the tenant has a customer already: two first starts racing each other
        keep the customer stored first."""
        statement = (
            insert(BillingCustomerRow)
            .values(
                tenant_id=customer.tenant_id.value,
                provider=provider,
                provider_customer_id=customer.provider_customer_id,
                email=customer.email,
                name=customer.name,
                created_at=at,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id"])
            .returning(BillingCustomerRow.tenant_id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def subscription(self, provider_subscription_id: str) -> Subscription | None:
        if self._tenant is None:
            return None
        row = self._session.scalars(
            select(BillingSubscriptionRow)
            .where(
                BillingSubscriptionRow.provider_subscription_id == provider_subscription_id,
                BillingSubscriptionRow.tenant_id == self._tenant.value,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else _to_subscription(row)

    def subscriptions(self) -> list[Subscription]:
        if self._tenant is None:
            return []
        rows = self._session.scalars(
            select(BillingSubscriptionRow)
            .where(BillingSubscriptionRow.tenant_id == self._tenant.value)
            .order_by(
                BillingSubscriptionRow.started_at.desc(),
                BillingSubscriptionRow.provider_subscription_id.desc(),
            )
            .execution_options(populate_existing=True)
        )
        return [_to_subscription(row) for row in rows]

    def add_subscription(self, subscription: Subscription) -> bool:
        """Insert unless the provider id exists: the tenant's own row (a webhook and a start
        racing each other) or, hidden by row-level security, another tenant's. Either way the
        row is left as it is."""
        statement = (
            insert(BillingSubscriptionRow)
            .values(
                provider_subscription_id=subscription.provider_subscription_id,
                tenant_id=subscription.tenant_id.value,
                plan_key=subscription.plan_key,
                quantity=subscription.quantity,
                status=subscription.status.value,
                started_at=subscription.started_at,
                updated_at=subscription.updated_at or subscription.started_at,
                checkout_url=subscription.checkout_url,
                last_event_at=subscription.last_event_at,
                past_due_since=subscription.past_due_since,
            )
            .on_conflict_do_nothing(index_elements=["provider_subscription_id"])
            .returning(BillingSubscriptionRow.provider_subscription_id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def update_subscription(self, subscription: Subscription) -> None:
        """Update the tenant's own row only: the statement names the tenant as well as the id,
        so even a role not held to row-level security never moves another tenant's row."""
        if self._tenant is None:
            return
        self._session.execute(
            update(BillingSubscriptionRow)
            .where(
                BillingSubscriptionRow.provider_subscription_id
                == subscription.provider_subscription_id,
                BillingSubscriptionRow.tenant_id == self._tenant.value,
                BillingSubscriptionRow.tenant_id == subscription.tenant_id.value,
            )
            .values(
                status=subscription.status.value,
                quantity=subscription.quantity,
                updated_at=subscription.updated_at or subscription.started_at,
                last_event_at=subscription.last_event_at,
                past_due_since=subscription.past_due_since,
            )
            .execution_options(synchronize_session=False)
        )

    def start_attempt(self, key: str) -> StartAttempt | None:
        if self._tenant is None:
            return None
        row = self._session.scalars(
            select(BillingStartRow).where(
                BillingStartRow.tenant_id == self._tenant.value,
                BillingStartRow.idempotency_key == key,
            )
        ).one_or_none()
        if row is None:
            return None
        return StartAttempt(
            tenant_id=TenantId(row.tenant_id),
            key=row.idempotency_key,
            plan_key=row.plan_key,
            quantity=row.quantity,
            created_at=row.created_at,
            provider_subscription_id=row.provider_subscription_id,
            checkout_url=row.checkout_url,
            recorded_at=row.recorded_at,
        )

    def claim_start(self, attempt: StartAttempt) -> bool:
        statement = (
            insert(BillingStartRow)
            .values(
                tenant_id=attempt.tenant_id.value,
                idempotency_key=attempt.key,
                plan_key=attempt.plan_key,
                quantity=attempt.quantity,
                created_at=attempt.created_at,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
            .returning(BillingStartRow.idempotency_key)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def record_started(
        self, key: str, *, provider_subscription_id: str, checkout_url: str, at: datetime
    ) -> None:
        if self._tenant is None:
            return
        self._session.execute(
            update(BillingStartRow)
            .where(
                BillingStartRow.tenant_id == self._tenant.value,
                BillingStartRow.idempotency_key == key,
            )
            .values(
                provider_subscription_id=provider_subscription_id,
                checkout_url=checkout_url,
                recorded_at=at,
            )
            .execution_options(synchronize_session=False)
        )

    def release_start(self, key: str) -> None:
        if self._tenant is None:
            return
        self._session.execute(
            delete(BillingStartRow)
            .where(
                BillingStartRow.tenant_id == self._tenant.value,
                BillingStartRow.idempotency_key == key,
                BillingStartRow.provider_subscription_id.is_(None),
            )
            .execution_options(synchronize_session=False)
        )

    def append_event(self, event: StoredBillingEvent) -> bool:
        """Insert unless the tenant holds the body's digest already; two deliveries racing each
        other still make one row."""
        statement = (
            insert(BillingEventRow)
            .values(
                id=event.id,
                tenant_id=event.tenant_id.value,
                provider_subscription_id=event.provider_subscription_id,
                kind=event.kind,
                status=None if event.status is None else event.status.value,
                occurred_at=event.occurred_at,
                received_at=event.received_at,
                body_sha256=event.body_sha256,
                raw_event=dict(event.raw_event),
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "body_sha256"])
            .returning(BillingEventRow.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def events_page(self, after: ExportAfter | None, limit: int) -> list[StoredBillingEvent]:
        if self._tenant is None:
            return []
        rows = self._session.scalars(
            _paged(
                select(BillingEventRow).where(BillingEventRow.tenant_id == self._tenant.value),
                (BillingEventRow.received_at, BillingEventRow.id),
                after,
                limit,
            )
        )
        return [
            StoredBillingEvent(
                id=row.id,
                tenant_id=TenantId(row.tenant_id),
                provider_subscription_id=row.provider_subscription_id,
                kind=row.kind,
                status=None if row.status is None else SubscriptionStatus(row.status),
                occurred_at=row.occurred_at,
                received_at=row.received_at,
                body_sha256=row.body_sha256,
                raw_event=dict(row.raw_event),
            )
            for row in rows
        ]


def _to_subscription(row: BillingSubscriptionRow) -> Subscription:
    return Subscription(
        tenant_id=TenantId(row.tenant_id),
        plan_key=row.plan_key,
        provider_subscription_id=row.provider_subscription_id,
        status=SubscriptionStatus(row.status),
        started_at=row.started_at,
        checkout_url=row.checkout_url,
        quantity=row.quantity,
        updated_at=row.updated_at,
        last_event_at=row.last_event_at,
        past_due_since=row.past_due_since,
    )


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
        self.consents = SqlAlchemyConsentRepository(session, tenant_id)
        self.tenants = SqlAlchemyTenantRepository(session, tenant_id)
        self.users = SqlAlchemyUserRepository(session, tenant_id)
        self.subjects = SqlAlchemySubjectIndex(session)
        self.service_clients = SqlAlchemyServiceClientRepository(session)
        self.billing = SqlAlchemyBillingRepository(session, tenant_id)
        self.data_requests = SqlAlchemyDataRequestRepository(session, tenant_id)
        self.events = OutboxSink(connection, writer)
        self.audit = PostgresAuditSink(connection)


class ConnectionUnitOfWorkFactory:
    """Units of work inside the transaction of ``connection``, such as a consumer's: a unit
    neither commits nor rolls back, so what it writes commits with what the owner of the
    connection writes (the ``processed_event`` row)."""

    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def __call__(self, tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId | None) -> Iterator[UnitOfWork]:
        if not self._connection.in_transaction():
            # Begun here, the session joins it and the owner of the connection still ends it.
            self._connection.begin()
        with Session(bind=self._connection, expire_on_commit=False) as session:
            yield SqlAlchemyUnitOfWork(session, tenant_id, self._writer)
            session.flush()


class PostgresUnitOfWorkFactory:
    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @staticmethod
    def on_connection(
        connection: Connection, *, writer: OutboxWriter | None = None
    ) -> ConnectionUnitOfWorkFactory:
        """Units of work in the transaction ``connection`` holds (a consumer's)."""
        return ConnectionUnitOfWorkFactory(connection, writer or OutboxWriter())

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


def _to_tenant(row: TenantRow) -> Tenant:
    return Tenant(
        id=TenantId(row.id),
        kind=TenantKind(row.kind),
        name=row.name,
        created_at=row.created_at,
        region=row.region,
        status=TenantStatus(row.status),
    )


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
