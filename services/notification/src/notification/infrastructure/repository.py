"""The Postgres units of work of the notification service.

A tenant unit is one transaction with ``app.tenant_id`` set for row-level security. Its
repositories share the unit's session: the tenant's recipients and notifications, the work queue
entries of those notifications, and the consents, suppressions and directory entries of every
address (tables without row-level security). Events go to the outbox on the same connection, so
an event commits or rolls back with the change that made it.

``PostgresUnitOfWorkFactory(tenant_id)`` opens a tenant unit on its own transaction; ``shared()``
opens one without a tenant, for consents, suppressions and the directory. A consumer runs its
handler on the connection of its inbox transaction instead: ``SqlAlchemyUnitOfWork.on_connection``
joins that transaction, so the handler's writes, its outbox rows and the ``processed_event`` row
commit together (``py_common.outbox.sync``).
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId, UserId
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import PENDING_STATES, DeliveryState, Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import (
    ChannelPreference,
    ConsentSource,
    QuietHours,
    Suppression,
    SuppressionReason,
)
from notification.domain.recipients import (
    BusinessLink,
    DigestMode,
    Recipient,
    RecipientAddress,
    RecipientRole,
)
from notification.domain.repository import (
    DirectoryEntry,
    PageAfter,
    SharedUnitOfWork,
    UnitOfWork,
    WorkEntry,
)
from notification.infrastructure.models import (
    TENANT_SETTING,
    AddressDirectoryRow,
    ChannelPreferenceRow,
    NotificationRow,
    RecipientAddressRow,
    RecipientBusinessRow,
    RecipientRow,
    SuppressionRow,
    WorkIndexRow,
)
from notification.infrastructure.work_index import PostgresWorkIndex
from py_common.outbox import OutboxWriter

_PENDING = tuple(state.value for state in PENDING_STATES)


class SqlAlchemyPreferenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, channel: Channel, address: str) -> ChannelPreference | None:
        row = self._session.get(ChannelPreferenceRow, (channel.value, address))
        if row is None or row.opted_in is None or row.source is None or row.updated_at is None:
            return None
        return ChannelPreference(
            channel=Channel(row.channel),
            address=row.address,
            opted_in=row.opted_in,
            source=ConsentSource(row.source),
            updated_at=row.updated_at.astimezone(UTC),
            language=row.language,
            quiet_hours=QuietHours(row.quiet_hours_start, row.quiet_hours_end),
        )

    def save(self, preference: ChannelPreference) -> None:
        values = {
            "opted_in": preference.opted_in,
            "source": preference.source.value,
            "language": preference.language,
            "quiet_hours_start": preference.quiet_hours.start,
            "quiet_hours_end": preference.quiet_hours.end,
            "updated_at": preference.updated_at,
        }
        statement = insert(ChannelPreferenceRow).values(
            channel=preference.channel.value, address=preference.address, **values
        )
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["channel", "address"],
                set_={name: statement.excluded[name] for name in values},
            )
        )
        self._session.expire_all()

    def last_inbound_at(self, channel: Channel, address: str) -> datetime | None:
        at = self._session.scalar(
            select(ChannelPreferenceRow.last_inbound_at).where(
                ChannelPreferenceRow.channel == channel.value,
                ChannelPreferenceRow.address == address,
            )
        )
        return None if at is None else at.astimezone(UTC)

    def record_inbound(self, channel: Channel, address: str, at: datetime) -> None:
        statement = insert(ChannelPreferenceRow).values(
            channel=channel.value, address=address, last_inbound_at=at
        )
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["channel", "address"],
                set_={
                    "last_inbound_at": func.greatest(
                        ChannelPreferenceRow.last_inbound_at, statement.excluded.last_inbound_at
                    )
                },
            )
        )
        self._session.expire_all()


class SqlAlchemySuppressionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, channel: Channel, address: str) -> Suppression | None:
        row = self._session.get(SuppressionRow, (channel.value, address))
        if row is None:
            return None
        return Suppression(
            channel=Channel(row.channel),
            address=row.address,
            reason=SuppressionReason(row.reason),
            at=row.created_at.astimezone(UTC),
            detail=row.detail,
        )

    def add(self, suppression: Suppression) -> None:
        values = {
            "reason": suppression.reason.value,
            "detail": suppression.detail,
            "created_at": suppression.at,
        }
        statement = insert(SuppressionRow).values(
            channel=suppression.channel.value, address=suppression.address, **values
        )
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["channel", "address"],
                set_={name: statement.excluded[name] for name in values},
            )
        )
        self._session.expire_all()

    def remove(self, channel: Channel, address: str) -> bool:
        result = self._session.execute(
            delete(SuppressionRow)
            .where(SuppressionRow.channel == channel.value, SuppressionRow.address == address)
            .returning(SuppressionRow.address)
        )
        return result.first() is not None


class SqlAlchemyRecipientRepository:
    """Row-level security scopes every statement to the unit's tenant; the tenant is named in
    the statements as well, because recipients are keyed by tenant and id."""

    def __init__(self, session: Session, tenant_id: TenantId) -> None:
        self._session = session
        self._tenant = tenant_id.value

    def get(self, recipient_id: RecipientId) -> Recipient | None:
        found = self._load(
            select(RecipientRow).where(
                RecipientRow.tenant_id == self._tenant, RecipientRow.id == recipient_id.value
            )
        )
        return found[0] if found else None

    def save(self, recipient: Recipient) -> None:
        values = {
            "user_id": None if recipient.user_id is None else recipient.user_id.value,
            "role": recipient.role.value,
            "language": recipient.language,
            "digest_mode": recipient.digest_mode.value,
            "org_label": recipient.org_label,
            "updated_at": recipient.updated_at,
        }
        statement = insert(RecipientRow).values(
            tenant_id=recipient.tenant_id.value,
            id=recipient.id.value,
            created_at=recipient.created_at,
            **values,
        )
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "id"],
                set_={name: statement.excluded[name] for name in values},
            )
        )
        keys = {"tenant_id": recipient.tenant_id.value, "recipient_id": recipient.id.value}
        for row in (RecipientAddressRow, RecipientBusinessRow):
            self._session.execute(
                delete(row).where(
                    row.tenant_id == keys["tenant_id"], row.recipient_id == keys["recipient_id"]
                )
            )
        if recipient.addresses:
            self._session.execute(
                insert(RecipientAddressRow),
                [
                    {
                        **keys,
                        "channel": address.channel.value,
                        "address": address.address,
                        "position": address.position,
                    }
                    for address in recipient.addresses
                ],
            )
        if recipient.businesses:
            self._session.execute(
                insert(RecipientBusinessRow),
                [
                    {**keys, "business_id": link.business_id.value, "label": link.label}
                    for link in recipient.businesses
                ],
            )
        self._session.expire_all()

    def delete(self, recipient_id: RecipientId) -> bool:
        result = self._session.execute(
            delete(RecipientRow)
            .where(RecipientRow.tenant_id == self._tenant, RecipientRow.id == recipient_id.value)
            .returning(RecipientRow.id)
        )
        self._session.expire_all()
        return result.first() is not None

    def for_business(self, business_id: BusinessId) -> Sequence[Recipient]:
        followers = select(RecipientBusinessRow.recipient_id).where(
            RecipientBusinessRow.tenant_id == self._tenant,
            RecipientBusinessRow.business_id == business_id.value,
        )
        return self._load(
            select(RecipientRow).where(
                RecipientRow.tenant_id == self._tenant, RecipientRow.id.in_(followers)
            )
        )

    def _load(self, statement: Any) -> list[Recipient]:
        """The recipients ``statement`` selects, by id, with their addresses and links."""
        rows = self._session.scalars(statement.order_by(RecipientRow.id)).all()
        if not rows:
            return []
        ids = [row.id for row in rows]
        addresses: dict[UUID, list[RecipientAddress]] = {}
        for address in self._session.scalars(
            select(RecipientAddressRow)
            .where(
                RecipientAddressRow.tenant_id == self._tenant,
                RecipientAddressRow.recipient_id.in_(ids),
            )
            .order_by(RecipientAddressRow.position)
        ):
            addresses.setdefault(address.recipient_id, []).append(
                RecipientAddress(Channel(address.channel), address.address, address.position)
            )
        links: dict[UUID, list[BusinessLink]] = {}
        for link in self._session.scalars(
            select(RecipientBusinessRow).where(
                RecipientBusinessRow.tenant_id == self._tenant,
                RecipientBusinessRow.recipient_id.in_(ids),
            )
        ):
            links.setdefault(link.recipient_id, []).append(
                BusinessLink(BusinessId(link.business_id), link.label)
            )
        return [
            Recipient(
                id=RecipientId(row.id),
                tenant_id=TenantId(row.tenant_id),
                user_id=None if row.user_id is None else UserId(row.user_id),
                role=RecipientRole(row.role),
                language=row.language,
                digest_mode=DigestMode(row.digest_mode),
                org_label=row.org_label,
                addresses=tuple(addresses.get(row.id, ())),
                businesses=tuple(links.get(row.id, ())),
                created_at=row.created_at.astimezone(UTC),
                updated_at=row.updated_at.astimezone(UTC),
            )
            for row in rows
        ]


class SqlAlchemyAddressDirectory:
    """``address_directory`` has no row-level security; every statement names the tenant."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(
        self, tenant_id: TenantId, recipient_id: RecipientId, addresses: Sequence[RecipientAddress]
    ) -> None:
        self.remove(tenant_id, recipient_id)
        if addresses:
            self._session.execute(
                insert(AddressDirectoryRow).on_conflict_do_nothing(),
                [
                    {
                        "channel": address.channel.value,
                        "address": address.address,
                        "tenant_id": tenant_id.value,
                        "recipient_id": recipient_id.value,
                    }
                    for address in addresses
                ],
            )

    def remove(self, tenant_id: TenantId, recipient_id: RecipientId) -> None:
        self._session.execute(
            delete(AddressDirectoryRow).where(
                AddressDirectoryRow.tenant_id == tenant_id.value,
                AddressDirectoryRow.recipient_id == recipient_id.value,
            )
        )

    def lookup(self, channel: Channel, address: str) -> Sequence[DirectoryEntry]:
        rows = self._session.execute(
            select(AddressDirectoryRow.tenant_id, AddressDirectoryRow.recipient_id)
            .where(
                AddressDirectoryRow.channel == channel.value,
                AddressDirectoryRow.address == address,
            )
            .order_by(AddressDirectoryRow.tenant_id, AddressDirectoryRow.recipient_id)
        ).all()
        return [
            DirectoryEntry(TenantId(row.tenant_id), RecipientId(row.recipient_id)) for row in rows
        ]


