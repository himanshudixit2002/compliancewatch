"""mask_pii and mask_pii_in: the identifiers masked in prompts, and in the text of log lines and
audit rows.

Every identifier here is made up: none belongs to a real person or business.
"""

import hashlib
import timeit
from collections.abc import Callable
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from domain_kernel.pii import (
    CYCLE,
    ID_KEY_SUFFIXES,
    MAX_DEPTH,
    PII_KINDS,
    PII_PATTERNS,
    RECORD_PII_PATTERNS,
    TOO_DEEP,
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
    assert [(kind, token) for kind, _, token in RECORD_PII_PATTERNS] == list(TOKENS.items())
    assert ID_KEY_SUFFIXES == ("_id", "_ids")


# ---- mask_pii: prompts --------------------------------------------------------------------------


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


def test_an_email_whose_local_part_starts_with_a_dot_is_masked_whole() -> None:
    """An address starts where no local-part character stands before it, once per run."""
    assert mask_pii("to .owner@example.com").text == "to [EMAIL]"
    assert mask_pii("to -owner@example.com, +owner@example.com").text == "to [EMAIL], [EMAIL]"


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


def test_a_plus_91_number_starts_a_number_of_its_own_even_after_a_digit() -> None:
    """So a run of glued numbers is masked in one pass, not one number per pass."""
    assert mask_pii("+919876543210+919876543210").text == "[PHONE][PHONE]"
    assert mask_pii("1+919876543210").text == "1[PHONE]"
    assert mask_pii_in("+919876543210+919876543210") == "[PHONE][PHONE]"


def test_masking_runs_until_nothing_more_is_found() -> None:
    """The PAN is glued to the phone number, so it stands on its own only once the phone is a
    token: one call masks both, and a second finds nothing."""
    result = mask_pii("ABCDE1234F09876543210")
    assert result.text == "[PAN][PHONE]"
    assert dict(result.counts) == {"gstin": 0, "pan": 1, "aadhaar": 0, "phone": 1, "email": 0}
    assert mask_pii(result.text).total == 0


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


# ---- mask_pii_in: log lines and audit rows ------------------------------------------------------


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


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("/v1/profile?email=owner%40example.com&x=1", "/v1/profile?email=[EMAIL]&x=1"),
        ("pan_ABCDE1234F", "pan_[PAN]"),
        ("gstin_29ABCDE1234F1Z5.json", "gstin_[GSTIN].json"),
        ("ref1ABCDE1234F2", "ref1[PAN]2"),
        ("ABCDE1234F09876543210", "[PAN][PHONE]"),
        ("aadhaar_234567890123_scan.pdf", "aadhaar_[AADHAAR]_scan.pdf"),
        ("/v1/pan/abcde1234f", "/v1/pan/[PAN]"),
        ("gstin=29abcde1234f1z5", "gstin=[GSTIN]"),
        ("+91 (987) 654 3210", "[PHONE]"),
        ("0091 98765 43210 and 00919876543210", "[PHONE] and [PHONE]"),
        ("0987 654 3210", "[PHONE]"),
        ("owner@example.com_old and owner@example.co.in2", "[EMAIL]_old and [EMAIL]2"),
        ("X29ABCDE1234F1Z5Y", "X[GSTIN]Y"),
        ("9876543210@example.com", "[PHONE]@example.com"),
    ],
)
def test_the_record_patterns_take_the_shapes_logs_and_urls_carry(text: str, masked: str) -> None:
    assert mask_pii_in(text) == masked


@pytest.mark.parametrize(
    "text",
    [
        "AbCdE1234F",  # mixed case is no PAN
        "XABCDE1234F",  # five letters only: a sixth is another code
        "ABCDE1234FG",
        "987 654 3210",  # a split phone number still needs its prefix
        "98765 43210",
        "1234567890",
        "nobody@localhost",
        "owner%40localhost",
    ],
)
def test_what_the_record_patterns_still_leave(text: str) -> None:
    assert mask_pii_in(text) == text


