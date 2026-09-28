import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from domain_kernel.identifiers import GSTIN_PATTERN, PAN_PATTERN, Gstin, Pan


def test_pan_and_gstin_parts() -> None:
    gstin = Gstin("29ABCDE1234F1Z5")
    assert gstin.state_code == "29"
    assert gstin.pan == Pan("ABCDE1234F")
    assert gstin.entity_code == "1"
    assert str(gstin) == "29ABCDE1234F1Z5"
    assert str(Pan("ABCDE1234F")) == "ABCDE1234F"


def test_parse_accepts_spaces_and_lower_case() -> None:
    assert Gstin.parse(" 29abcde1234f1z5 ") == Gstin("29ABCDE1234F1Z5")
    assert Pan.parse("abcde 1234 f") == Pan("ABCDE1234F")


@pytest.mark.parametrize("text", ["ABCDE1234", "abcde1234f", "ABCDE12345", "1BCDE1234F", ""])
def test_pan_rejects_malformed_values(text: str) -> None:
    with pytest.raises(InvariantViolationError, match="pan"):
        Pan(text)


@pytest.mark.parametrize(
    "text", ["29ABCDE1234F1Z", "29ABCDE1234F1A5", "2AABCDE1234F1Z5", "29ABCDE1234F0Z5", ""]
)
def test_gstin_rejects_malformed_values(text: str) -> None:
    with pytest.raises(InvariantViolationError, match="gstin"):
        Gstin(text)


def test_non_text_is_rejected() -> None:
    with pytest.raises(InvariantViolationError):
        Pan(1234567890)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError):
        Gstin.parse(None)  # type: ignore[arg-type]


@given(st.from_regex(PAN_PATTERN, fullmatch=True))
def test_every_pan_matching_the_pattern_is_accepted(text: str) -> None:
    assert Pan(text).value == text


@given(st.from_regex(GSTIN_PATTERN, fullmatch=True))
def test_every_gstin_matching_the_pattern_exposes_its_pan(text: str) -> None:
    gstin = Gstin(text)
    assert gstin.pan.value == text[2:12]
    assert gstin.state_code == text[:2]
