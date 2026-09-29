"""Set-up an operator or a dev stack runs, never a request.

- ``CreateServiceClient``, ``RevokeServiceClient`` and ``ListServiceClients`` are what
  ``identity-admin service-client`` runs. A new client's secret is answered once and only its
  SHA-256 is stored.
- ``BootstrapInternalTenant`` is ``identity-admin bootstrap-internal``: it creates the internal
  tenant, where the regulatory team works, with its first admin, whose account it creates at the
  identity provider. There is one internal tenant; a second run is refused. The admin enrols a
  second factor at the provider before signing in, since admins sign in with one.
- ``EnsureDevServiceClients`` makes the development service clients exist with the shared dev
  secret: one client per caller in the committed ``identity_dev_clients.toml`` (or
  ``CW_IDENTITY_DEV_CLIENTS``). The composition root runs it only when ``CW_ENV`` is local or test
  and ``CW_IDENTITY_DEV_CLIENT_SECRET`` is set; the settings refuse that secret anywhere else.
"""

from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime

from domain_kernel.access import Scope
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.application.tenancy import first_user_events
from identity.domain.errors import (
    ProviderUnavailableError,
    ServiceClientExistsError,
    ServiceClientNotFoundError,
)
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.domain.service_clients import ServiceClient
from identity.domain.tenancy import FIRST_ROLE, Contact, SubjectEntry, Tenant, TenantKind, User


class CreateServiceClient:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, client_id: str, scopes: frozenset[Scope]) -> tuple[ServiceClient, str]:
        """The new client and its secret, which the caller shows once."""
        client, secret = ServiceClient.create(client_id, scopes, at=self._clock())
        with self._unit_of_work(None) as uow:
            if uow.service_clients.get(client_id) is not None:
                raise ServiceClientExistsError(client_id)
            uow.service_clients.add(client)
        return client, secret


class RevokeServiceClient:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, client_id: str) -> ServiceClient:
        """The client, revoked: it gets no new token; a revoked client stays revoked."""
        with self._unit_of_work(None) as uow:
            client = uow.service_clients.get(client_id)
            if client is None:
                raise ServiceClientNotFoundError(client_id)
            revoked = client.revoked(self._clock())
            if revoked is not client:
                uow.service_clients.save(revoked)
        return revoked


class ListServiceClients:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self) -> list[ServiceClient]:
        with self._unit_of_work(None) as uow:
            return uow.service_clients.list()


class EnsureDevServiceClients:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, clients: Mapping[str, frozenset[Scope]], secret: str) -> list[ServiceClient]:
        """Create each client, or bring an existing one to these scopes and this secret, and
        answer them by id. A dev client that was revoked is active again."""
        at = self._clock()
        ensured: list[ServiceClient] = []
        with self._unit_of_work(None) as uow:
            for client_id in sorted(clients):
                wanted = ServiceClient.with_secret(client_id, clients[client_id], secret, at=at)
                existing = uow.service_clients.get(client_id)
                if existing is None:
                    uow.service_clients.add(wanted)
                    ensured.append(wanted)
                    continue
                kept = ServiceClient(
                    client_id, wanted.secret_sha256, wanted.scopes, existing.created_at
                )
                if kept != existing:
                    uow.service_clients.save(kept)
                ensured.append(kept)
        return ensured


class BootstrapInternalTenant:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        provider: IdentityProvider,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._clock = clock

    def run(self, name: str, contact: Contact, *, display_name: str = "") -> tuple[Tenant, User]:
        """The internal tenant and its first admin. ``InternalTenantExistsError`` when there is
        one already."""
        at = self._clock()
        tenant = Tenant(TenantId.new(), TenantKind.INTERNAL, name.strip(), at)
        subject = self._provider.provision(
            email=contact.email, phone=contact.phone, display_name=display_name.strip()
        )
        admin = User.new(
            tenant,
            provider=self._provider.name,
            provider_subject=subject,
            contact=contact,
            roles=[FIRST_ROLE[TenantKind.INTERNAL]],
            at=at,
            display_name=display_name,
        )
        try:
            with self._unit_of_work(tenant.id) as uow:
                uow.tenants.add(tenant)
                uow.users.add(admin)
                uow.subjects.add(SubjectEntry.of(admin))
                for event in first_user_events(tenant, admin, changed_by=None):
                    uow.events.publish(event)
        except Exception:
            with suppress(ProviderUnavailableError):
                self._provider.delete(subject)
            raise
        return tenant, admin
