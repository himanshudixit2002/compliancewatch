"""A tenant's data requests: make one, list them, read one, and download the export.

Who may (the routes admit the rest of the callers they name):

- the tenant's owner or CA admin, for their own tenant (``self_service``); the session of a
  verified token is checked against the store, as on the user routes;
- the regulatory team's admin, for a tenant they name (``support``, with a reason): they make
  the request, and the tenant's owner downloads the export;
- in header mode the anonymous caller, for the tenant the header names.

``RequestExport`` records an export request with its 30-day deadline and a
``data_request.created`` audit entry. ``RequestDeletion`` records a deletion request the same
way, and in the same transaction turns the tenant ``deletion_requested`` (nobody signs in to it
any more, and it asks for nothing else) and writes ``tenant.deletion.requested`` to the outbox;
the services' erasure consumers answer it (``identity.application.erasure``). The internal tenant
is never erased (``TenantNotErasableError``, 422), and a tenant already being deleted asks
nothing more (``TenantDeletingError``, 403). The tenant's owner may still list and read its
requests while the erasure runs, with the token it holds.

``ExportTenantData`` assembles the export on download, and never stores it: identity's own data
of the tenant (the tenant, its users, its consent records, its billing ledger and its data
requests, each read ``EXPORT_PAGE_SIZE`` rows at a time), then each ``ExportSource``'s, one
section per service, each with when it was generated. The sources are asked ``concurrency`` at a
time and all within ``deadline_seconds`` (the settings' ``identity_export_concurrency`` and
``identity_export_deadline_seconds``); one still answering at the deadline counts as failed. No
transaction stays open while the sources answer. The request then records the services that
answered, holding its row (``lock``) so two downloads at once each add theirs: it completes once
every one of them has, and a source that failed stays pending, which the bundle says too. Each
download writes a ``data_request.exported`` audit entry naming the services that answered and
those still pending. ``ExportBundle.chunks`` writes the bundle a section at a time, so the
response is never one more copy of the whole export.

Secrets and tokens never reach the bundle: no session versions, no service clients, no
idempotency keys of the billing starts, no checkout links, no digests of webhook bodies and no
id of the platform's own payment account. A support request shows ``support`` as who asked in
the bundle, which is a copy of the tenant's data. The audit trail (``GET /v1/identity/audit``)
names the regulatory admin who recorded it, as it names every actor: it is the record of who
acted on the tenant's data, which the tenant may read. The personal data the tenant holds stays
as it is, since the export is the tenant's own data.
"""

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from domain_kernel.access import Principal, PrincipalKind, Role
from domain_kernel.audit import AuditEntry
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.application.audit import audit_entry
from identity.application.sessions import check_session
from identity.domain.billing import StoredBillingEvent, Subscription
from identity.domain.consent import ConsentRecord
from identity.domain.data_requests import (
    IDENTITY_SERVICE,
    DataRequest,
    DataRequestId,
    DataRequestKind,
    DataRequestSource,
    ExportSource,
    SourceSection,
)
from identity.domain.errors import (
    DataRequestNotFoundError,
    ExportNotReadyError,
    TenantDeletingError,
    TenantInactiveError,
    TenantNotErasableError,
    TenantNotFoundError,
)
from identity.domain.events import TenantDeletionRequested
from identity.domain.pages import EXPORT_PAGE_SIZE, ExportAfter
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import Tenant, TenantKind, User
from py_common.auth.errors import AuthForbiddenError

REQUESTER_ROLES: Final = frozenset({Role.OWNER, Role.CA_ADMIN})
"""Roles that make and read their tenant's data requests."""
SUBJECT_TYPE: Final = "data_request"
CREATED: Final = "data_request.created"
EXPORTED: Final = "data_request.exported"
BUNDLE_FORMAT: Final = "compliancewatch.tenant-export"
BUNDLE_VERSION: Final = 1
DEFAULT_CONCURRENCY: Final = 4
"""How many services an export asks at once."""
DEFAULT_DEADLINE_SECONDS: Final = 45.0
"""How long an export waits for all the services together."""
PLATFORM_FIELDS: Final = frozenset({"account_id"})
"""Fields of a stored webhook that name the platform's own payment account, not the tenant's
data, and stay out of the bundle."""


