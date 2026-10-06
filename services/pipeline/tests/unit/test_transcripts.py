"""An analyst's transcript: its shape is checked, every problem named by its place, and it
parses as manual@1 the way a parser's blocks do."""

import hashlib
import json
from typing import Any

import pytest

from domain_kernel.documents import DocumentType, document_id_for
from pipeline.domain.errors import TranscriptInvalidError
from pipeline.domain.structure import Heading, Paragraph, Table
from pipeline.domain.transcripts import (
    MAX_BLOCKS,
    TRANSCRIPT_PARSER,
    Transcript,
    decode_transcript,
    read_transcript,
    transcribed,
)

TRANSCRIPT: dict[str, Any] = {
    "title": "Example notification",
    "blocks": [
        {"type": "heading", "text": "Example heading", "page": 1},
        {"type": "paragraph", "number": "1.", "text": "Example text of the first paragraph."},
        {"type": "paragraph", "text": "Example text without a number.", "page": 2},
        {
            "type": "table",
            "header": ["S. No.", "Item"],
            "rows": [["1", "Example item"], ["2", "Another example item"]],
            "page": 2,
        },
    ],
}
DIGEST = hashlib.sha256(b"%PDF-1.7 an example scan").hexdigest()


def problems(data: object) -> str:
    with pytest.raises(TranscriptInvalidError) as caught:
        read_transcript(data)
    return str(caught.value)


def test_a_transcript_reads_into_blocks() -> None:
    transcript = read_transcript(TRANSCRIPT)
    assert transcript == Transcript(
        blocks=(
            Heading("Example heading", page=1),
            Paragraph("Example text of the first paragraph.", number="1."),
            Paragraph("Example text without a number.", page=2),
            Table(
                header=("S. No.", "Item"),
                rows=(("1", "Example item"), ("2", "Another example item")),
                page=2,
            ),
        ),
        title="Example notification",
    )


def test_it_parses_as_manual_with_the_parsers_refs() -> None:
    parsed = transcribed(
        read_transcript(TRANSCRIPT),
        document_id=document_id_for(DIGEST),
        doc_type=DocumentType.STATUTE,
    )
    assert parsed.parser_version == TRANSCRIPT_PARSER == "manual@1"
    assert parsed.document_id == document_id_for(DIGEST)
    assert parsed.doc_type is DocumentType.STATUTE
    assert (parsed.title, parsed.language) == ("Example notification", "en")
    assert [(c.clause_ref, c.text, c.page) for c in parsed.clauses] == [
        ("en.p1", "Example heading", 1),
        ("en.p2", "1. Example text of the first paragraph.", None),
        ("en.p3", "Example text without a number.", 2),
        ("en.p4", "S. No. | Item", 2),
        ("en.p5", "1 | Example item", 2),
        ("en.p6", "2 | Another example item", 2),
    ]


def test_a_bilingual_transcript_is_mul_and_the_title_falls_back() -> None:
    data = {
        "blocks": [
            {"type": "paragraph", "text": "उदाहरण पाठ"},
            {"type": "heading", "text": "Example"},
        ]
    }
    parsed = transcribed(
        read_transcript(data), document_id=document_id_for(DIGEST), doc_type=DocumentType.STATUTE
    )
    assert parsed.language == "mul"
    assert parsed.title == "उदाहरण पाठ"
    assert [c.clause_ref for c in parsed.clauses] == ["hi.p1", "en.p1"]


def test_the_encoded_form_is_canonical_and_reads_back() -> None:
    transcript = read_transcript(TRANSCRIPT)
    encoded = transcript.encoded()
    assert encoded == read_transcript(json.loads(encoded)).encoded()
    assert decode_transcript(encoded) == transcript
    assert b" " not in encoded.replace(b"Example", b"").split(b'"blocks"')[0]
    assert json.loads(encoded)["blocks"][1] == {
        "number": "1.",
        "text": "Example text of the first paragraph.",
        "type": "paragraph",
    }


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ([], "a transcript is an object with blocks"),
        ({}, "blocks must be a list of at least one block"),
        ({"blocks": []}, "blocks must be a list of at least one block"),
        ({"blocks": [], "extra": 1}, "keys it does not take: extra"),
        ({"blocks": ["text"]}, "blocks[0] must be an object"),
        ({"blocks": [{"type": "list"}]}, "blocks[0].type must be heading, paragraph or table"),
        ({"blocks": [{"type": "heading", "text": " "}]}, "blocks[0].text must not be empty"),
        ({"blocks": [{"type": "heading", "text": 3}]}, "blocks[0].text must be text"),
        (
            {"blocks": [{"type": "heading", "text": "x", "rows": []}]},
            "blocks[0] has keys a heading does not take: rows",
        ),
        ({"blocks": [{"type": "heading", "text": "x", "page": 0}]}, "blocks[0].page must be"),
        ({"blocks": [{"type": "heading", "text": "x", "page": True}]}, "blocks[0].page must be"),
        (
            {"blocks": [{"type": "paragraph", "text": "x", "number": "1" * 21}]},
            "blocks[0].number must be at most 20 characters",
        ),
        ({"blocks": [{"type": "table", "rows": []}]}, "blocks[0].rows must be a list of at least"),
        ({"blocks": [{"type": "table", "rows": [[]]}]}, "blocks[0].rows[0] must be a list of"),
        ({"blocks": [{"type": "table", "rows": [["", " "]]}]}, "blocks[0].rows[0] has no text"),
        (
            {"blocks": [{"type": "table", "rows": [["x"]], "header": "S. No."}]},
            "blocks[0].header must be a list of at least one cell",
        ),
        ({"blocks": [{"type": "table", "rows": [["x", 1]]}]}, "blocks[0].rows[0][1] must be text"),
        ({"title": 5, "blocks": [{"type": "heading", "text": "x"}]}, "title must be text"),
    ],
)
def test_every_problem_is_named_by_its_place(data: object, expected: str) -> None:
    assert expected in problems(data)


def test_all_problems_are_named_at_once_up_to_a_limit() -> None:
    message = problems({"blocks": [{"type": "heading", "text": ""} for _ in range(25)]})
    assert message.count("must not be empty") == 20
    assert message.endswith("and 5 more")


def test_clauses_beyond_the_rulebooks_limits_are_refused() -> None:
    rows = [[str(n), "Example item"] for n in range(MAX_BLOCKS + 1)]
    assert "2001 clauses; the rulebook takes at most 2000" in problems(
        {"blocks": [{"type": "table", "rows": rows}]}
    )
    too_many = [{"type": "heading", "text": "x"}] * (MAX_BLOCKS + 1)
    assert "2001 blocks; at most 2000" in problems({"blocks": too_many})
    long = {"blocks": [{"type": "paragraph", "text": "x" * 50_001}]}
    assert "en.p1 has 50001 characters" in problems(long)


def test_bytes_that_are_not_json_are_refused() -> None:
    with pytest.raises(TranscriptInvalidError, match="not JSON"):
        decode_transcript(b"\xff not json")