class SqlAlchemyNotificationRepository:
    """Row-level security scopes every statement to the unit's tenant."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_if_absent(self, notification: Notification) -> bool:
        statement = (
            insert(NotificationRow)
            .values(**_notification_values(notification))
            .on_conflict_do_nothing()
            .returning(NotificationRow.id)
        )
        return self._session.execute(statement).first() is not None

    def get(self, notification_id: NotificationId) -> Notification | None:
        return self._one(select(NotificationRow).where(NotificationRow.id == notification_id.value))

    def by_dedupe_key(self, dedupe_key: DedupeKey) -> Notification | None:
        return self._one(
            select(NotificationRow).where(NotificationRow.dedupe_key == dedupe_key.value)
        )

    def save(self, notification: Notification) -> None:
        values = _notification_values(notification)
        values.pop("id")
        self._session.execute(
            update(NotificationRow)
            .where(NotificationRow.id == notification.id.value)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()

    def due_for(
        self, recipient_id: RecipientId, channel: Channel, now: datetime
    ) -> Sequence[Notification]:
        return self._many(
            select(NotificationRow)
            .where(
                NotificationRow.recipient_id == recipient_id.value,
                NotificationRow.channel == channel.value,
                NotificationRow.state.in_(_PENDING),
                NotificationRow.available_at <= now,
            )
            .order_by(NotificationRow.available_at, NotificationRow.created_at, NotificationRow.id)
        )

    def by_dispatch(self, dispatch_id: DispatchId) -> Sequence[Notification]:
        return self._many(
            select(NotificationRow)
            .where(NotificationRow.dispatch_id == dispatch_id.value)
            .order_by(NotificationRow.created_at, NotificationRow.id)
        )

    def by_provider_message(self, provider_message_id: str) -> Sequence[Notification]:
        if not provider_message_id:
            return []
        return self._many(
            select(NotificationRow)
            .where(NotificationRow.provider_message_id == provider_message_id)
            .order_by(NotificationRow.created_at, NotificationRow.id)
        )

    def latest_params(self, obligation_id: ObligationId) -> Mapping[str, object] | None:
        params: dict[str, Any] | None = self._session.scalar(
            select(NotificationRow.params)
            .where(
                NotificationRow.obligation_id == obligation_id.value,
                NotificationRow.params != text("'{}'::jsonb"),
            )
            .order_by(NotificationRow.created_at.desc(), NotificationRow.id.desc())
            .limit(1)
        )
        return params

    def page(
        self,
        business_id: BusinessId,
        *,
        state: DeliveryState | None = None,
        limit: int,
        after: PageAfter | None = None,
    ) -> Sequence[Notification]:
        statement = (
            select(NotificationRow)
            .where(NotificationRow.business_id == business_id.value)
            .order_by(NotificationRow.created_at.desc(), NotificationRow.id.desc())
            .limit(limit)
        )
        if state is not None:
            statement = statement.where(NotificationRow.state == state.value)
        if after is not None:
            statement = statement.where(
                (NotificationRow.created_at < after.created_at)
                | (
                    (NotificationRow.created_at == after.created_at)
                    & (NotificationRow.id < after.notification_id.value)
                )
            )
        return self._many(statement)

    def purge(self, before: datetime) -> int:
        result = self._session.execute(
            delete(NotificationRow)
            .where(NotificationRow.created_at < before)
            .returning(NotificationRow.id)
        )
        self._session.expire_all()
        return len(result.all())

    def strip_params(self, before: datetime) -> int:
        result = self._session.execute(
            update(NotificationRow)
            .where(
                NotificationRow.created_at < before,
                NotificationRow.params != text("'{}'::jsonb"),
                NotificationRow.state.not_in(_PENDING),
            )
            .values(params={})
            .returning(NotificationRow.id)
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        return len(result.all())

    def _one(self, statement: Any) -> Notification | None:
        row = self._session.scalars(statement).first()
        return None if row is None else _to_notification(row)

    def _many(self, statement: Any) -> list[Notification]:
        return [_to_notification(row) for row in self._session.scalars(statement).all()]


class SqlAlchemyWorkQueue:
    """The unit's writes to the work index, in its transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: WorkEntry) -> None:
        self._session.execute(
            insert(WorkIndexRow).values(
                id=entry.id.value,
                tenant_id=entry.tenant_id.value,
                kind=entry.kind.value,
                status="pending",
                available_at=entry.available_at,
                lease_until=entry.lease_until,
                created_at=func.now(),
                updated_at=func.now(),
            )
        )

    def complete(self, notification_id: NotificationId, *, provider_message_id: str = "") -> None:
        self._session.execute(
            update(WorkIndexRow)
            .where(WorkIndexRow.id == notification_id.value)
            .values(
                status="done",
                lease_until=None,
                provider_message_id=provider_message_id,
                updated_at=func.now(),
            )
            .execution_options(synchronize_session=False)
        )

    def reschedule(self, notification_id: NotificationId, available_at: datetime) -> None:
        self._session.execute(
            update(WorkIndexRow)
            .where(WorkIndexRow.id == notification_id.value)
            .values(
                status="pending", available_at=available_at, lease_until=None, updated_at=func.now()
            )
            .execution_options(synchronize_session=False)
        )


