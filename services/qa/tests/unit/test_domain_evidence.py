"""The evidence bundle: labels, de-duplication, caps and the rendered prompt text."""

from uuid import UUID

from domain_kernel.ids import ClauseId, DocumentId
from qa.domain.evidence import (
    MAX_CLAUSES,
    MAX_FACTS,
    MAX_RENDERED_CHARS,
    BundleBuilder,
    render_bundle,
)

DOCUMENT = DocumentId(UUID(int=1))


def clause_id(number: int) -> ClauseId:
    return ClauseId(UUID(int=1000 + number))


def add(builder: BundleBuilder, number: int, text: str = "text", step: str = "s1") -> str | None:
    return builder.add_clause(
        clause_id=clause_id(number),
        document_id=DOCUMENT,
        clause_ref=f"en.p{number}",
        text=text,
        step_id=step,
        source="01/2026-Central Tax",
    )


def test_clauses_are_labelled_in_order_and_kept_once() -> None:
    builder = BundleBuilder()
    assert add(builder, 1) == "C1"
    assert add(builder, 2, step="s2") == "C2"
    assert add(builder, 1, step="s3") == "C1"
    bundle = builder.build()
    assert bundle.labels == ("C1", "C2")
    assert bundle.clauses[0].step_id == "s1"
    assert bundle.clause("C2") is not None
    assert bundle.clause("C9") is None
    assert not bundle.empty


def test_facts_are_labelled_and_an_empty_bundle_has_no_clause() -> None:
    builder = BundleBuilder()
    assert builder.add_fact("s1", "rule gstr3b_monthly version 1 is in force") == "F1"
    bundle = builder.build()
    assert bundle.empty
    assert [fact.label for fact in bundle.facts] == ["F1"]


def test_what_does_not_fit_is_counted() -> None:
    builder = BundleBuilder()
    for number in range(MAX_CLAUSES + 2):
        add(builder, number)
    for number in range(MAX_FACTS + 3):
        builder.add_fact("s1", f"fact {number}")
    bundle = builder.build()
    assert len(bundle.clauses) == MAX_CLAUSES
    assert len(bundle.facts) == MAX_FACTS
    assert (bundle.dropped_clauses, bundle.dropped_facts) == (2, 3)


def test_rendering_labels_clauses_cuts_long_text_and_lists_facts() -> None:
    builder = BundleBuilder()
    add(builder, 1, text="x" * (MAX_RENDERED_CHARS + 50))
    builder.add_clause(
        clause_id=clause_id(2),
        document_id=DOCUMENT,
        clause_ref="en.p2",
        text="short",
        step_id="s1",
    )
    builder.add_fact("s2", "the business is a monthly filer")
    rendered = render_bundle(builder.build())
    assert rendered.startswith("Clauses:\n[C1] en.p1 (01/2026-Central Tax)\n")
    assert "x" * MAX_RENDERED_CHARS + " [cut]" in rendered
    assert "[C2] en.p2\nshort" in rendered
    assert rendered.endswith("Facts:\nF1: the business is a monthly filer")