def test_id_keys_are_left_alone_at_any_depth_unless_turned_off() -> None:
    value = {
        "node_id": "234567890123",
        "obligation_ids": ["234567890123", "9876543210"],
        "reference": "234567890123",
        "inner": {"tenant_id": "9876543210", "phone": "9876543210"},
    }
    assert mask_pii_in(value) == {
        "node_id": "234567890123",
        "obligation_ids": ["234567890123", "9876543210"],
        "reference": "[AADHAAR]",
        "inner": {"tenant_id": "9876543210", "phone": "[PHONE]"},
    }
    assert mask_pii_in(value, id_keys=False) == {
        "node_id": "[AADHAAR]",
        "obligation_ids": ["[AADHAAR]", "[PHONE]"],
        "reference": "[AADHAAR]",
        "inner": {"tenant_id": "[PHONE]", "phone": "[PHONE]"},
    }


NODE = "5a3c6a0e-0d7b-4f43-9a4e-234567890123"
"""A made-up UUID whose last group reads as an Aadhaar number to ``mask_pii``."""
DIGEST = "3f0c2a9876543210b7e1d4c5a6f8091e2d3c4b5a69788776655443322110fedc"
"""A made-up SHA-256 digest with a phone number's ten digits in it."""


def test_a_uuid_is_kept_whole_wherever_it_stands_on_its_own() -> None:
    assert mask_pii(NODE).text == "5a3c6a0e-0d7b-4f43-9a4e-[AADHAAR]", "the prompt patterns"
    value = {
        "resolved_by": NODE,
        "path": f"/v1/nodes/{NODE.upper()}/attributes",
        "actor": f"user:{NODE}",
        "workflow": f"extract-knowledge-{NODE}",
        "versions": [f"tenant-{NODE}", f"{NODE}-v2", f"{NODE}_v2"],
        "note": f"{NODE}: owner@example.com, 9876543210 and 234567890123",
    }
    assert mask_pii_in(value) == {
        **value,
        "note": f"{NODE}: [EMAIL], [PHONE] and [AADHAAR]",
    }
    assert mask_pii_in(f"x{NODE}") == "x5a3c6a0e-0d7b-4f43-9a4e-[AADHAAR]", "not on its own"


def test_a_hex_id_is_kept_whole_wherever_it_stands_on_its_own() -> None:
    assert mask_pii(DIGEST).text != DIGEST, "the prompt patterns"
    for text in (
        DIGEST,
        f"ab/{DIGEST}",
        f"pipeline-triage-{DIGEST[:32]}",
        f"span {DIGEST[:16]} of trace {DIGEST[:32]}",
        f'"sha256": "{DIGEST}"',
    ):
        assert mask_pii_in(text) == text
    assert mask_pii_in(f"{DIGEST} 9876543210") == f"{DIGEST} [PHONE]"
    assert mask_pii_in(f"x{DIGEST[:31]}") == "x3f0c2a[PHONE]b7e1d4c5a6f8091", "not on its own"
    assert mask_pii_in(DIGEST.upper()) != DIGEST.upper(), "lower case only"
    assert mask_pii_in(f"{DIGEST[:16]}@example.com") == "[EMAIL]", "an address is masked whole"


def test_keys_are_never_masked_and_the_input_is_never_changed() -> None:
    inner = {"owner@example.com": "ABCDE1234F", 7: "9876543210"}
    value = MappingProxyType({"by_email": inner, "list": ["a@b.co"]})
    masked = mask_pii_in(value)
    assert masked == {"by_email": {"owner@example.com": "[PAN]", 7: "[PHONE]"}, "list": ["[EMAIL]"]}
    assert isinstance(masked, dict)
    assert inner == {"owner@example.com": "ABCDE1234F", 7: "9876543210"}
    assert value["list"] == ["a@b.co"]


class _Owner:
    def __repr__(self) -> str:
        return "Owner(email='owner@example.com')"


def test_a_leaf_that_is_not_json_is_rendered_and_masked_only_when_asked() -> None:
    owner = _Owner()
    leaves = [owner, {9876543210}, b"PAN ABCDE1234F", 2.5, None]
    assert mask_pii_in(leaves) == leaves
    assert mask_pii_in(leaves, render=repr) == [
        "Owner(email='[EMAIL]')",
        "{[PHONE]}",
        "b'PAN [PAN]'",
        2.5,
        None,
    ]


