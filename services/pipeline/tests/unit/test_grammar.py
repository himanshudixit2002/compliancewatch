"""The mention grammar on the recorded notifications and on small texts, one pattern at a time.

The recorded cases pin exact spans: a change to the grammar that moves one fails here, and the
mention it would store no longer points at the same characters.
"""

import base64
import itertools
import json
import re
from pathlib import Path
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domain_kernel.documents import DocumentRef, ParsedDocument, RawDocument
from domain_kernel.ids import SourceId
from domain_kernel.knowledge import EntityType, Instrument, normalise_name
from pipeline.domain.grammar import (
    GRAMMAR_VERSION,
    STATE_NAMES,
    GrammarMatch,
    find_mentions,
    mentions_for,
)
from pipeline.infrastructure.parsers import PdfParser
from pipeline.testing import RECORDED_NOTIFICATIONS

GAZETTE_PART = re.compile(r"part\s+ii\s*,\s*$", re.IGNORECASE)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cbic"
N = EntityType.NOTIFICATION
S = EntityType.SECTION
R = EntityType.RULE
F = EntityType.FORM
HINDI_CENTRAL_TAX = "\u0915\u0947\u0928\u094d\u0926\u094d\u0930\u0940\u092f \u0915\u0930"


def recorded(file_name: str) -> ParsedDocument:
    wrapper = json.loads((FIXTURES / f"{file_name}.json").read_text(encoding="utf-8"))
    ref = DocumentRef(SourceId(UUID(int=1)), f"https://example.invalid/{file_name}")
    raw = RawDocument.from_bytes(ref, base64.b64decode(wrapper["data"]), "application/pdf")
    return PdfParser().parse(raw)


def names(text: str, **kwargs: object) -> list[tuple[EntityType, str]]:
    return [(m.entity_type, m.proposed_name) for m in find_mentions(text, **kwargs)]  # type: ignore[arg-type]


def test_the_grammar_has_a_version() -> None:
    assert GRAMMAR_VERSION == "grammar@1"


def test_the_recorded_01_2026_gives_exactly_five_mentions() -> None:
    doc = recorded("gst-ct-01-2026.pdf")
    found = mentions_for(doc, own_ref="01/2026-Central Tax")
    assert [
        (m.clause_ref, m.span_start, m.span_end, m.entity_type, m.proposed_name, m.self_ref)
        for m in found
    ] == [
        ("en.p2", 106, 144, N, "01/2026-central tax", True),
        ("en.p3", 53, 83, S, "39(6)@cgst-act", False),
        ("en.p3", 265, 277, F, "GSTR-3B", False),
        ("en.p3", 418, 447, S, "39(1)@cgst-act", False),
        ("en.p3", 458, 497, R, "61(1)(i)@cgst-rules", False),
    ]


def test_the_hindi_rendering_names_its_own_number_and_the_form() -> None:
    doc = recorded("gst-ct-01h-2026.pdf")
    found = mentions_for(doc, own_ref="01/2026-Central Tax")
    notifications = [m for m in found if m.entity_type is N]
    assert [(m.clause_ref, m.proposed_name, m.self_ref) for m in notifications] == [
        ("hi.p1", "01/2026-" + HINDI_CENTRAL_TAX, True)
    ]
    assert ("hi.p1", "GSTR-3B") in [(m.clause_ref, m.proposed_name) for m in found]


@pytest.mark.parametrize("file_name", sorted(RECORDED_NOTIFICATIONS.values()))
def test_every_recorded_mention_is_its_span_and_its_name_is_canonical(file_name: str) -> None:
    doc = recorded(file_name)
    texts = {clause.clause_ref: clause.text for clause in doc.clauses}
    for mention in mentions_for(doc, own_ref=""):
        assert texts[mention.clause_ref][mention.span_start : mention.span_end] == mention.text
        if mention.proposed_name:
            assert normalise_name(mention.entity_type, mention.proposed_name) == (
                mention.proposed_name
            )
        before = texts[mention.clause_ref][max(0, mention.span_start - 12) : mention.span_start]
        assert not GAZETTE_PART.search(before), "a gazette header's section is not a mention"


def test_the_recorded_amendment_names_what_it_amends() -> None:
    doc = recorded("gst-ct-10-2025.pdf")
    found = [
        (m.entity_type, m.proposed_name, m.self_ref)
        for m in mentions_for(doc, own_ref="10/2025-Central Tax")
        if m.entity_type in {N, S}
    ]
    assert found == [
        (N, "10/2025-central tax", True),
        (S, "3", False),
        (S, "5@cgst-act", False),
        (S, "3@igst-act", False),
        (N, "02/2017-central tax", False),
        (N, "02/2017-central tax", False),
        (N, "27/2024-central tax", False),
    ]


