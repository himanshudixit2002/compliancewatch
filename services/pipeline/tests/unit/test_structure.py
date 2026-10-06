"""Blocks into clauses: the one rendering the table-aware parsers and transcripts share."""

import pytest

from domain_kernel.documents import Clause
from domain_kernel.errors import InvariantViolationError
from pipeline.domain.structure import (
    MAX_CLAUSES,
    Block,
    Heading,
    Paragraph,
    Table,
    block_texts,
    clauses_of,
    limit_problems,
    row_text,
)


def test_each_block_becomes_its_clauses_in_order() -> None:
    clauses = clauses_of(
        [
            Heading("Example   heading", page=1),
            Paragraph("Example text\nof the first paragraph.", number="1.", page=1),
            Table(
                header=("S. No.", "Item", "Rate"),
                rows=(("1", "Example item", "5%"), ("2", "", "12%")),
                page=2,
            ),
            Paragraph("Unnumbered example paragraph."),
        ]
    )
    assert [(c.clause_ref, c.text, c.page) for c in clauses] == [
        ("en.p1", "Example heading", 1),
        ("en.p2", "1. Example text of the first paragraph.", 1),
        ("en.p3", "S. No. | Item | Rate", 2),
        ("en.p4", "1 | Example item | 5%", 2),
        ("en.p5", "2 |  | 12%", 2),
        ("en.p6", "Unnumbered example paragraph.", None),
    ]


def test_refs_count_per_language_and_empty_text_makes_no_clause() -> None:
    clauses = clauses_of(
        [
            Paragraph("उदाहरण पाठ"),
            Paragraph("Example text"),
            Paragraph("   "),
            Table(rows=(("", " "), ("उदाहरण", "पंक्ति"))),
            Heading("Example"),
        ]
    )
    assert [c.clause_ref for c in clauses] == ["hi.p1", "en.p1", "hi.p2", "en.p2"]
    assert clauses[2].text == "उदाहरण | पंक्ति"


def test_the_same_blocks_always_give_the_same_clauses() -> None:
    blocks: list[Block] = [Heading("Example"), Table(rows=(("1", "Example item"),))]
    assert clauses_of(blocks) == clauses_of(list(blocks))


def test_a_row_keeps_its_inner_empty_cells_and_drops_trailing_ones() -> None:
    assert row_text(["1", "", "5%"]) == "1 |  | 5%"
    assert row_text(["1", "Example", "", " "]) == "1 | Example"
    assert row_text(["", ""]) == ""
    assert list(block_texts(Table(rows=(("a",),), header=("Only",)))) == ["Only", "a"]


def test_blocks_check_their_fields() -> None:
    with pytest.raises(InvariantViolationError, match="page"):
        Heading("Example", page=0)
    with pytest.raises(InvariantViolationError):
        Table(rows=(("1", 2),))  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError):
        Paragraph("Example", number=None)  # type: ignore[arg-type]


def test_limit_problems_name_what_the_rulebook_would_refuse() -> None:
    fine = clauses_of([Paragraph("Example")])
    assert limit_problems(fine) == []
    many = tuple(Clause(f"en.p{n}", "x") for n in range(1, MAX_CLAUSES + 2))
    assert limit_problems(many) == [f"{MAX_CLAUSES + 1} clauses; the rulebook takes at most 2000"]
    long = (Clause("en.p1", "x" * 50_001),)
    assert limit_problems(long) == ["en.p1 has 50001 characters; at most 50000"]
