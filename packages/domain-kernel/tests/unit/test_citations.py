import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domain_kernel.citations import (
    MAX_QUOTE_CHARS,
    QUOTE_MATCH_THRESHOLD,
    Citation,
    evidence_tokens_missing,
    quote_match_ratio,
    quote_matches,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId


def test_citation_defaults() -> None:
    citation = Citation("3(1)", "Every registered person shall ...")
    assert citation.clause_ref == "3(1)"
    assert citation.verified is False
    assert citation.clause_id is None


def test_citation_keeps_the_quote_verbatim_and_links_the_clause() -> None:
    clause_id = ClauseId.new()
    citation = Citation("3(1)", "  two  spaces \n", verified=True, clause_id=clause_id)
    assert citation.quote == "  two  spaces \n"
    assert citation.verified is True
    assert citation.clause_id == clause_id
    assert hash(citation) == hash(Citation("3(1)", "  two  spaces \n", True, clause_id))


@pytest.mark.parametrize(
    ("clause_ref", "quote", "verified", "clause_id", "message"),
    [
        ("", "text", False, None, "clause_ref must not be blank"),
        ("  ", "text", False, None, "clause_ref must not be blank"),
        (" 3(1)", "text", False, None, "clause_ref must not have leading"),
        (3, "text", False, None, "clause_ref must be str"),
        ("3(1)", "", False, None, "quote must not be blank"),
        ("3(1)", " \n", False, None, "quote must not be blank"),
        ("3(1)", None, False, None, "quote must be str"),
        ("3(1)", "text", "yes", None, "verified must be bool"),
        ("3(1)", "text", 1, None, "verified must be bool"),
        ("3(1)", "text", False, "abc", "clause_id must be ClauseId"),
        ("3(1)", "text", False, DocumentId.new(), "clause_id must be ClauseId"),
    ],
)
def test_invalid_citations_are_rejected(
    clause_ref: object, quote: object, verified: object, clause_id: object, message: str
) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        Citation(clause_ref, quote, verified, clause_id)  # type: ignore[arg-type]


CLAUSE = (
    "In exercise of the powers conferred by sub -section (6) of section 39 of the Central Goods "
    "and Services Tax Act, 2017, the Government hereby extends the due date for furnishing the "
    "return in FORM GSTR-3B for the month of December, 2025 till the 23rd January, 2026."
)


def test_a_contained_quote_scores_one_after_folding() -> None:
    assert quote_match_ratio("sub-section (6) of section 39", CLAUSE) == 1.0
    assert quote_match_ratio("FORM GSTR\u20133B", CLAUSE) == 1.0
    assert quote_match_ratio("  HEREBY   extends the\nDUE date ", CLAUSE) == 1.0


def test_an_empty_quote_scores_zero() -> None:
    assert quote_match_ratio("", CLAUSE) == 0.0
    assert quote_match_ratio(" \n", CLAUSE) == 0.0


def test_a_near_quote_passes_and_an_unrelated_one_fails() -> None:
    near = "the Government hereby extend the due date for furnishing return in FORM GSTR-3B"
    assert QUOTE_MATCH_THRESHOLD <= quote_match_ratio(near, CLAUSE) < 1.0
    assert quote_matches(near, CLAUSE)
    unrelated = "the registered person shall pay interest at eighteen per cent per annum"
    assert quote_match_ratio(unrelated, CLAUSE) < QUOTE_MATCH_THRESHOLD
    assert not quote_matches(unrelated, CLAUSE)
    assert quote_match_ratio("zzzz", "aaaa") == 0.0


def test_a_wrong_fact_can_score_high_so_tokens_are_checked_too() -> None:
    wrong = (
        "extends the due date for furnishing the return in FORM GSTR-1 "
        "for the month of November, 2025"
    )
    assert quote_matches(wrong, CLAUSE)
    assert evidence_tokens_missing(wrong, CLAUSE) == ("gstr-1", "november")


def test_an_honest_quote_misses_no_tokens() -> None:
    honest = "FORM GSTR\u20133B for the month of December, 2025 till the 23rd January, 2026"
    assert evidence_tokens_missing(honest, CLAUSE) == ()


def test_missing_tokens_are_reported_once_in_quote_order() -> None:
    quote = "section 40 and section 40 in March, 2024"
    assert evidence_tokens_missing(quote, CLAUSE) == ("40", "march", "2024")


def test_the_threshold_can_be_raised() -> None:
    near = "the Government hereby extend the due date for furnishing return in FORM GSTR-3B"
    assert not quote_matches(near, CLAUSE, threshold=1.0)


@given(st.text(max_size=200), st.text(max_size=200))
@settings(max_examples=300, deadline=None)
def test_ratio_is_bounded(quote: str, text: str) -> None:
    assert 0.0 <= quote_match_ratio(quote, text) <= 1.0


@given(st.text(min_size=1, max_size=300), st.data())
@settings(max_examples=300, deadline=None)
def test_any_non_blank_slice_of_the_text_is_found(text: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(min_value=0, max_value=len(text) - 1))
    end = data.draw(st.integers(min_value=start + 1, max_value=len(text)))
    quote = text[start:end]
    if quote.strip() and len(" ".join(quote.split())) <= MAX_QUOTE_CHARS:
        assert quote_match_ratio(quote, text) >= QUOTE_MATCH_THRESHOLD