def test_a_value_inside_itself_and_one_nested_too_deep_never_recurse_without_end() -> None:
    cycle: list[object] = ["9876543210"]
    cycle.append(cycle)
    looped: dict[str, object] = {"note": "owner@example.com"}
    looped["self"] = {"again": looped}
    assert mask_pii_in(cycle) == ["[PHONE]", CYCLE]
    assert mask_pii_in(looped) == {"note": "[EMAIL]", "self": {"again": CYCLE}}
    shared = ["ABCDE1234F"]
    assert mask_pii_in([shared, shared]) == [["[PAN]"], ["[PAN]"]], "shared is not a cycle"

    deep: object = "9876543210"
    for _ in range(5_000):
        deep = {"inner": [deep]} if isinstance(deep, str) else {"inner": (deep,)}
    masked = mask_pii_in(deep)
    depth = 0
    while isinstance(masked, dict | list | tuple):
        masked = masked["inner"] if isinstance(masked, dict) else masked[0]
        depth += 1
    assert (masked, depth) == (TOO_DEEP, MAX_DEPTH)


# ---- time ---------------------------------------------------------------------------------------

ADVERSARIAL = {
    "dotted run with an @": "a." * 32_768 + "@",
    "dotted domain": "x@" + "a." * 32_768,
    "url-encoded @ run": "a%40" * 16_384,
    "digit run": "9" * 65_536,
    "+91 run": "+91" * 21_846,
    "glued +91 numbers": "+919876543210" * 5_042,
    "glued gstins": "29ABCDE1234F1Z5" * 4_370,
    "glued gstins ending in a letter": "29ABCDE1234FAZA" * 4_370,
}
"""64 KB each. The email pattern before the fix took some 2.2 s on the first two: from every
start in a run of local-part characters it read the run to its end and back. Glued numbers
would take seconds too if each pass unpicked one number of the run."""
BOUND_SECONDS = 0.05
"""Each takes a few milliseconds; the bound leaves room for a slow CI runner."""


@pytest.mark.parametrize("text", ADVERSARIAL.values(), ids=ADVERSARIAL.keys())
@pytest.mark.parametrize("mask", [mask_pii, mask_pii_in], ids=["prompt", "record"])
def test_64_kb_of_adversarial_text_is_masked_in_well_under_50_ms(
    mask: Callable[[str], object], text: str
) -> None:
    assert len(text) >= 64 * 1024
    best = min(timeit.repeat(lambda: mask(text), number=1, repeat=3))
    assert best < BOUND_SECONDS, f"{best * 1000:.1f} ms"


# ---- properties ---------------------------------------------------------------------------------

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
_RECORD_ONLY = {
    "gstin": st.from_regex(r"[0-9]{2}[a-z]{5}[0-9]{4}[a-z][0-9a-z]z[0-9a-z]", fullmatch=True),
    "pan": st.from_regex(r"[a-z]{5}[0-9]{4}[a-z]", fullmatch=True),
    "phone": st.from_regex(
        r"(\+91[ -]?|0091[ -]?|0)\(?[6-9][0-9]{2}\)?[ -]?[0-9]{3}[ -]?[0-9]{4}", fullmatch=True
    ),
    "email": st.from_regex(r"[a-z][a-z._+-]{0,15}%40[a-z]{1,10}\.(com|in|co\.in)", fullmatch=True),
}


@st.composite
def _planted(draw: st.DrawFn) -> tuple[str, str, str, str]:
    kind = draw(st.sampled_from(PII_KINDS))
    return kind, draw(_FILLER), draw(_IDENTIFIERS[kind]), draw(_FILLER)


@st.composite
def _planted_in_a_record(draw: st.DrawFn) -> tuple[str, str, str, str, str, str]:
    """An identifier in a prompt's shape or one only a record pattern takes, a PAN or GSTIN
    glued to an underscore or a digit: the kind, the filler before, the glue, the identifier,
    the glue and the filler after."""
    kind = draw(st.sampled_from(PII_KINDS))
    shapes = [_IDENTIFIERS[kind]] + ([_RECORD_ONLY[kind]] if kind in _RECORD_ONLY else [])
    glue = st.sampled_from(["", "_", "0", "9"] if kind in ("gstin", "pan") else [""])
    return (
        kind,
        draw(_FILLER),
        draw(glue),
        draw(st.one_of(shapes)),
        draw(glue),
        draw(_FILLER),
    )