def requester_context(
    uow: UnitOfWork, tenant_id: TenantId, actor: Principal, *, deleting_ok: bool = False
) -> Tenant:
    """The tenant, after checking the actor may handle its data requests: the anonymous caller
    of header mode, or an active owner or CA admin of the tenant whose session is current.
    ``deleting_ok`` admits a tenant that asked for its deletion (to read its requests)."""
    tenant = uow.tenants.get(tenant_id)
    if tenant is None:
        raise TenantNotFoundError()
    if not actor.is_authenticated:
        return tenant
    if actor.kind is not PrincipalKind.USER:
        raise AuthForbiddenError("data requests answer for a person, not a service")
    _, user = check_session(uow, actor, deleting_ok=deleting_ok)
    if not user.roles & REQUESTER_ROLES:
        raise AuthForbiddenError("data requests are made by the tenant's owner or CA admin")
    return tenant


def support_context(uow: UnitOfWork, actor: Principal) -> User:
    """The regulatory team's admin making a support request: an active admin of the internal
    tenant whose session is current."""
    if actor.kind is not PrincipalKind.USER or actor.tenant_id is None:
        raise AuthForbiddenError("a support request is made by the regulatory team's admin")
    tenant, user = check_session(uow, actor)
    if tenant.kind is not TenantKind.INTERNAL or Role.ADMIN not in user.roles:
        raise AuthForbiddenError("a support request is made by the regulatory team's admin")
    return user


def _created_entry(request: DataRequest, actor: Principal) -> AuditEntry:
    return audit_entry(
        CREATED,
        tenant_id=request.tenant_id,
        subject_type=SUBJECT_TYPE,
        subject_id=str(request.id),
        at=request.requested_at,
        after={
            "kind": request.kind.value,
            "source": request.source.value,
            "deadline_at": request.deadline_at.isoformat(),
        },
        reason=request.reason,
        principal=actor,
    )


def _require_active(tenant: Tenant) -> None:
    """A tenant asks for nothing once it asked for its deletion, or was erased."""
    if tenant.is_deleting:
        raise TenantDeletingError()
    if not tenant.is_active:
        raise TenantInactiveError()


class _MakeRequest:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def _new(
        self,
        actor: Principal,
        tenant_id: TenantId,
        kind: DataRequestKind,
        *,
        reason: str,
        for_tenant: TenantId | None,
    ) -> DataRequest:
        """A request of the request's tenant, or with ``for_tenant`` a support request for that
        tenant by the regulatory team's admin (``tenant_id`` is then the admin's own)."""
        source = DataRequestSource.SELF_SERVICE
        target = tenant_id
        if for_tenant is not None and for_tenant != tenant_id:
            with self._unit_of_work(tenant_id) as uow:
                support_context(uow, actor)
            source = DataRequestSource.SUPPORT
            target = for_tenant
        return DataRequest.new(
            target,
            kind,
            source,
            requested_by=actor.actor_label if actor.is_authenticated else "",
            reason=reason,
            at=self._clock(),
        )

    @staticmethod
    def _tenant(uow: UnitOfWork, request: DataRequest, actor: Principal) -> Tenant:
        """The request's tenant, after checking who asks for it."""
        if request.source is DataRequestSource.SUPPORT:
            tenant = uow.tenants.lock(request.tenant_id)
            if tenant is None:
                raise TenantNotFoundError()
            return tenant
        requester_context(uow, request.tenant_id, actor)
        tenant = uow.tenants.lock(request.tenant_id)
        if tenant is None:  # pragma: no cover - requester_context found it
            raise TenantNotFoundError()
        return tenant


