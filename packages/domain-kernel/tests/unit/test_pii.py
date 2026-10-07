"""mask_pii and mask_pii_in: the identifiers masked in text and in JSON-like values.

Every identifier here is made up: none belongs to a real person or business.
"""

from types import MappingProxyType
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from domain_kernel.pii import (
    ID_KEY_SUFFIXES,
    PII_KINDS,
    PII_PATTERNS,
    MaskResult,
    mask_pii,
    mask_pii_in,
)

TOKENS = {kind: token for kind, _, token in PII_PATTERNS}


def test_kinds_and_tokens_in_the_order_they_apply() -> None:
    assert PII_KINDS == ("gstin", "pan", "aadhaar", "phone", "email")
    assert TOKENS == {
        "gstin": "[GSTIN]",
        "pan": "[PAN]",
        "aadhaar": "[AADHAAR]",
        "phone": "[PHONE]",
        "email": "[EMAIL]",
    }
    assert ID_KEY_SUFFIXES == ("_id", "_ids")


def test_gstin_is_masked_whole_before_the_pan_inside_it() -> None:
    result = mask_pii("GSTIN 29ABCDE1234F1Z5 of the supplier")
    assert result.text == "GSTIN [GSTIN] of the supplier"
    assert result.counts["gstin"] == 1
    assert result.counts["pan"] == 0
    assert result.total == 1


def test_pan_on_its_own_in_upper_case_only() -> None:
    result = mask_pii("PAN ABCDE1234F and abcde1234f")
    assert result.text == "PAN [PAN] and abcde1234f"
    assert dict(result.counts) == {"gstin": 0, "pan": 1, "aadhaar": 0, "phone": 0, "email": 0}


@pytest.mark.parametrize("number", ["2345 6789 0123", "2345-6789-0123", "234567890123"])
def test_aadhaar_layouts(number: str) -> None:
    result = mask_pii(f"Aadhaar: {number}.")
    assert result.text == "Aadhaar: [AADHAAR]."
    assert result.counts["aadhaar"] == 1
    assert result.counts["phone"] == 0


def test_aadhaar_never_starts_with_zero_or_one() -> None:
    assert mask_pii("1345 6789 0123").counts["aadhaar"] == 0
    assert mask_pii("0345 6789 0123").counts["aadhaar"] == 0


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
    result = mask_pii(f"call {number} now")
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
    result = mask_pii(text)
    assert result.text == text
    assert result.total == 0


def test_email() -> None:
    result = mask_pii("write to ca.firm+gst@example.co.in or nobody@localhost")
    assert result.text == "write to [EMAIL] or nobody@localhost"
    assert result.counts["email"] == 1


def test_hindi_sentence_is_untouched() -> None:
    text = "पंजीकृत व्यक्ति को मासिक विवरणी दाखिल करनी होगी। संख्या १२३४५६७८९० है।"
    result = mask_pii(text)
    assert result.text == text
    assert result.total == 0


def test_empty_text() -> None:
    result = mask_pii("")
    assert result.text == ""
    assert set(result.counts) == set(PII_KINDS)
    assert result.total == 0


def test_all_kinds_in_one_text_are_counted_per_kind() -> None:
    result = mask_pii(
        "29ABCDE1234F1Z5 ABCDE1234F 2345 6789 0123 9876543210 a@b.co and again 9876543211"
    )
    assert result.text == "[GSTIN] [PAN] [AADHAAR] [PHONE] [EMAIL] and again [PHONE]"
    assert dict(result.counts) == {"gstin": 1, "pan": 1, "aadhaar": 1, "phone": 2, "email": 1}
    assert result.total == 6


def test_an_email_with_digits_but_no_other_identifier() -> None:
    result = mask_pii("ops2000@example.com")
    assert result.text == "[EMAIL]"
    assert dict(result.counts) == {"gstin": 0, "pan": 0, "aadhaar": 0, "phone": 0, "email": 1}


