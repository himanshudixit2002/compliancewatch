import pytest

from domain_kernel.channels import Channel
from notification.domain.addresses import normalise_address
from notification.domain.errors import InvalidAddressError

WHATSAPP = Channel.WHATSAPP
EMAIL = Channel.EMAIL


@pytest.mark.parametrize(
    "raw",
    [
        "919876543210",
        "+919876543210",
        "+91 98765 43210",
        "+91-98765-43210",
        "(+91) 98765.43210",
        "00919876543210",
        " 919876543210 ",
    ],
)
def test_every_form_of_a_number_is_one_key(raw: str) -> None:
    assert normalise_address(WHATSAPP, raw) == "+919876543210"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "+",
        "12345",
        "0919876543210",
        "+1234567890123456",
        "98765abc10",
        "+91 98765 4321x",
    ],
)
def test_what_is_not_a_phone_number_is_refused(raw: str) -> None:
    with pytest.raises(InvalidAddressError) as refused:
        normalise_address(WHATSAPP, raw)
    assert refused.value.type_slug == "notification-address-invalid"
    if raw.strip():
        assert raw.strip() not in refused.value.detail, "the detail never repeats the address"


def test_no_country_code_is_guessed() -> None:
    assert normalise_address(WHATSAPP, "9876543210") == "+9876543210"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("owner@example.com", "owner@example.com"),
        (" Owner@Example.COM ", "owner@example.com"),
        ("first.last+cw@mail.example.co.in", "first.last+cw@mail.example.co.in"),
        ("a@b.c", "a@b.c"),
    ],
)
def test_emails_are_trimmed_and_lower_cased(raw: str, expected: str) -> None:
    assert normalise_address(EMAIL, raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "owner",
        "owner@",
        "@example.com",
        "owner@@example.com",
        "own er@example.com",
        ".owner@example.com",
        "owner.@example.com",
        "ow..ner@example.com",
        "owner@localhost",
        "owner@-example.com",
        "owner@example..com",
        "o" * 65 + "@example.com",
        "owner@" + "e" * 250 + ".com",
    ],
)
def test_invalid_emails_are_refused(raw: str) -> None:
    with pytest.raises(InvalidAddressError):
        normalise_address(EMAIL, raw)
