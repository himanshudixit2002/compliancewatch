"""Identity's part of a deletion request's erasure, the answers it records, and the resend.

- ``DeleteProviderAccounts`` is the first half of identity's erasure (``identity.erasure``): with
  no transaction open, it deletes the account of every user of the tenant at the identity
  provider. An account already gone counts as deleted, so a redelivered request deletes nothing
  twice; a provider that cannot be reached raises, and the consumer retries, then
  dead-letters. The second half, in the consumer's transaction, is the ``IdentityEraser``
  (``identity.domain.erasure``).
- ``RecordErasure`` is the consumer of ``tenant.data.erased`` (``identity.erasure-records``): it
  adds the service to the tenant's open deletion request with a ``data_request.erased`` audit
  entry, and once every expected service has answered, completes it with a
  ``data_request.completed`` entry. It records whatever the flag says: an answer means the
  service has erased, and the request must show it.
- ``ResendDeletion`` (``identity-admin erasure resend``) writes ``tenant.deletion.requested``
  again for the tenant's open deletion request: what an operator runs once the flag is on for a
  request made while it was off, or to retry after a dead letter. Every service's erasure is
  idempotent, so a service that had answered erases nothing more and answers again.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, TenantId
from identity.application.audit import audit_entry
from identity.application.data_requests import SUBJECT_TYPE, deletion_event
from identity.domain.data_requests import DataRequest
from identity.domain.errors import DeletionRequestNotFoundError
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import User

SERVICE: Final = "identity"
ERASED: Final = "data_request.erased"
COMPLETED: Final = "data_request.completed"
RESENT: Final = "data_request.resent"
ADMIN_ACTOR: Final = AuditActor.system("identity-admin")


@dataclass(frozen=True, slots=True)
class ProviderDeletions:
    """What the provider was asked: the accounts deleted and those of another provider, which
    this process cannot reach and the runbook has the operator delete by hand."""

    deleted: int
    other_provider: int


class DeleteProviderAccounts:
    def __init__(self, unit_of_work: UnitOfWorkFactory, provider: IdentityProvider) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider

    def users(self, tenant_id: TenantId) -> list[User]:
        with self._unit_of_work(tenant_id) as uow:
            return uow.users.list()

    def run(self, tenant_id: TenantId) -> ProviderDeletions:
        deleted = other = 0
        for user in self.users(tenant_id):
            if user.provider != self._provider.name:
                other += 1
                continue
            self._provider.delete(user.provider_subject)
            deleted += 1
        return ProviderDeletions(deleted, other)


@dataclass(frozen=True, slots=True)
class ErasureRecorded:
    """The deletion request after one service's answer; None when the tenant has no open one
    (an answer after completion, or a redelivery)."""

    request: DataRequest | None
    changed: bool

    @property
    def completed(self) -> bool:
        return self.request is not None and self.request.is_completed


class RecordErasure:
    def __init__(
        self, expected: tuple[str, ...], *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        if SERVICE not in expected:
            raise ValueError("a deletion request always waits for identity")
        self._expected = expected
        self._clock = clock

    @property
    def expected(self) -> tuple[str, ...]:
        return self._expected

    def run_in(
        self,
        uow: UnitOfWork,
        tenant_id: TenantId,
        service: str,
        *,
        correlation_id: CorrelationId | None = None,
    ) -> ErasureRecorded:
        """Record ``service``'s erasure on the tenant's open deletion request, in ``uow``."""
        current = uow.data_requests.open_deletion()
        if current is None:
            return ErasureRecorded(None, changed=False)
        at = self._clock()
        updated = current.record_erasure(service, self._expected, at)
        if updated == current:
            return ErasureRecorded(current, changed=False)
        uow.data_requests.save(updated)
        pending = list(updated.pending(self._expected))
        uow.audit.write(
            _entry(
                ERASED,
                updated,
                at,
                before={"status": current.status.value},
                after={
                    "service": service,
                    "status": updated.status.value,
                    "services_done": list(updated.services_done),
                    "services_pending": pending,
                },
                correlation_id=correlation_id,
            )
        )
        if updated.is_completed:
            uow.audit.write(
                _entry(
                    COMPLETED,
                    updated,
                    at,
                    before={"status": current.status.value},
                    after={"status": updated.status.value, "services": list(self._expected)},
                    correlation_id=correlation_id,
                )
            )
        return ErasureRecorded(updated, changed=True)


def _entry(
    action: str,
    request: DataRequest,
    at: datetime,
    *,
    before: dict[str, object],
    after: dict[str, object],
    correlation_id: CorrelationId | None,
) -> AuditEntry:
    return AuditEntry(
        action=action,
        tenant_id=request.tenant_id,
        subject_type=SUBJECT_TYPE,
        subject_id=str(request.id),
        actor=AuditActor.system(SERVICE),
        before=before,
        after=after,
        occurred_at=at,
        correlation_id=None if correlation_id is None else str(correlation_id),
    )


class ResendDeletion:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, tenant_id: TenantId, *, reason: str) -> DataRequest:
        """Send the tenant's open deletion request to the services again."""
        with self._unit_of_work(tenant_id) as uow:
            request = uow.data_requests.open_deletion()
            if request is None:
                raise DeletionRequestNotFoundError()
            uow.events.publish(deletion_event(request, None))
            uow.audit.write(
                audit_entry(
                    RESENT,
                    tenant_id=tenant_id,
                    subject_type=SUBJECT_TYPE,
                    subject_id=str(request.id),
                    at=self._clock(),
                    after={
                        "status": request.status.value,
                        "services_done": list(request.services_done),
                    },
                    reason=reason,
                    actor=ADMIN_ACTOR,
                )
            )
        return request