def test_result_fills_missing_counts_and_is_read_only() -> None:
    result = MaskResult("x", {"pan": 2})
    assert dict(result.counts) == {"gstin": 0, "pan": 2, "aadhaar": 0, "phone": 0, "email": 0}
    assert result.total == 2
    with pytest.raises(TypeError):
        result.counts["pan"] = 0  # type: ignore[index]
    with pytest.raises(InvariantViolationError, match="text must be str"):
        mask_pii(None)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="text must be str"):
        MaskResult(b"x", {})  # type: ignore[arg-type]


# ---- mask_pii_in -------------------------------------------------------------------------------


def test_every_text_at_any_depth_is_masked() -> None:
    value = {
        "contact": "Example Owner, owner@example.com",
        "phones": ["+91 98765 43210", ("09876543210", 7)],
        "nested": {"note": "PAN ABCDE1234F", "count": 2, "flag": True, "none": None},
    }
    assert mask_pii_in(value) == {
        "contact": "Example Owner, [EMAIL]",
        "phones": ["[PHONE]", ("[PHONE]", 7)],
        "nested": {"note": "PAN [PAN]", "count": 2, "flag": True, "none": None},
    }
    assert mask_pii_in("ABCDE1234F") == "[PAN]"
    assert mask_pii_in(9876543210) == 9876543210, "only text is masked"


def test_id_keys_and_kept_keys_are_left_alone_at_any_depth() -> None:
    value = {
        "node_id": "234567890123",
        "obligation_ids": ["234567890123", "9876543210"],
        "reference": "234567890123",
        "inner": {"tenant_id": "9876543210", "phone": "9876543210"},
        "stamp": "9876543210",
    }
    masked = mask_pii_in(value, keep={"stamp"})
    assert masked == {
        "node_id": "234567890123",
        "obligation_ids": ["234567890123", "9876543210"],
        "reference": "[AADHAAR]",
        "inner": {"tenant_id": "9876543210", "phone": "[PHONE]"},
        "stamp": "9876543210",
    }


NODE = "5a3c6a0e-0d7b-4f43-9a4e-234567890123"
"""A made-up UUID whose last group reads as an Aadhaar number to ``mask_pii``."""


def test_a_uuid_is_kept_whole_wherever_it_stands() -> None:
    assert mask_pii(NODE).text == "5a3c6a0e-0d7b-4f43-9a4e-[AADHAAR]", "the patterns alone"
    value = {
        "resolved_by": NODE,
        "path": f"/v1/nodes/{NODE.upper()}/attributes",
        "actor": f"user:{NODE}",
        "note": f"{NODE}: owner@example.com, 9876543210 and 234567890123",
    }
    assert mask_pii_in(value) == {
        "resolved_by": NODE,
        "path": f"/v1/nodes/{NODE.upper()}/attributes",
        "actor": f"user:{NODE}",
        "note": f"{NODE}: [EMAIL], [PHONE] and [AADHAAR]",
    }
    assert mask_pii_in(f"x{NODE}") == "x5a3c6a0e-0d7b-4f43-9a4e-[AADHAAR]", "not on its own"


def test_keys_are_never_masked_and_the_input_is_never_changed() -> None:
    inner = {"owner@example.com": "ABCDE1234F", 7: "9876543210"}
    value = MappingProxyType({"by_email": inner, "list": ["a@b.co"]})
    masked = mask_pii_in(value)
    assert masked == {"by_email": {"owner@example.com": "[PAN]", 7: "[PHONE]"}, "list": ["[EMAIL]"]}
    assert isinstance(masked, dict)
    assert inner == {"owner@example.com": "ABCDE1234F", 7: "9876543210"}
    assert value["list"] == ["a@b.co"]


# ---- properties --------------------------------------------------------------------------------