# ---------------------------------------------------------------- notifications and circulars


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Notification No. 17/2026-Central Tax", "17/2026-central tax"),
        ("NOTIFICATION No. 01/2026 \u2013 CENTRAL TAX", "01/2026-central tax"),
        ("notification No.27/2024-Central Tax", "27/2024-central tax"),
        ("number 27/2022 - Central Tax", "27/2022-central tax"),
        ("vide 13/2017-CT dated", "13/2017-central tax"),
        ("No. 11/2017-Central Tax (Rate)", "11/2017-central tax (rate)"),
        ("Notfn. No. 05/2019-IT", "05/2019-integrated tax"),
        ("01/2026 - Union Territory Tax", "01/2026-union territory tax"),
    ],
)
def test_notification_numbers(text: str, expected: str) -> None:
    assert names(text) == [(N, expected)]


@pytest.mark.parametrize(
    "text",
    ["Notification No. 17/2026", "[F. No. CBIC-20006/45/2025-GST]", "dated 26/12/2022"],
)
def test_a_number_without_its_series_is_not_a_notification(text: str) -> None:
    assert names(text) == []


def test_own_notification_is_flagged_however_it_is_padded() -> None:
    found = find_mentions("Notification No. 1/2026-Central Tax", own_ref="01/2026-Central Tax")
    assert [m.self_ref for m in found] == [True]
    other = find_mentions("Notification No. 02/2026-Central Tax", own_ref="01/2026-Central Tax")
    assert [m.self_ref for m in other] == [False]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Circular No. 256/02/2026-GST", "256/02/2026-gst"),
        ("circular no 123/42/2019 \u2013 CGST", "123/42/2019-cgst"),
        ("Circular 45/19/2018", "45/19/2018"),
    ],
)
def test_circular_numbers(text: str, expected: str) -> None:
    assert names(text) == [(EntityType.CIRCULAR, expected)]


def test_own_circular_is_flagged() -> None:
    found = find_mentions("Circular No. 256/02/2026-GST", own_ref="256/02/2026-GST")
    assert [m.self_ref for m in found] == [True]


# ---------------------------------------------------------------- sections and rules

CGST_ACT = "of the Central Goods and Services Tax Act, 2017"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"sub -section (6) of section 39 {CGST_ACT}", [(S, "39(6)@cgst-act")]),
        (f"clause (c) of sub-section (2) of section 16 {CGST_ACT}", [(S, "16(2)(c)@cgst-act")]),
        (f"section 16 (2) (c) {CGST_ACT}", [(S, "16(2)(c)@cgst-act")]),
        (f"section 168 {CGST_ACT}", [(S, "168@cgst-act")]),
        (
            "section 5 of the Integrated Goods and Services Tax Act, 2017",
            [(S, "5@igst-act")],
        ),
        (f"section 39 read with section 168 {CGST_ACT}", [(S, "39@cgst-act"), (S, "168@cgst-act")]),
        ("section 10 of the Finance Act, 2025", [(S, "10")]),
    ],
)
def test_sections_and_their_statute(text: str, expected: list[tuple[EntityType, str]]) -> None:
    assert names(text) == expected


def test_a_clause_naming_two_acts_leaves_an_unqualified_section_for_review() -> None:
    text = (
        f"section 3 read with section 5 {CGST_ACT} and section 3 of the Integrated Goods and "
        "Services Tax Act, 2017"
    )
    assert names(text, default_act=Instrument.CGST_ACT) == [
        (S, "3"),
        (S, "5@cgst-act"),
        (S, "3@igst-act"),
    ]


def test_a_clause_naming_no_act_takes_the_documents_own() -> None:
    assert names("(i) sub-section (1) of section 39", default_act=Instrument.CGST_ACT) == [
        (S, "39(1)@cgst-act")
    ]
    assert names("(i) sub-section (1) of section 39") == [(S, "39(1)")]
    assert names("section 20", default_act=Instrument.IGST_ACT) == [(S, "20@igst-act")]


def test_the_gazette_header_is_not_a_section() -> None:
    header = (
        "[TO BE PUBLISHED IN THE GAZETTE OF INDIA, EXTRAORDINARY, PART II, SECTION 3, "
        "SUB- SECTION (i)]"
    )
    assert names(header, default_act=Instrument.CGST_ACT) == []
    assert names("in Part II, Section 3, Sub-section (i)") == []


@pytest.mark.parametrize(
    ("text", "default_act", "expected"),
    [
        (
            "clause (i) of sub -rule (1) of  rule 61 of the Central Goods and Services Tax Rules",
            None,
            [(R, "61(1)(i)@cgst-rules")],
        ),
        ("sub -rule (4B) of rule 8", Instrument.CGST_ACT, [(R, "8(4B)@cgst-rules")]),
        ("rule 36 (4)", Instrument.CGST_ACT, [(R, "36(4)@cgst-rules")]),
        ("rule 36 (4)", Instrument.IGST_ACT, [(R, "36(4)")]),
        ("rule 36(4)", None, [(R, "36(4)")]),
    ],
)
def test_rules_and_their_statute(
    text: str, default_act: Instrument | None, expected: list[tuple[EntityType, str]]
) -> None:
    assert names(text, default_act=default_act) == expected


