import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.scrub import PII_KINDS, ScrubResult, scrub


def test_gstin_is_masked_whole_before_the_pan_inside_it() -> None:
    result = scrub("GSTIN 29ABCDE1234F1Z5 of the supplier")
    assert result.text == "GSTIN [GSTIN] of the supplier"
    assert result.counts["gstin"] == 1
    assert result.counts["pan"] == 0
    assert result.total == 1


def test_pan_on_its_own() -> None:
    result = scrub("PAN ABCDE1234F and abcde1234f")
    assert result.text == "PAN [PAN] and abcde1234f"
    assert dict(result.counts) == {"gstin": 0, "pan": 1, "aadhaar": 0, "phone": 0, "email": 0}


@pytest.mark.parametrize("number", ["2345 6789 0123", "2345-6789-0123", "234567890123"])
def test_aadhaar_layouts(number: str) -> None:
    result = scrub(f"Aadhaar: {number}.")
    assert result.text == "Aadhaar: [AADHAAR]."
    assert result.counts["aadhaar"] == 1
    assert result.counts["phone"] == 0


def test_aadhaar_never_starts_with_zero_or_one() -> None:
    assert scrub("1345 6789 0123").counts["aadhaar"] == 0


@pytest.mark.parametrize(
    "number",
    [
        "9876543210",
        "+919876543210",
        "+91 9876543210",
        "09876543210",
        "+91 98765 43210",
        "+91-98765-43210",
        "098765 43210",
    ],
)
def test_phone_layouts(number: str) -> None:
    result = scrub(f"call {number} now")
    assert result.text == "call [PHONE] now"
    assert result.counts["phone"] == 1
    assert result.counts["aadhaar"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "9876 543210",
        "98765 43210",
        "98765-43210",
        "Amount 75000 12345",
        "HSN 99871 23456",
        "98765  43210",
        "987 654 3210",
        "1234567890",
        "98765432101",
        "order 5876543210",
    ],
)
def test_phone_non_matches(text: str) -> None:
    result = scrub(text)
    assert result.text == text
    assert result.total == 0


def test_email() -> None:
    result = scrub("write to ca.firm+gst@example.co.in or nobody@localhost")
    assert result.text == "write to [EMAIL] or nobody@localhost"
    assert result.counts["email"] == 1


def test_hindi_sentence_is_untouched() -> None:
    text = "पंजीकृत व्यक्ति को मासिक विवरणी दाखिल करनी होगी। संख्या १२३४५६७८९० है।"
    result = scrub(text)
    assert result.text == text
    assert result.total == 0


def test_empty_text() -> None:
    result = scrub("")
    assert result.text == ""
    assert set(result.counts) == set(PII_KINDS)
    assert result.total == 0


def test_all_kinds_in_one_text() -> None:
    result = scrub(
        "29ABCDE1234F1Z5 ABCDE1234F 2345 6789 0123 9876543210 a@b.co and again 9876543211"
    )
    assert result.text == "[GSTIN] [PAN] [AADHAAR] [PHONE] [EMAIL] and again [PHONE]"
    assert dict(result.counts) == {"gstin": 1, "pan": 1, "aadhaar": 1, "phone": 2, "email": 1}
    assert result.total == 6


def test_result_fills_missing_counts_and_is_read_only() -> None:
    result = ScrubResult("x", {"pan": 2})
    assert dict(result.counts) == {"gstin": 0, "pan": 2, "aadhaar": 0, "phone": 0, "email": 0}
    with pytest.raises(TypeError):
        result.counts["pan"] = 0  # type: ignore[index]
    with pytest.raises(InvariantViolationError, match="text must be str"):
        scrub(None)  # type: ignore[arg-type]


@given(st.text(alphabet=st.characters(blacklist_characters="0123456789@")))
def test_text_without_digits_or_at_signs_is_unchanged(text: str) -> None:
    result = scrub(text)
    assert result.text == text
    assert result.total == 0