class RequestExport(_MakeRequest):
    def run(
        self,
        actor: Principal,
        tenant_id: TenantId,
        *,
        reason: str = "",
        for_tenant: TenantId | None = None,
    ) -> DataRequest:
        """An export request, offered at once."""
        request = self._new(
            actor, tenant_id, DataRequestKind.EXPORT, reason=reason, for_tenant=for_tenant
        )
        with self._unit_of_work(request.tenant_id) as uow:
            _require_active(self._tenant(uow, request, actor))
            uow.data_requests.add(request)
            uow.audit.write(_created_entry(request, actor))
        return request


class RequestDeletion(_MakeRequest):
    def run(
        self,
        actor: Principal,
        tenant_id: TenantId,
        *,
        reason: str = "",
        for_tenant: TenantId | None = None,
    ) -> DataRequest:
        """A deletion request: the tenant turns ``deletion_requested`` and the services are
        asked to erase it (``tenant.deletion.requested``), all in one transaction."""
        request = self._new(
            actor, tenant_id, DataRequestKind.DELETION, reason=reason, for_tenant=for_tenant
        )
        with self._unit_of_work(request.tenant_id) as uow:
            tenant = self._tenant(uow, request, actor)
            if tenant.kind is TenantKind.INTERNAL:
                raise TenantNotErasableError()
            _require_active(tenant)
            uow.tenants.save(tenant.deletion_requested())
            uow.data_requests.add(request)
            uow.events.publish(deletion_event(request, actor))
            uow.audit.write(_created_entry(request, actor))
        return request


def deletion_event(request: DataRequest, actor: Principal | None) -> TenantDeletionRequested:
    """The ``tenant.deletion.requested`` a deletion request sends: who asked, a user of the
    tenant, or None for a support request or an unnamed caller."""
    asked_by = None
    if (
        actor is not None
        and request.source is DataRequestSource.SELF_SERVICE
        and actor.kind is PrincipalKind.USER
    ):
        asked_by = actor.user_id
    return TenantDeletionRequested(
        tenant_id=request.tenant_id,
        requested_by=asked_by,
        requested_at=request.requested_at,
        deadline_at=request.deadline_at,
        reason=request.reason,
    )


class ListDataRequests:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, actor: Principal, tenant_id: TenantId) -> list[DataRequest]:
        """The tenant's requests, newest first."""
        with self._unit_of_work(tenant_id) as uow:
            requester_context(uow, tenant_id, actor, deleting_ok=True)
            return uow.data_requests.list()


class ReadDataRequest:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, actor: Principal, tenant_id: TenantId, request_id: DataRequestId) -> DataRequest:
        with self._unit_of_work(tenant_id) as uow:
            requester_context(uow, tenant_id, actor, deleting_ok=True)
            request = uow.data_requests.get(request_id)
        if request is None:
            raise DataRequestNotFoundError()
        return request


@dataclass(frozen=True, slots=True)
class ExportBundle:
    """One download: the request as it stands after it, and the sections."""

    request: DataRequest
    generated_at: datetime
    sections: tuple[SourceSection, ...]
    pending: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        """The bundle as JSON: one entry per service, each with its ``generated_at``, or with
        ``status: unavailable`` and why when the service did not answer."""
        return {
            **self._head(),
            "services": {section.service: _entry(section) for section in self.sections},
        }

    def chunks(self) -> Iterator[bytes]:
        """``document`` as JSON text, written a service at a time."""
        head = json.dumps(self._head())
        yield (head[:-1] + ', "services": {').encode()
        for index, section in enumerate(self.sections):
            separator = ", " if index else ""
            name = json.dumps(section.service)
            yield f"{separator}{name}: {json.dumps(_entry(section))}".encode()
        yield b"}}"

    def _head(self) -> dict[str, Any]:
        return {
            "format": BUNDLE_FORMAT,
            "format_version": BUNDLE_VERSION,
            "tenant_id": str(self.request.tenant_id),
            "request_id": str(self.request.id),
            "generated_at": self.generated_at.isoformat(),
            "complete": not self.pending,
            "services_pending": list(self.pending),
        }


def _entry(section: SourceSection) -> dict[str, Any]:
    if section.data is not None:
        return dict(section.data)
    return {"service": section.service, "status": "unavailable", "error": section.error}


