import pytest

from domain_kernel.citations import Citation
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
