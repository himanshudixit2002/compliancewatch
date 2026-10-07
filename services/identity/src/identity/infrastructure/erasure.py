"""Identity's ``IdentityEraser`` on the consumer's Postgres connection, and its memory twin.

``PostgresIdentityEraser.erase`` runs in the transaction of the ``identity.erasure`` consumer,
with ``app.tenant_id`` and ``app.erasure`` set (``py_common.erasure.begin_erasure``): row-level
security admits the tenant's rows only, and the consent records' trigger lets the
pseudonymisation through. It deletes ``user_subject`` (no row-level security: the rows of this
tenant, by ``tenant_id``), ``app_user`` and ``idempotency_key``, pseudonymises ``consent_record``
and ``billing_customer`` with the erasure pepper (``pseudonym``), empties the checkout links of
``billing_subscription`` and ``billing_start``, prunes the tenant's published events from
``outbox_event``, marks the tenant erased and writes its erased marker (``erased_tenant``, with
the answer). Run again (a redelivery, a resend, the second pass) it counts only what it changed.
Everything else of the tenant stays, each with its reason in ``RETAINED``. ``channel_consent``
belongs to no tenant (consents typed on a channel, keyed by the number) and ``service_client``
neither; ``audit.event`` is never erased.

``MemoryIdentityEraser`` does the same to a ``MemoryStore`` (tests and the in-process journey).
"""

from dataclasses import replace
from typing import Final

from sqlalchemy import Connection, or_, select, update

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import Erased, TenantDataErased, retained
from domain_kernel.ids import TenantId
from identity.domain.erasure import PSEUDONYM_PREFIX, pseudonym
from identity.domain.tenancy import TenantStatus
from identity.infrastructure.memory import MemoryStore
from identity.infrastructure.models import (
    BillingCustomerRow,
    BillingStartRow,
    BillingSubscriptionRow,
    ConsentRow,
    TenantRow,
)
from py_common.audit import MemoryAuditSink
from py_common.audit.writer import AuditWriter
from py_common.erasure import (
    ERASED_RETAINED,
    OUTBOX_RETAINED,
    PostgresTenantEraser,
    begin_erasure,
    delete_rows,
    prune_outbox,
)
from py_common.idempotency import MemoryIdempotencyStore
from py_common.outbox import OutboxWriter

RETAINED: Final = (
    *retained(
        (
            "consent_record",
            "pseudonymised, not deleted: the record proves when consent was given or withdrawn "
            "and under which notice; whose it was is gone (subject hashed, evidence emptied)",
        ),
        (
            "billing_customer",
            "pseudonymised: the provider's customer id stays for the tax records (lawyer to "
            "confirm); email and name are gone",
        ),
        (
            "billing_subscription",
            "tax records: plan, quantity and dates of what the tenant paid for, no personal "
            "data; the checkout link is emptied",
        ),
        ("billing_event", "tax records: the provider's webhooks, masked when they arrived"),
        (
            "billing_start",
            "ids of the subscription starts, no personal data; the checkout link is emptied",
        ),
        (
            "data_request",
            "the record that the deletion was asked for and answered, with its deadline",
        ),
        ("tenant", "the erased tenant: id, kind and status, no name; it refuses every sign-in"),
    ),
    ERASED_RETAINED,
    OUTBOX_RETAINED,
)


class PostgresIdentityEraser(PostgresTenantEraser):
    """``pepper`` keys the pseudonyms (``CW_IDENTITY_ERASURE_PEPPER``)."""

    def __init__(
        self,
        connection: Connection,
        *,
        pepper: bytes,
        writer: OutboxWriter | None = None,
        audit: AuditWriter | None = None,
    ) -> None:
        super().__init__(connection, writer=writer, audit=audit)
        if not pepper:
            raise ValueError("identity's erasure needs the erasure pepper")
        self._pepper = pepper

    def erase(self, tenant_id: TenantId) -> Erased:
        connection = self.connection
        begin_erasure(connection, tenant_id)
        tables: dict[str, int] = {}
        tables["user_subject"] = delete_rows(connection, "user_subject", tenant_id)
        tables["app_user"] = delete_rows(connection, "app_user", tenant_id)
        tables["idempotency_key"] = delete_rows(connection, "idempotency_key", tenant_id)
        tables["consent_record"] = _pseudonymise_consents(connection, tenant_id, self._pepper)
        tables["billing_customer"] = _pseudonymise_customer(connection, tenant_id, self._pepper)
        tables["billing_subscription"] = _empty_checkout(
            connection, BillingSubscriptionRow, tenant_id
        )
        tables["billing_start"] = _empty_checkout(connection, BillingStartRow, tenant_id)
        tables["outbox_event"] = prune_outbox(connection, tenant_id)
        tables["tenant"] = _erase_tenant(connection, tenant_id)
        return Erased(tables, RETAINED)