_FILLER = st.text(alphabet=st.characters(exclude_characters="0123456789@"), max_size=40)
"""Text around an identifier: anything without an ASCII digit or an ``@``."""
_IDENTIFIERS = {
    "gstin": st.from_regex(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]", fullmatch=True),
    "pan": st.from_regex(r"[A-Z]{5}[0-9]{4}[A-Z]", fullmatch=True),
    "aadhaar": st.from_regex(r"[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}", fullmatch=True),
    "phone": st.from_regex(
        r"(\+91[ -]?|0)?[6-9][0-9]{9}|(\+91[ -]?|0)[6-9][0-9]{4}[ -][0-9]{5}", fullmatch=True
    ),
    "email": st.from_regex(r"[a-z][a-z._%+-]{0,15}@[a-z]{1,10}\.(com|in|co\.in)", fullmatch=True),
}


@st.composite
def _planted(draw: st.DrawFn) -> tuple[str, str, str, str]:
    kind = draw(st.sampled_from(PII_KINDS))
    return kind, draw(_FILLER), draw(_IDENTIFIERS[kind]), draw(_FILLER)


@given(_FILLER)
def test_text_without_digits_or_at_signs_is_unchanged(text: str) -> None:
    result = mask_pii(text)
    assert result.text == text
    assert result.total == 0


@given(st.text(alphabet=st.characters(min_codepoint=0x0900, max_codepoint=0x097F)))
def test_devanagari_and_its_digits_are_never_touched(text: str) -> None:
    result = mask_pii(text)
    assert result.text == text
    assert result.total == 0


@given(_planted())
def test_an_identifier_between_spaces_is_masked_as_its_kind(
    planted: tuple[str, str, str, str],
) -> None:
    kind, before, identifier, after = planted
    result = mask_pii(f"{before} {identifier} {after}")
    assert result.text == f"{before} {TOKENS[kind]} {after}"
    assert result.counts[kind] == 1
    assert result.total == 1


_KEYS = st.sampled_from(["note", "contact", "items", "node_id", "obligation_ids", "status"])
_LEAVES = st.one_of(
    st.text(max_size=20),
    _IDENTIFIERS["pan"],
    _IDENTIFIERS["phone"],
    _IDENTIFIERS["email"],
    st.uuids().map(str),
    st.integers(),
    st.booleans(),
    st.none(),
)
_VALUES = st.recursive(
    _LEAVES,
    lambda children: (
        st.lists(children, max_size=3)
        | st.tuples(children, children)
        | st.dictionaries(_KEYS, children, max_size=3)
    ),
    max_leaves=12,
)


def _leaves(
    value: object, path: tuple[object, ...] = ()
) -> list[tuple[tuple[object, ...], object]]:
    """Every leaf of ``value`` with the keys and indexes that lead to it."""
    if isinstance(value, dict):
        return [leaf for key, item in value.items() for leaf in _leaves(item, (*path, key))]
    if isinstance(value, list | tuple):
        return [leaf for index, item in enumerate(value) for leaf in _leaves(item, (*path, index))]
    return [(path, value)]


def _is_uuid(text: str) -> bool:
    try:
        return str(UUID(text)) == text.lower()
    except ValueError:
        return False


def _shape(value: object) -> object:
    """``value`` with every text emptied: the containers, their types, keys and other leaves."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_shape(item) for item in value)
    return "" if isinstance(value, str) else value


@given(_VALUES)
def test_a_value_keeps_its_shape_and_each_text_outside_id_keys_is_masked(value: object) -> None:
    masked = mask_pii_in(value)
    assert _shape(masked) == _shape(value)
    for (path, leaf), (_, out) in zip(_leaves(value), _leaves(masked), strict=True):
        under_an_id = any(isinstance(key, str) and key.endswith(("_id", "_ids")) for key in path)
        if isinstance(leaf, str) and not under_an_id and not _is_uuid(leaf):
            assert out == mask_pii(leaf).text
        else:
            assert out == leaf