class OutboxSink:
    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DomainEvent) -> None:
        self._writer.write(self._connection, event)


class SqlAlchemySharedUnitOfWork:
    """Consents, suppressions and the address directory, in a transaction without a tenant."""

    def __init__(self, session: Session) -> None:
        self.preferences = SqlAlchemyPreferenceRepository(session)
        self.suppressions = SqlAlchemySuppressionRepository(session)
        self.directory = SqlAlchemyAddressDirectory(session)


class SqlAlchemyUnitOfWork:
    """One transaction of one tenant."""

    def __init__(self, session: Session, tenant_id: TenantId, writer: OutboxWriter) -> None:
        connection = session.connection()
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
        self.tenant_id = tenant_id
        self.preferences = SqlAlchemyPreferenceRepository(session)
        self.suppressions = SqlAlchemySuppressionRepository(session)
        self.directory = SqlAlchemyAddressDirectory(session)
        self.recipients = SqlAlchemyRecipientRepository(session, tenant_id)
        self.notifications = SqlAlchemyNotificationRepository(session)
        self.work = SqlAlchemyWorkQueue(session)
        self.events = OutboxSink(connection, writer)

    @classmethod
    @contextmanager
    def on_connection(
        cls, connection: Connection, tenant_id: TenantId, *, writer: OutboxWriter | None = None
    ) -> Iterator[UnitOfWork]:
        """A unit of the tenant inside the transaction ``connection`` has begun, such as a
        consumer's inbox transaction. It neither commits nor rolls back: the owner of the
        transaction does. The tenant setting holds until that transaction ends."""
        if not connection.in_transaction():
            raise ValueError("on_connection needs a connection inside a transaction")
        with Session(bind=connection, expire_on_commit=False) as session:
            yield cls(session, tenant_id, writer or OutboxWriter())
            session.flush()


