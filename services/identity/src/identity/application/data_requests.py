"""A tenant's data requests: make one, list them, read one, and download the export.

Who may (the routes admit the rest of the callers they name):

- the tenant's owner or CA admin, for their own tenant (``self_service``); the session of a
  verified token is checked against the store, as on the user routes;
- the regulatory team's admin, for a tenant they name (``support``, with a reason): they make
  the request, and the tenant's owner downloads the export;
- in header mode the anonymous caller, for the tenant the header names.

``RequestExport`` records an export request with its 30-day deadline and a
``data_request.created`` audit entry. Deletion requests are refused until the erasure cascade
exists (``DataRequestKindUnavailableError``, 422).

``ExportTenantData`` assembles the export on download, and never stores it: identity's own data
of the tenant (the tenant, its users, its consent records, its billing ledger and its data
requests), then each ``ExportSource``'s, one section per service, each with when it was
generated. No transaction stays open while the sources answer. The request then records the
services that answered: it completes once every one of them has, and a source that failed stays
pending, which the bundle says too. Each download writes a ``data_request.exported`` audit
entry naming the services that answered and those still pending.

Secrets and tokens never reach the bundle: no session versions, no service clients, no
idempotency keys of the billing starts, no checkout links and no digests of webhook bodies; a
support request shows ``support`` as who asked, never the internal admin's id. The personal data
the tenant holds stays as it is, since the export is the tenant's own data.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from domain_kernel.access import Principal, PrincipalKind, Role
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
    DataRequestKindUnavailableError,
    DataRequestNotFoundError,
    ExportNotReadyError,
    TenantNotFoundError,
)
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
AVAILABLE_KINDS: Final = frozenset({DataRequestKind.EXPORT})
"""The kinds the routes take; deletion waits for the erasure cascade."""


def requester_context(uow: UnitOfWork, tenant_id: TenantId, actor: Principal) -> Tenant:
    """The tenant, after checking the actor may handle its data requests: the anonymous caller
    of header mode, or an active owner or CA admin of the tenant whose session is current."""
    tenant = uow.tenants.get(tenant_id)
    if tenant is None:
        raise TenantNotFoundError()
    if not actor.is_authenticated:
        return tenant
    if actor.kind is not PrincipalKind.USER:
        raise AuthForbiddenError("data requests answer for a person, not a service")
    _, user = check_session(uow, actor)
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


class RequestExport:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        actor: Principal,
        tenant_id: TenantId,
        kind: DataRequestKind,
        *,
        reason: str = "",
        for_tenant: TenantId | None = None,
    ) -> DataRequest:
        """A request of the request's tenant, or with ``for_tenant`` a support request for that
        tenant by the regulatory team's admin (``tenant_id`` is then the admin's own)."""
        if kind not in AVAILABLE_KINDS:
            raise DataRequestKindUnavailableError(kind.value)
        source = DataRequestSource.SELF_SERVICE
        target = tenant_id
        if for_tenant is not None and for_tenant != tenant_id:
            with self._unit_of_work(tenant_id) as uow:
                support_context(uow, actor)
            source = DataRequestSource.SUPPORT
            target = for_tenant
        request = DataRequest.new(
            target,
            kind,
            source,
            requested_by=actor.actor_label if actor.is_authenticated else "",
            reason=reason,
            at=self._clock(),
        )
        with self._unit_of_work(target) as uow:
            if source is DataRequestSource.SUPPORT:
                if uow.tenants.get(target) is None:
                    raise TenantNotFoundError()
            else:
                requester_context(uow, target, actor)
            uow.data_requests.add(request)
            uow.audit.write(
                audit_entry(
                    CREATED,
                    tenant_id=target,
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
            )
        return request


class ListDataRequests:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, actor: Principal, tenant_id: TenantId) -> list[DataRequest]:
        """The tenant's requests, newest first."""
        with self._unit_of_work(tenant_id) as uow:
            requester_context(uow, tenant_id, actor)
            return uow.data_requests.list()


class ReadDataRequest:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, actor: Principal, tenant_id: TenantId, request_id: DataRequestId) -> DataRequest:
        with self._unit_of_work(tenant_id) as uow:
            requester_context(uow, tenant_id, actor)
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
        services: dict[str, Any] = {}
        for section in self.sections:
            if section.data is not None:
                services[section.service] = dict(section.data)
            else:
                services[section.service] = {
                    "service": section.service,
                    "status": "unavailable",
                    "error": section.error,
                }
        return {
            "format": BUNDLE_FORMAT,
            "format_version": BUNDLE_VERSION,
            "tenant_id": str(self.request.tenant_id),
            "request_id": str(self.request.id),
            "generated_at": self.generated_at.isoformat(),
            "complete": not self.pending,
            "services_pending": list(self.pending),
            "services": services,
        }


class ExportTenantData:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        sources: Sequence[ExportSource] = (),
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._sources = tuple(sources)
        self._clock = clock

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
            own = SourceSection(IDENTITY_SERVICE, identity_section(uow, tenant, self._clock()))
        answers = [own, *(source.export(tenant_id) for source in self._sources)]
        answered = [section.service for section in answers if section.answered]
        at = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            current = uow.data_requests.get(request_id)
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


def identity_section(uow: UnitOfWork, tenant: Tenant, at: datetime) -> dict[str, Any]:
    """Identity's own data of the tenant, as JSON."""
    customer = uow.billing.customer()
    return {
        "service": IDENTITY_SERVICE,
        "tenant_id": str(tenant.id),
        "generated_at": at.isoformat(),
        "sections": {
            "tenant": [_tenant(tenant)],
            "users": [_user(user) for user in uow.users.list()],
            "consents": [_consent(record) for record in uow.consents.all()],
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
            "billing_events": [_billing_event(event) for event in uow.billing.events()],
            "data_requests": [
                _data_request(request) for request in reversed(uow.data_requests.list())
            ],
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
        "payload": dict(payload),
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
