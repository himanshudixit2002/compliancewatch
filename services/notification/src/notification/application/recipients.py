"""Register, read, list and remove the recipients of a tenant's businesses.

Registering is an upsert by recipient id (the web app uses the person's user id): the recipient,
its addresses in the order given and its business links replace what was stored, and the
address directory is rewritten in the same transaction, so an address never routes to a
recipient that no longer has it. Addresses are normalised first; one listed twice keeps its
first place. Consent is not given here: an address still needs its opt-in before anything is
sent to it. A business's recipients are listed by id, a page at a time.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, TenantId, UserId
from notification.domain.addresses import normalise_address
from notification.domain.errors import RecipientNotFoundError
from notification.domain.ids import RecipientId
from notification.domain.recipients import (
    BusinessLink,
    DigestMode,
    Recipient,
    RecipientAddress,
    RecipientRole,
)
from notification.domain.repository import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class RecipientRegistration:
    tenant_id: TenantId
    recipient_id: RecipientId
    role: RecipientRole
    user_id: UserId | None = None
    language: str = "en"
    digest_mode: DigestMode = DigestMode.OFF
    org_label: str = ""
    addresses: Sequence[tuple[Channel, str]] = field(default=())
    """Channel and address as given, in the order they are to be tried."""
    businesses: Sequence[BusinessLink] = field(default=())


class RegisterRecipient:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, registration: RecipientRegistration) -> Recipient:
        addresses = _addresses(registration.addresses)
        now = self._clock()
        with self._unit_of_work(registration.tenant_id) as unit:
            existing = unit.recipients.get(registration.recipient_id)
            recipient = Recipient(
                id=registration.recipient_id,
                tenant_id=registration.tenant_id,
                user_id=registration.user_id,
                role=registration.role,
                language=registration.language,
                digest_mode=registration.digest_mode,
                org_label=registration.org_label,
                addresses=addresses,
                businesses=tuple(registration.businesses),
                created_at=now if existing is None else existing.created_at,
                updated_at=now,
            )
            unit.recipients.save(recipient)
            unit.directory.replace(recipient.tenant_id, recipient.id, recipient.addresses)
        return recipient


class GetRecipient:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, recipient_id: RecipientId) -> Recipient:
        with self._unit_of_work(tenant_id) as unit:
            recipient = unit.recipients.get(recipient_id)
        if recipient is None:
            raise RecipientNotFoundError(str(recipient_id))
        return recipient


class ListRecipients:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        tenant_id: TenantId,
        business_id: BusinessId,
        *,
        limit: int,
        after: RecipientId | None = None,
    ) -> Sequence[Recipient]:
        """At most ``limit`` of the recipients that follow the business, by id, after
        ``after``."""
        with self._unit_of_work(tenant_id) as unit:
            return unit.recipients.page(business_id, limit=limit, after=after)


class RemoveRecipient:
    """The recipient, its addresses, its links and its directory entries go; the notifications
    already sent to it stay until the retention sweep."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, tenant_id: TenantId, recipient_id: RecipientId) -> None:
        with self._unit_of_work(tenant_id) as unit:
            if not unit.recipients.delete(recipient_id):
                raise RecipientNotFoundError(str(recipient_id))
            unit.directory.remove(tenant_id, recipient_id)


def _addresses(given: Sequence[tuple[Channel, str]]) -> tuple[RecipientAddress, ...]:
    """Normalised, in the order given, each once."""
    seen: set[tuple[Channel, str]] = set()
    addresses: list[RecipientAddress] = []
    for channel, raw in given:
        key = (channel, normalise_address(channel, raw))
        if key in seen:
            continue
        seen.add(key)
        addresses.append(RecipientAddress(channel, key[1], len(addresses)))
    return tuple(addresses)
