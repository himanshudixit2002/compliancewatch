"""Identity's part of a deletion request's erasure, the answers it records, and the resend.

- ``CheckErasure`` is what identity holds of a tenant's deletion (``ErasureCheck``): the tenant's
  status and kind, and the event it last sent for the tenant's open deletion request. Identity's
  own erasure consumer checks every ``tenant.deletion.requested`` against it before it touches
  the provider (``domain_kernel.erasure.erasure_refusal``), and ``GET
  /v1/identity/erasures/{tenant_id}`` answers it to every other service's consumer, which checks
  the same before erasing.
- ``DeleteProviderAccounts`` is the first half of identity's erasure (``identity.erasure``): with
  no transaction open, it deletes the account of every user of the tenant at the identity
  provider. An account already gone counts as deleted, so a redelivered request deletes nothing
  twice; a provider that cannot be reached raises, and the consumer retries, then
  dead-letters. Users signed in through another provider are listed with their user id, the
  provider and its subject (``ProviderDeletions.elsewhere``), in the log and the ``tenant.erased``
  audit entry, so the operator can delete them there (the runbook). The second half, in the
  consumer's transaction, is the ``IdentityEraser`` (``identity.domain.erasure``).
- ``RecordErasure`` is the consumer of ``tenant.data.erased`` (``identity.erasure-records``): an
  answer to the event identity last sent for the tenant's open deletion request adds the service
  to the request's pass with a ``data_request.erased`` audit entry (any other answer changes
  nothing). Once every expected service has answered the first pass it schedules the second:
  ``tenant.deletion.requested`` again, held in the outbox ``second_pass_after`` (the settings'
  ``CW_IDENTITY_ERASURE_SECOND_PASS_SECONDS``, longer than an access token lives) and checked by
  the services like the first, with a ``data_request.second_pass_scheduled`` entry. Once every
  service has answered the second pass the request completes, with a ``data_request.completed``
  entry. It records whatever the flag says: an answer means the service has erased, and the
  request must show it.
- ``ResendDeletion`` (``identity-admin erasure resend``) writes ``tenant.deletion.requested``
  again for the tenant's open deletion request and makes it the event the services check: what
  an operator runs once the flag is on for a request made while it was off, or to retry after a
  dead letter. Every service's erasure is idempotent, so a service that had answered erases
  nothing more and answers again. An older event still in flight is refused from then on (and
  dead-lettered, with an audit row). A completed request is not sent again: every service
  would refuse it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.erasure import ErasureCheck
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, EventId, TenantId
from identity.application.audit import audit_entry
from identity.application.data_requests import SUBJECT_TYPE, deletion_event
from identity.domain.data_requests import DataRequest
from identity.domain.errors import DeletionRequestNotFoundError
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import TenantKind, User

SERVICE: Final = "identity"
ERASED: Final = "data_request.erased"
SECOND_PASS: Final = "data_request.second_pass_scheduled"
COMPLETED: Final = "data_request.completed"
RESENT: Final = "data_request.resent"
ADMIN_ACTOR: Final = AuditActor.system("identity-admin")
SECOND_PASS_AFTER: Final = timedelta(seconds=900)
"""How long after the first pass the second goes out by default: longer than an access token
lives (``access_token_ttl_seconds``, 600 by default)."""


class CheckErasure:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId) -> ErasureCheck:
        """What identity holds of the tenant's deletion; a tenant it does not hold has no
        status."""
        with self._unit_of_work(tenant_id) as uow:
            tenant = uow.tenants.get(tenant_id)
            if tenant is None:
                return ErasureCheck(tenant_id, None)
            request = next(
                (
                    found
                    for found in uow.data_requests.list()
                    if found.is_deletion and not found.is_completed
                ),
                None,
            )
        return ErasureCheck(
            tenant_id,
            tenant.status.value,
            internal=tenant.kind is TenantKind.INTERNAL,
            deletion_event_id=None if request is None else request.deletion_event_id,
        )


@dataclass(frozen=True, slots=True)
class OtherAccount:
    """A user signed in through another provider than this process's: the operator deletes
    the account there by hand (docs/runbooks/data-requests.md)."""

    user_id: str
    provider: str
    subject: str

    def document(self) -> dict[str, str]:
        return {"user_id": self.user_id, "provider": self.provider, "subject": self.subject}


@dataclass(frozen=True, slots=True)
class ProviderDeletions:
    """What the provider was asked: how many accounts it deleted, and the accounts of another
    provider, which this process cannot reach."""

    deleted: int
    elsewhere: tuple[OtherAccount, ...] = ()

    @property
    def other_provider(self) -> int:
        return len(self.elsewhere)

    def details(self) -> dict[str, object]:
        """What the ``tenant.erased`` audit entry adds (masked as every entry is)."""
        return {"other_provider_accounts": [account.document() for account in self.elsewhere]}


class DeleteProviderAccounts:
    def __init__(self, unit_of_work: UnitOfWorkFactory, provider: IdentityProvider) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider

    def users(self, tenant_id: TenantId) -> list[User]:
        with self._unit_of_work(tenant_id) as uow:
            return uow.users.list()

    def run(self, tenant_id: TenantId) -> ProviderDeletions:
        deleted = 0
        elsewhere: list[OtherAccount] = []
        for user in self.users(tenant_id):
            if user.provider != self._provider.name:
                elsewhere.append(OtherAccount(str(user.id), user.provider, user.provider_subject))
                continue
            self._provider.delete(user.provider_subject)
            deleted += 1
        return ProviderDeletions(deleted, tuple(elsewhere))


@dataclass(frozen=True, slots=True)
class ErasureRecorded:
    """The deletion request after one service's answer; None when the tenant has no open one
    (an answer after completion, or a redelivery). ``stale`` is an answer to another event than
    the one identity sent last."""

    request: DataRequest | None
    changed: bool
    stale: bool = False

    @property
    def completed(self) -> bool:
        return self.request is not None and self.request.is_completed


class RecordErasure:
    def __init__(
        self,
        expected: tuple[str, ...],
        *,
        clock: Callable[[], datetime] = utc_now,
        second_pass_after: timedelta = SECOND_PASS_AFTER,
    ) -> None:
        if SERVICE not in expected:
            raise ValueError("a deletion request always waits for identity")
        if second_pass_after < timedelta(0):
            raise ValueError("the second pass cannot go out before the first is answered")
        self._expected = expected
        self._clock = clock
        self._second_pass_after = second_pass_after

    @property
    def expected(self) -> tuple[str, ...]:
        return self._expected

    def run_in(
        self,
        uow: UnitOfWork,
        tenant_id: TenantId,
        service: str,
        *,
        deletion_event_id: EventId,
        correlation_id: CorrelationId | None = None,
    ) -> ErasureRecorded:
        """Record ``service``'s erasure for ``deletion_event_id`` on the tenant's open deletion
        request, in ``uow``; schedule the second pass once the first is complete."""
        current = uow.data_requests.open_deletion()
        if current is None:
            return ErasureRecorded(None, changed=False)
        if deletion_event_id != current.deletion_event_id:
            return ErasureRecorded(current, changed=False, stale=True)
        at = self._clock()
        updated = current.record_erasure(service, self._expected, at, event_id=deletion_event_id)
        if updated == current:
            return ErasureRecorded(current, changed=False)
        answered = updated
        if updated.first_pass_complete(self._expected):
            due = at + self._second_pass_after
            second = deletion_event(updated, None, correlation_id=correlation_id)
            updated = updated.schedule_second_pass(second.event_id, due, self._expected)
            uow.events.publish(second, not_before=due)
        uow.data_requests.save(updated)
        uow.audit.write(
            _entry(
                ERASED,
                updated,
                at,
                before={"status": current.status.value},
                after={
                    "service": service,
                    "pass": current.erasure_pass,
                    "status": answered.status.value,
                    "services_done": list(answered.services_done),
                    "second_pass_done": list(answered.second_pass_done),
                    "services_pending": list(answered.pending(self._expected)),
                },
                correlation_id=correlation_id,
            )
        )
        if updated.second_pass_at is not None and current.second_pass_at is None:
            uow.audit.write(
                _entry(
                    SECOND_PASS,
                    updated,
                    at,
                    before={"pass": 1},
                    after={
                        "pass": 2,
                        "second_pass_at": updated.second_pass_at.isoformat(),
                        "deletion_event_id": str(updated.deletion_event_id),
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
        """Send the tenant's open deletion request to the services again, as the event they
        check from now on."""
        with self._unit_of_work(tenant_id) as uow:
            current = uow.data_requests.open_deletion()
            if current is None:
                raise DeletionRequestNotFoundError()
            event = deletion_event(current, None)
            request = current.sent(event.event_id)
            uow.data_requests.save(request)
            uow.events.publish(event)
            uow.audit.write(
                audit_entry(
                    RESENT,
                    tenant_id=tenant_id,
                    subject_type=SUBJECT_TYPE,
                    subject_id=str(request.id),
                    at=self._clock(),
                    after={
                        "status": request.status.value,
                        "pass": request.erasure_pass,
                        "services_done": list(request.services_done),
                        "second_pass_done": list(request.second_pass_done),
                        "deletion_event_id": str(event.event_id),
                    },
                    reason=reason,
                    actor=ADMIN_ACTOR,
                )
            )
        return request
