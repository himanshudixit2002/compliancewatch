from collections.abc import Callable

import pytest

from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, TenantId, UserId
from notification.domain.ids import RecipientId
from notification.domain.recipients import (
    MAX_ADDRESSES,
    BusinessLink,
    DigestMode,
    Recipient,
    RecipientAddress,
    RecipientRole,
)
from notification.testing import NOON_IST

WA = Channel.WHATSAPP
EMAIL = Channel.EMAIL
PHONE = RecipientAddress(WA, "+919876543210", 0)
MAIL = RecipientAddress(EMAIL, "owner@example.com", 1)
SECOND_PHONE = RecipientAddress(WA, "+919800000000", 2)
BUSINESS = BusinessId.new()


def recipient(**changes: object) -> Recipient:
    values: dict[str, object] = {
        "id": RecipientId.new(),
        "tenant_id": TenantId.new(),
        "user_id": UserId.new(),
        "role": RecipientRole.OWNER,
        "addresses": (MAIL, PHONE),
        "businesses": (BusinessLink(BUSINESS, "Acme Traders"),),
        "created_at": NOON_IST,
        "updated_at": NOON_IST,
    }
    values.update(changes)
    return Recipient(**values)  # type: ignore[arg-type]


def everything_open(address: RecipientAddress) -> bool:
    return True


def closed(*shut: RecipientAddress) -> Callable[[RecipientAddress], bool]:
    return lambda address: address not in shut


def test_addresses_keep_position_order_and_businesses_id_order() -> None:
    other = BusinessId.new()
    found = recipient(
        businesses=(BusinessLink(BUSINESS, "Acme"), BusinessLink(other, "Other")),
    )
    assert found.addresses == (PHONE, MAIL)
    assert [link.business_id.value for link in found.businesses] == sorted(
        [BUSINESS.value, other.value]
    )


def test_the_primary_address_is_the_first_open_one() -> None:
    owner = recipient()
    assert owner.primary_address(everything_open) == PHONE
    assert owner.primary_address(closed(PHONE)) == MAIL
    assert owner.primary_address(closed(PHONE, MAIL)) is None


def test_the_fallback_is_the_next_open_address_on_another_channel() -> None:
    owner = recipient(addresses=(PHONE, MAIL, SECOND_PHONE))
    assert owner.fallback_after(WA, everything_open) == MAIL
    assert owner.fallback_after(WA, closed(MAIL)) is None, "the second number is WhatsApp too"
    assert owner.fallback_after(EMAIL, everything_open) == SECOND_PHONE
    assert recipient().fallback_after(EMAIL, everything_open) is None, "nothing after the email"
    email_first = recipient(addresses=(RecipientAddress(EMAIL, "a@b.c", 0),))
    assert email_first.fallback_after(WA, everything_open) == email_first.addresses[0]
    assert recipient(addresses=(PHONE,)).fallback_after(WA, everything_open) is None


@pytest.mark.parametrize(
    ("role", "mode", "by_digest"),
    [
        (RecipientRole.OWNER, DigestMode.OFF, False),
        (RecipientRole.STAFF, DigestMode.DAILY, True),
        (RecipientRole.CA_ADMIN, DigestMode.OFF, True),
        (RecipientRole.CA_STAFF, DigestMode.OFF, True),
    ],
)
def test_digest_is_chosen_or_comes_with_a_ca_role(
    role: RecipientRole, mode: DigestMode, by_digest: bool
) -> None:
    assert recipient(role=role, digest_mode=mode).by_digest is by_digest


def test_business_links() -> None:
    owner = recipient()
    assert owner.follows(BUSINESS)
    assert owner.label_for(BUSINESS) == "Acme Traders"
    stranger = BusinessId.new()
    assert not owner.follows(stranger)
    assert owner.label_for(stranger) == ""


@pytest.mark.parametrize(
    "changes",
    [
        {"addresses": (PHONE, RecipientAddress(EMAIL, "a@b.c", 0))},
        {"addresses": (PHONE, RecipientAddress(WA, "+919876543210", 1))},
        {
            "addresses": tuple(
                RecipientAddress(EMAIL, f"p{n}@example.com", n) for n in range(MAX_ADDRESSES + 1)
            )
        },
        {"businesses": (BusinessLink(BUSINESS), BusinessLink(BUSINESS, "again"))},
        {"org_label": " padded"},
        {"org_label": "x" * 201},
        {"language": ""},
        {"user_id": RecipientId.new()},
        {"addresses": ("+919876543210",)},
        {"businesses": (BUSINESS,)},
    ],
)
def test_a_recipient_that_breaks_a_rule_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(InvariantViolationError):
        recipient(**changes)


def test_address_and_link_rules() -> None:
    with pytest.raises(InvariantViolationError):
        RecipientAddress(WA, "+919876543210", -1)
    with pytest.raises(InvariantViolationError):
        RecipientAddress(WA, "", 0)
    with pytest.raises(InvariantViolationError):
        BusinessLink(BUSINESS, "trailing ")
    assert recipient(user_id=None).user_id is None