# ---------------------------------------------------------------- forms, codes, rates, amounts


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("furnishing the return in FORM GSTR-3B for", "GSTR-3B"),
        ("FORM GSTR\u20133B", "GSTR-3B"),
        ("in GSTR 1 and", "GSTR-1"),
        ("challan in FORM GST PMT-06", "GST-PMT-06"),
        ("FORM GST DRC-03", "GST-DRC-03"),
        ("ITC-04 for the half year", "ITC-04"),
        ("statement in FORM CMP-08", "CMP-08"),
        ("GSTR-9C", "GSTR-9C"),
    ],
)
def test_forms(text: str, expected: str) -> None:
    assert names(text) == [(F, expected)]


@pytest.mark.parametrize("text", ["gstr-3b in lower case", "GSTR-3BX", "the FORM of the return"])
def test_not_forms(text: str) -> None:
    assert names(text) == []


def test_codes_need_their_keyword() -> None:
    assert names("goods of HSN 8471 90 and heading 8517") == [
        (EntityType.HSN_CODE, "847190"),
        (EntityType.HSN_CODE, "8517"),
    ]
    assert names("services under SAC 998313") == [(EntityType.SAC_CODE, "998313")]
    assert names("in 8471 cases dated 2017") == []
    assert names("HSN 84719") == []


def test_rates_need_a_tax_word_nearby() -> None:
    assert names("central tax at the rate of 9 per cent and 2.5%") == [
        (EntityType.TAX_RATE, "9%"),
        (EntityType.TAX_RATE, "2.5%"),
    ]
    assert names("attendance was 90% this year") == []


def test_amounts_need_a_threshold_word_nearby() -> None:
    assert names("whose aggregate turnover exceeds Rs. 5,00,00,000 in the year") == [
        (EntityType.THRESHOLD, "50000000")
    ]
    assert names("turnover up to Rs. 2 crore") == [(EntityType.THRESHOLD, "20000000")]
    assert names("a fee of Rs. 500 for each day") == []
    assert names("turnover is up to two crore rupees") == []


# ---------------------------------------------------------------- states


def test_state_names() -> None:
    assert names("in the state of Rajasthan and the State of Tamil Nadu") == [
        (EntityType.STATE, "rajasthan"),
        (EntityType.STATE, "tamil nadu"),
    ]
    assert names("Dadra and Nagar Haveli and Daman and Diu") == [
        (EntityType.STATE, "dadra and nagar haveli and daman and diu")
    ]
    assert names("New Delhi, the 18 October, 2025") == []
    assert names("the National Capital Territory of Delhi") == [(EntityType.STATE, "delhi")]
    assert len(STATE_NAMES) == 37


# ---------------------------------------------------------------- properties


def test_overlapping_matches_keep_the_longest() -> None:
    found = find_mentions(f"sub-section (1) of section 39 {CGST_ACT}")
    assert [(m.text, m.proposed_name) for m in found] == [
        ("sub-section (1) of section 39", "39(1)@cgst-act")
    ]


PIECES = [
    *"0123456789/-() .,",
    "\u2013",
    "Rs. ",
    "section ",
    "rule ",
    "sub-",
    "of the ",
    "Central Tax",
    "FORM ",
    "GSTR",
    "turnover ",
    "Circular ",
    "Notification No. ",
    "Central Goods and Services Tax Act",
    "Tamil Nadu",
    " rate ",
    "%",
    "HSN ",
]
TEXT = st.lists(st.sampled_from(PIECES), max_size=40).map("".join)


@settings(max_examples=500, deadline=None)
@given(TEXT)
def test_every_match_is_its_span_in_order_without_overlap(text: str) -> None:
    found: tuple[GrammarMatch, ...] = find_mentions(text, default_act=Instrument.CGST_ACT)
    for match in found:
        assert text[match.span_start : match.span_end] == match.text
        assert match.span_end > match.span_start
    for earlier, later in itertools.pairwise(found):
        assert earlier.span_end <= later.span_start


@pytest.mark.parametrize(
    "text",
    [
        "turnover exceeding Rs 2 crore 50 lakh in a year",
        "turnover exceeding Rs. 2 crore and 50 lakh",
    ],
)
def test_a_compound_amount_is_read_whole_and_left_for_review(text: str) -> None:
    (match,) = find_mentions(text)
    assert match.entity_type is EntityType.THRESHOLD
    assert "50 lakh" in match.text
    assert match.proposed_name == ""


def test_rupees_before_a_scaled_amount() -> None:
    assert names("turnover of Rupees 20 lakh") == [(EntityType.THRESHOLD, "2000000")]


def test_a_look_alike_series_is_not_a_notification() -> None:
    assert names("Notification No. 5/2019-\u0131t dated") == []
    found = find_mentions("x", own_ref="5/2019-\u0131t")
    assert found == ()
