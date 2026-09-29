"""Who hears about a business, and on which addresses.

A recipient is a person in a tenant: the owner or staff of a business, or the admin or staff of
a CA firm that looks after client businesses. It carries its addresses in the order they are
tried and the businesses it hears about, each with the label the recipient knows it by.

- ``primary_address(is_open)``: the first address, in position order, that may be written to;
  ``is_open`` says whether one may (opted in and not suppressed).
- ``fallback_after(channel, is_open)``: when every attempt on ``channel`` has failed, the first
  open address on another channel that comes after the recipient's address on ``channel``. A
  recipient with WhatsApp first and email second falls back to email; one with email first falls
  back to nothing earlier in the list.
- ``by_digest``: the recipient's notifications wait for the daily digest, which is what a
  recipient chose (``digest_mode`` daily) and how a CA firm's people hear about their clients.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, TenantId, UserId
from notification.domain.ids import RecipientId

MAX_ADDRESSES = 10
MAX_BUSINESSES = 500
MAX_LABEL_LENGTH = 200


class RecipientRole(StrEnum):
    OWNER = "owner"
    STAFF = "staff"
    CA_ADMIN = "ca_admin"
    CA_STAFF = "ca_staff"


CA_ROLES = frozenset({RecipientRole.CA_ADMIN, RecipientRole.CA_STAFF})


class DigestMode(StrEnum):
    OFF = "off"
    """Each notification goes out on its own, or in a batch within the batching window."""
    DAILY = "daily"
    """Notifications wait for the daily digest."""


@dataclass(frozen=True, slots=True)
class RecipientAddress:
    channel: Channel
    address: str
    """Normalised (``normalise_address``)."""
    position: int
    """0 is tried first."""

    def __post_init__(self) -> None:
        require_instance(self.channel, Channel, "channel")
        require_text(self.address, "address")
        require_int(self.position, "position", minimum=0)


@dataclass(frozen=True, slots=True)
class BusinessLink:
    business_id: BusinessId
    label: str = ""
    """What the recipient calls the business, such as a CA firm's client name; may be empty."""

    def __post_init__(self) -> None:
        require_instance(self.business_id, BusinessId, "business_id")
        _require_label(self.label, "label")


AddressIsOpen = Callable[[RecipientAddress], bool]


@dataclass(frozen=True, slots=True, kw_only=True)
class Recipient:
    id: RecipientId
    tenant_id: TenantId
    user_id: UserId | None
    """The person's user id when they sign in to the web app; None for someone who does not."""
    role: RecipientRole
    language: str = "en"
    digest_mode: DigestMode = DigestMode.OFF
    org_label: str = ""
    """The organisation the recipient speaks for, such as the CA firm's name in its digest."""
    addresses: tuple[RecipientAddress, ...] = ()
    """In position order; positions and (channel, address) pairs are unique."""
    businesses: tuple[BusinessLink, ...] = ()
    """By business id."""
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.id, RecipientId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        if self.user_id is not None:
            require_instance(self.user_id, UserId, "user_id")
        require_instance(self.role, RecipientRole, "role")
        require_text(self.language, "language")
        require_instance(self.digest_mode, DigestMode, "digest_mode")
        _require_label(self.org_label, "org_label")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        addresses = tuple(self.addresses)
        for address in addresses:
            require_instance(address, RecipientAddress, "addresses")
        if len(addresses) > MAX_ADDRESSES:
            raise InvariantViolationError(f"a recipient has at most {MAX_ADDRESSES} addresses")
        if len({a.position for a in addresses}) != len(addresses):
            raise InvariantViolationError("address positions must be unique")
        if len({(a.channel, a.address) for a in addresses}) != len(addresses):
            raise InvariantViolationError("an address is listed twice")
        object.__setattr__(
            self, "addresses", tuple(sorted(addresses, key=lambda address: address.position))
        )
        businesses = tuple(self.businesses)
        for link in businesses:
            require_instance(link, BusinessLink, "businesses")
        if len(businesses) > MAX_BUSINESSES:
            raise InvariantViolationError(
                f"a recipient follows at most {MAX_BUSINESSES} businesses"
            )
        if len({link.business_id for link in businesses}) != len(businesses):
            raise InvariantViolationError("a business is listed twice")
        object.__setattr__(
            self, "businesses", tuple(sorted(businesses, key=lambda link: link.business_id.value))
        )

    @property
    def by_digest(self) -> bool:
        """Notifications wait for the daily digest: chosen, or the recipient is a CA firm's."""
        return self.digest_mode is DigestMode.DAILY or self.role in CA_ROLES

    def follows(self, business_id: BusinessId) -> bool:
        return any(link.business_id == business_id for link in self.businesses)

    def label_for(self, business_id: BusinessId) -> str:
        """The recipient's label for the business; '' when it has none or is not followed."""
        return next((link.label for link in self.businesses if link.business_id == business_id), "")

    def primary_address(self, is_open: AddressIsOpen) -> RecipientAddress | None:
        """The first open address in position order, or None when none is open."""
        return next((address for address in self.addresses if is_open(address)), None)

    def fallback_after(self, channel: Channel, is_open: AddressIsOpen) -> RecipientAddress | None:
        """The first open address on another channel after the recipient's address on
        ``channel`` (from the start when it has none there), or None."""
        failed_at = next(
            (address.position for address in self.addresses if address.channel is channel), -1
        )
        return next(
            (
                address
                for address in self.addresses
                if address.position > failed_at
                and address.channel is not channel
                and is_open(address)
            ),
            None,
        )


def _require_label(value: object, name: str) -> str:
    text = require_instance(value, str, name)
    if text != text.strip():
        raise InvariantViolationError(f"{name} must not have leading or trailing whitespace")
    if len(text) > MAX_LABEL_LENGTH:
        raise InvariantViolationError(f"{name} is longer than {MAX_LABEL_LENGTH} characters")
    return text