@given(_FILLER)
def test_text_without_digits_or_at_signs_is_unchanged(text: str) -> None:
    result = mask_pii(text)
    assert result.text == text
    assert result.total == 0
    assert mask_pii_in(text) == text


@given(st.text(alphabet=st.characters(min_codepoint=0x0900, max_codepoint=0x097F)))
def test_devanagari_and_its_digits_are_never_touched(text: str) -> None:
    result = mask_pii(text)
    assert result.text == text
    assert result.total == 0
    assert mask_pii_in(text) == text


@given(_planted())
def test_an_identifier_between_spaces_is_masked_as_its_kind(
    planted: tuple[str, str, str, str],
) -> None:
    kind, before, identifier, after = planted
    result = mask_pii(f"{before} {identifier} {after}")
    assert result.text == f"{before} {TOKENS[kind]} {after}"
    assert result.counts[kind] == 1
    assert result.total == 1


@given(_planted_in_a_record())
def test_an_identifier_in_a_record_is_masked_as_its_kind_even_when_glued(
    planted: tuple[str, str, str, str, str, str],
) -> None:
    kind, before, left, identifier, right, after = planted
    masked = mask_pii_in(f"{before} {left}{identifier}{right} {after}")
    assert masked == f"{before} {left}{TOKENS[kind]}{right} {after}"


_HEX = "0123456789abcdef"
_HEX_IDS = st.one_of(
    st.binary(max_size=64).map(lambda data: hashlib.sha256(data).hexdigest()),
    st.uuids().map(lambda value: value.hex),
    st.integers(min_value=1, max_value=2**64 - 1).map(lambda span: f"{span:016x}"),
    st.builds(
        lambda head, letter, tail: head + letter + tail,
        st.text(alphabet=_HEX, min_size=15, max_size=40),
        st.sampled_from("abcdef"),
        st.text(alphabet=_HEX, max_size=40),
    ),
)
"""SHA-256 digests, ``uuid4().hex`` and other UUIDs' hex, 16-hex span ids, and any lower-case
hex run of 16 or more with a letter in it, where Hypothesis may put any digit run it likes."""
_CONTEXTS = ("{}", "pipeline-triage-{}", "{}-v2", "ab/{}", "span {} ended", "/v1/documents/{}")


@given(_HEX_IDS, st.sampled_from(_CONTEXTS))
def test_a_hex_id_is_never_altered(hex_id: str, context: str) -> None:
    text = context.format(hex_id)
    assert mask_pii_in(text) == text
    assert mask_pii_in({"note": text, "items": [text]}) == {"note": text, "items": [text]}


@given(
    st.uuids(),
    st.sampled_from(("extract-knowledge-{}", "tenant-{}", "{}-v2", "x-{}-y", "{}")),
    st.booleans(),
)
def test_a_uuid_next_to_a_dash_is_never_altered(value: UUID, context: str, upper: bool) -> None:
    text = context.format(str(value).upper() if upper else str(value))
    assert mask_pii_in(text) == text


_PIECES = st.one_of(
    *_IDENTIFIERS.values(),
    *_RECORD_ONLY.values(),
    st.sampled_from(["_", "0", "9", "a", "Z", " ", "-", "+", "@", "%40", ".", "[PAN]", "x"]),
    _HEX_IDS,
    _FILLER,
)


@given(st.lists(_PIECES, max_size=8).map("".join))
def test_masking_once_reaches_a_fixed_point(text: str) -> None:
    once = mask_pii(text)
    assert mask_pii(once.text).total == 0
    assert mask_pii(once.text).text == once.text
    masked = mask_pii_in(text)
    assert mask_pii_in(masked) == masked


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
def test_a_value_keeps_its_shape_and_each_text_outside_id_keys_is_masked(value: Any) -> None:
    masked = mask_pii_in(value)
    assert _shape(masked) == _shape(value)
    for (path, leaf), (_, out) in zip(_leaves(value), _leaves(masked), strict=True):
        under_an_id = any(isinstance(key, str) and key.endswith(("_id", "_ids")) for key in path)
        if isinstance(leaf, str) and not under_an_id:
            assert out == mask_pii_in(leaf)
            if _is_uuid(leaf):
                assert out == leaf
        else:
            assert out == leaf


def _is_uuid(text: str) -> bool:
    try:
        return str(UUID(text)) == text.lower()
    except ValueError:
        return False