def _pseudonymise_consents(connection: Connection, tenant_id: TenantId, pepper: bytes) -> int:
    rows = connection.execute(
        select(ConsentRow.id, ConsentRow.subject).where(
            ConsentRow.tenant_id == tenant_id.value,
            (~ConsentRow.subject.startswith(PSEUDONYM_PREFIX))
            | (ConsentRow.evidence != "")
            | ConsentRow.recorded_by.is_not(None),
        )
    ).all()
    for row in rows:
        connection.execute(
            update(ConsentRow)
            .where(ConsentRow.id == row.id, ConsentRow.tenant_id == tenant_id.value)
            .values(
                subject=pseudonym(tenant_id, row.subject, pepper), evidence="", recorded_by=None
            )
        )
    return len(rows)


def _pseudonymise_customer(connection: Connection, tenant_id: TenantId, pepper: bytes) -> int:
    row = connection.execute(
        select(BillingCustomerRow.email, BillingCustomerRow.name).where(
            BillingCustomerRow.tenant_id == tenant_id.value
        )
    ).one_or_none()
    if row is None or (row.email.startswith(PSEUDONYM_PREFIX) and row.name == ""):
        return 0
    connection.execute(
        update(BillingCustomerRow)
        .where(BillingCustomerRow.tenant_id == tenant_id.value)
        .values(email=pseudonym(tenant_id, row.email, pepper), name="")
    )
    return 1


def _empty_checkout(
    connection: Connection,
    row: type[BillingSubscriptionRow] | type[BillingStartRow],
    tenant_id: TenantId,
) -> int:
    result = connection.execute(
        update(row)
        .where(row.tenant_id == tenant_id.value, row.checkout_url != "")
        .values(checkout_url="")
    )
    return max(result.rowcount, 0)


def _erase_tenant(connection: Connection, tenant_id: TenantId) -> int:
    result = connection.execute(
        update(TenantRow)
        .where(
            TenantRow.id == tenant_id.value,
            or_(TenantRow.status != TenantStatus.ERASED.value, TenantRow.name != ""),
        )
        .values(status=TenantStatus.ERASED.value, name="")
    )
    return max(result.rowcount, 0)


class MemoryIdentityEraser:
    """``IdentityEraser`` on a memory store, under its lock."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        pepper: bytes,
        idempotency: MemoryIdempotencyStore | None = None,
    ) -> None:
        if not pepper:
            raise ValueError("identity's erasure needs the erasure pepper")
        self._store = store
        self._pepper = pepper
        self._idempotency = idempotency

    def erase(self, tenant_id: TenantId) -> Erased:
        store = self._store
        with store.lock:
            subjects = [
                key for key, entry in store.subjects.items() if entry.tenant_id == tenant_id
            ]
            for key in subjects:
                del store.subjects[key]
            users = [
                user_id for user_id, user in store.users.items() if user.tenant_id == tenant_id
            ]
            for user_id in users:
                del store.users[user_id]
            consents = 0
            for index, record in enumerate(store.records):
                if record.tenant_id != tenant_id:
                    continue
                erased = replace(
                    record,
                    subject=pseudonym(tenant_id, record.subject, self._pepper),
                    evidence="",
                    recorded_by=None,
                )
                if erased != record:
                    store.records[index] = erased
                    consents += 1
            customers = 0
            held = store.billing.customers.get(tenant_id)
            if held is not None:
                customer, provider, at = held
                hidden = replace(
                    customer, email=pseudonym(tenant_id, customer.email, self._pepper), name=""
                )
                if hidden != customer:
                    store.billing.customers[tenant_id] = (hidden, provider, at)
                    customers = 1
            subscriptions = 0
            for subscription_id, subscription in list(store.billing.subscriptions.items()):
                if subscription.tenant_id == tenant_id and subscription.checkout_url:
                    emptied = replace(subscription, checkout_url="")
                    store.billing.subscriptions[subscription_id] = emptied
                    subscriptions += 1
            starts = 0
            for start_key, start in list(store.billing.starts.items()):
                if start.tenant_id == tenant_id and start.checkout_url:
                    store.billing.starts[start_key] = replace(start, checkout_url="")
                    starts += 1
            tenants = 0
            tenant = store.tenants.get(tenant_id)
            if tenant is not None and tenant.erased() != tenant:
                store.tenants[tenant_id] = tenant.erased()
                tenants = 1
        return Erased(
            {
                "user_subject": len(subjects),
                "app_user": len(users),
                "idempotency_key": _forget(self._idempotency, tenant_id),
                "consent_record": consents,
                "billing_customer": customers,
                "billing_subscription": subscriptions,
                "billing_start": starts,
                "outbox_event": 0,
                "tenant": tenants,
            },
            RETAINED,
        )

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        store = self._store
        with store.lock:
            store.events.append(event)
            store.erased.mark(event)
            self._audit(entry)

    def write_audit(self, entry: AuditEntry) -> None:
        with self._store.lock:
            self._audit(entry)

    def _audit(self, entry: AuditEntry) -> None:
        sink = MemoryAuditSink(self._store.audit, tenant_id=entry.tenant_id)
        sink.write(entry)
        sink.commit()


def _forget(idempotency: MemoryIdempotencyStore | None, tenant_id: TenantId) -> int:
    """The tenant's idempotency keys dropped from the service's memory store of them, when the
    eraser was given it."""
    return 0 if idempotency is None else idempotency.forget(tenant_id)