class ExportTenantData:
    """``page_size`` is how many rows each read of identity's own data takes (tests make it
    small to cross pages)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        sources: Sequence[ExportSource] = (),
        *,
        clock: Callable[[], datetime] = utc_now,
        concurrency: int = DEFAULT_CONCURRENCY,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        page_size: int = EXPORT_PAGE_SIZE,
    ) -> None:
        if concurrency < 1 or deadline_seconds <= 0 or page_size < 1:
            raise ValueError("an export asks at least one service at a time, with a deadline")
        self._unit_of_work = unit_of_work
        self._sources = tuple(sources)
        self._clock = clock
        self._concurrency = concurrency
        self._deadline_seconds = deadline_seconds
        self._page_size = page_size

    @property
    def services(self) -> tuple[str, ...]:
        """Every service an export needs: identity and each source."""
        return (IDENTITY_SERVICE, *sorted(source.service for source in self._sources))

    def run(self, actor: Principal, tenant_id: TenantId, request_id: DataRequestId) -> ExportBundle:
        with self._unit_of_work(tenant_id) as uow:
            tenant = requester_context(uow, tenant_id, actor)
            request = uow.data_requests.get(request_id)
            if request is None:
                raise DataRequestNotFoundError()
            if request.kind is not DataRequestKind.EXPORT:
                raise ExportNotReadyError(request.kind.value)
            own = SourceSection(
                IDENTITY_SERVICE,
                identity_section(uow, tenant, self._clock(), page_size=self._page_size),
            )
        answers = [own, *self._ask(tenant_id)]
        answered = [section.service for section in answers if section.answered]
        at = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            current = uow.data_requests.lock(request_id)
            if current is None:  # pragma: no cover - requests are never deleted
                raise DataRequestNotFoundError()
            updated = current.record_answers(answered, self.services, at)
            if updated != current:
                uow.data_requests.save(updated)
            pending = updated.pending(self.services)
            failed = sorted(section.service for section in answers if not section.answered)
            uow.audit.write(
                audit_entry(
                    EXPORTED,
                    tenant_id=tenant_id,
                    subject_type=SUBJECT_TYPE,
                    subject_id=str(request_id),
                    at=at,
                    before={"status": current.status.value},
                    after={
                        "status": updated.status.value,
                        "services_answered": sorted(answered),
                        "services_failed": failed,
                        "services_pending": list(pending),
                    },
                    principal=actor,
                )
            )
        return ExportBundle(
            request=updated,
            generated_at=at,
            sections=tuple(answers),
            pending=tuple(sorted({*pending, *failed})),
        )

    def _ask(self, tenant_id: TenantId) -> list[SourceSection]:
        """Every source's section, ``concurrency`` at a time, within the deadline; a source that
        has not answered by then is a section without data. Its thread runs on until the
        source's own timeout, and its answer is dropped."""
        if not self._sources:
            return []
        pool = ThreadPoolExecutor(
            max_workers=min(self._concurrency, len(self._sources)),
            thread_name_prefix="identity-export",
        )
        try:
            asked = [
                (source.service, pool.submit(source.export, tenant_id)) for source in self._sources
            ]
            wait([future for _, future in asked], timeout=self._deadline_seconds)
            return [self._section(service, future) for service, future in asked]
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _section(self, service: str, future: Future[SourceSection]) -> SourceSection:
        if not future.done():
            future.cancel()
            return SourceSection(
                service, None, f"no answer within the export's {self._deadline_seconds:g} s"
            )
        try:
            return future.result()
        except Exception as exc:  # a source answers its failures; this is a bug, kept out
            return SourceSection(service, None, f"not asked ({type(exc).__name__})")


def _pages[T](
    read: Callable[[ExportAfter | None, int], Sequence[T]],
    cursor: Callable[[T], ExportAfter],
    size: int,
) -> Iterator[T]:
    """Every row ``read`` gives, a page of ``size`` at a time, each after the last."""
    after: ExportAfter | None = None
    while True:
        page = read(after, size)
        yield from page
        if len(page) < size:
            return
        after = cursor(page[-1])