class PostgresUnitOfWorkFactory:
    """``factory(tenant_id)`` opens a transaction with ``app.tenant_id`` set for its duration;
    ``factory.shared()`` one without a tenant."""

    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def work_index(self) -> PostgresWorkIndex:
        return PostgresWorkIndex(self._engine)

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    def shared(self) -> AbstractContextManager[SharedUnitOfWork]:
        return self._open_shared()

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, tenant_id, self._writer)

    @contextmanager
    def _open_shared(self) -> Iterator[SharedUnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemySharedUnitOfWork(session)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def _notification_values(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id.value,
        "tenant_id": notification.tenant_id.value,
        "business_id": notification.business_id.value,
        "obligation_id": notification.obligation_id.value,
        "recipient_id": None
        if notification.recipient_id is None
        else notification.recipient_id.value,
        "channel": notification.channel.value,
        "address": notification.address,
        "occasion": notification.occasion.value,
        "template_key": notification.template_key,
        "language": notification.language,
        "params": _plain(notification.params),
        "dedupe_key": notification.dedupe_key.value,
        "state": notification.state.value,
        "attempts": notification.attempts,
        "available_at": notification.available_at,
        "dispatch_id": None if notification.dispatch_id is None else notification.dispatch_id.value,
        "provider_message_id": notification.provider_message_id,
        "error": notification.error,
        "fallback_of": None if notification.fallback_of is None else notification.fallback_of.value,
        "created_at": notification.created_at,
        "updated_at": notification.updated_at,
        "sent_at": notification.sent_at,
        "delivered_at": notification.delivered_at,
        "read_at": notification.read_at,
        "failed_at": notification.failed_at,
    }


def _plain(value: object) -> Any:
    """The JSON form of template values: read-only mappings and tuples become dicts and lists."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _utc(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.astimezone(UTC)


def _to_notification(row: NotificationRow) -> Notification:
    return Notification(
        id=NotificationId(row.id),
        tenant_id=TenantId(row.tenant_id),
        business_id=BusinessId(row.business_id),
        obligation_id=ObligationId(row.obligation_id),
        recipient_id=None if row.recipient_id is None else RecipientId(row.recipient_id),
        channel=Channel(row.channel),
        address=row.address,
        occasion=OccasionKind(row.occasion),
        template_key=row.template_key,
        language=row.language,
        params=row.params,
        dedupe_key=DedupeKey(row.dedupe_key),
        state=DeliveryState(row.state),
        available_at=row.available_at.astimezone(UTC),
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
        attempts=row.attempts,
        dispatch_id=None if row.dispatch_id is None else DispatchId(row.dispatch_id),
        provider_message_id=row.provider_message_id,
        error=row.error,
        sent_at=_utc(row.sent_at),
        delivered_at=_utc(row.delivered_at),
        read_at=_utc(row.read_at),
        failed_at=_utc(row.failed_at),
        fallback_of=None if row.fallback_of is None else NotificationId(row.fallback_of),
    )