def identity_section(
    uow: UnitOfWork, tenant: Tenant, at: datetime, *, page_size: int = EXPORT_PAGE_SIZE
) -> dict[str, Any]:
    """Identity's own data of the tenant, as JSON: users, consents, billing events and data
    requests a page at a time, oldest first; the billing customer (one) and subscriptions (one
    per plan the tenant ever started) as they are."""
    customer = uow.billing.customer()
    users = _pages(
        uow.users.page, lambda user: ExportAfter(user.created_at, user.id.value), page_size
    )
    consents = _pages(
        uow.consents.page,
        lambda record: ExportAfter(record.recorded_at, record.id.value),
        page_size,
    )
    events = _pages(
        uow.billing.events_page, lambda event: ExportAfter(event.received_at, event.id), page_size
    )
    requests = _pages(
        uow.data_requests.page,
        lambda request: ExportAfter(request.requested_at, request.id.value),
        page_size,
    )
    return {
        "service": IDENTITY_SERVICE,
        "tenant_id": str(tenant.id),
        "generated_at": at.isoformat(),
        "sections": {
            "tenant": [_tenant(tenant)],
            "users": [_user(user) for user in users],
            "consents": [_consent(record) for record in consents],
            "billing_customer": []
            if customer is None
            else [
                {
                    "provider_customer_id": customer.provider_customer_id,
                    "email": customer.email,
                    "name": customer.name,
                }
            ],
            "billing_subscriptions": [
                _subscription(subscription)
                for subscription in reversed(uow.billing.subscriptions())
            ],
            "billing_events": [_billing_event(event) for event in events],
            "data_requests": [_data_request(request) for request in requests],
        },
    }


def _when(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _tenant(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "kind": tenant.kind.value,
        "name": tenant.name,
        "region": tenant.region,
        "status": tenant.status.value,
        "created_at": tenant.created_at.isoformat(),
    }


def _user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.contact.email,
        "phone": user.contact.phone,
        "display_name": user.display_name,
        "roles": sorted(role.value for role in user.roles),
        "status": user.status.value,
        "provider": user.provider,
        "provider_subject": user.provider_subject,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def _consent(record: ConsentRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "subject": record.subject,
        "purpose": record.purpose.value,
        "granted": record.granted,
        "source": record.source.value,
        "notice_version": record.notice_version,
        "evidence": record.evidence,
        "recorded_by": None if record.recorded_by is None else str(record.recorded_by),
        "recorded_at": record.recorded_at.isoformat(),
    }


def _subscription(subscription: Subscription) -> dict[str, Any]:
    return {
        "provider_subscription_id": subscription.provider_subscription_id,
        "plan_key": subscription.plan_key,
        "quantity": subscription.quantity,
        "status": subscription.status.value,
        "started_at": subscription.started_at.isoformat(),
        "updated_at": _when(subscription.updated_at),
        "last_event_at": _when(subscription.last_event_at),
        "past_due_since": _when(subscription.past_due_since),
    }


def _billing_event(event: StoredBillingEvent) -> dict[str, Any]:
    payload: Mapping[str, object] = event.raw_event
    return {
        "id": str(event.id),
        "provider_subscription_id": event.provider_subscription_id,
        "kind": event.kind,
        "status": None if event.status is None else event.status.value,
        "occurred_at": event.occurred_at.isoformat(),
        "received_at": event.received_at.isoformat(),
        "payload": {key: value for key, value in payload.items() if key not in PLATFORM_FIELDS},
    }


def _data_request(request: DataRequest) -> dict[str, Any]:
    support = request.source is DataRequestSource.SUPPORT
    return {
        "id": str(request.id),
        "kind": request.kind.value,
        "source": request.source.value,
        "requested_by": "support" if support else request.requested_by,
        "reason": request.reason,
        "requested_at": request.requested_at.isoformat(),
        "deadline_at": request.deadline_at.isoformat(),
        "status": request.status.value,
        "services_done": list(request.services_done),
        "completed_at": _when(request.completed_at),
    }
