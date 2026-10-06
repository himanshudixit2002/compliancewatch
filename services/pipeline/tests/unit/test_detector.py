from uuid import UUID

import pytest

from domain_kernel.documents import Clause, DocumentType, ParsedDocument
from domain_kernel.ids import DocumentId
from pipeline.application.detector import ChangeKind, detect, opening_of
from pipeline.domain.classification import Relevance, TypeConfidence


def doc(
    title: str, *paragraphs: str, doc_type: DocumentType = DocumentType.NOTIFICATION
) -> ParsedDocument:
    clauses = tuple(Clause(f"en.p{i}", text) for i, text in enumerate([title, *paragraphs], 1))
    return ParsedDocument(DocumentId(UUID(int=7)), doc_type, title, clauses)


def test_a_plain_notification_has_no_change() -> None:
    detection = detect(
        doc(
            "Notification No. 01/2026 - Central Tax",
            "In exercise of the powers conferred by section 128 of the Central Goods and Services "
            "Tax Act, 2017, the Government waives the late fee.",
        )
    )
    assert detection.doc_type is DocumentType.NOTIFICATION
    assert detection.change_kind is ChangeKind.NONE
    assert detection.references == ()
    assert not detection.announced_not_in_force


def test_a_corrigendum_names_the_notification_it_corrects() -> None:
    detection = detect(
        doc(
            "Corrigendum to Notification No. 12/2024 - Central Tax",
            "In the notification of the Government of India No. 12/2024 - Central Tax, dated the "
            "10th July 2024, for the words 'five crore' read 'two crore'.",
        )
    )
    assert detection.change_kind is ChangeKind.CORRIGENDUM
    assert detection.references == ("12/2024-central tax",)


def test_extension_of_a_due_date_and_rescission_are_told_apart() -> None:
    extension = detect(
        doc(
            "Seeks to extend the due date for furnishing FORM GSTR-3B for September 2026",
            "the Commissioner hereby extends the due date for furnishing the return under "
            "section 39",
        )
    )
    assert extension.change_kind is ChangeKind.EXTENSION
    withdrawal = detect(
        doc(
            "Seeks to rescind Notification No. 30/2021 - Central Tax",
            "the Central Government hereby rescinds the notification No. 30/2021 - Central Tax",
        )
    )
    assert withdrawal.change_kind is ChangeKind.WITHDRAWAL
    assert withdrawal.references == ("30/2021-central tax",)


def test_amendment_is_the_fallback_change_kind() -> None:
    detection = detect(
        doc(
            "Seeks to amend Notification No. 83/2020 - Central Tax",
            "the following amendments are made in the said notification",
        )
    )
    assert detection.change_kind is ChangeKind.AMENDMENT
    assert detection.references == ("83/2020-central tax",)


def test_a_press_release_is_announced_not_in_force() -> None:
    detection = detect(
        doc(
            "Recommendations of the 56th Meeting of the GST Council held at New Delhi",
            "The Council recommended reducing the rate on ...",
            doc_type=DocumentType.PRESS_RELEASE,
        ),
        default_type=DocumentType.PRESS_RELEASE,
    )
    assert detection.doc_type is DocumentType.PRESS_RELEASE
    assert detection.announced_not_in_force


def test_circulars_and_advisories_and_user_manuals_are_flagged() -> None:
    circular = detect(
        doc(
            "Circular No. 256/02/2026-GST",
            "Clarification regarding filing of appeal",
            doc_type=DocumentType.CIRCULAR,
        )
    )
    assert circular.doc_type is DocumentType.CIRCULAR
    advisory = detect(
        doc(
            "Advisory on use of version 3.3 of emSigner",
            "This is an advance information",
            doc_type=DocumentType.PRESS_RELEASE,
        )
    )
    assert advisory.is_advisory
    manual = detect(doc("Reset Password User Manual", "Step 1", doc_type=DocumentType.NOTIFICATION))
    assert manual.is_user_manual


def test_own_number_from_the_listing_is_not_a_reference() -> None:
    gazette = doc(
        "[To be published in the Gazette of India]",
        "Notification No. 01/2026 - Central Tax",
        "the Commissioner extends the due date for furnishing FORM GSTR-3B, as required under "
        "notification No. 83/2020 - Central Tax",
    )
    assert detect(gazette).references == ("01/2026-central tax", "83/2020-central tax")
    assert detect(gazette, own_ref="01/2026-Central Tax").references == ("83/2020-central tax",)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "as amended by Circular No. 123/42/2019-GST and notification 14/2022-Central Tax",
            ("123/42/2019-gst", "14/2022-central tax"),
        ),
        ("read with notification No. 5/2017 - Central Tax (Rate)", ("5/2017-central tax (rate)",)),
        ("nothing to see", ()),
        (
            "hereby rescinds notification No. 27/2022 \u2013 Central Tax and Circular No. "
            "123/42/2019 \u2013 GST",
            ("123/42/2019-gst", "27/2022-central tax"),
        ),
    ],
)
def test_references_are_canonical_and_unique(text: str, expected: tuple[str, ...]) -> None:
    assert detect(doc("Notification", text)).references == expected


def test_the_type_its_opening_names_is_certain() -> None:
    detection = detect(doc("Notification No. 01/2026 - Central Tax", "the Commissioner extends"))
    assert (detection.doc_type, detection.confidence) == (
        DocumentType.NOTIFICATION,
        TypeConfidence.CERTAIN,
    )
    assert detection.reasons[0] == (
        "its opening names it a notification, the type its source publishes"
    )


def test_an_opening_that_names_no_type_takes_its_sources() -> None:
    detection = detect(
        doc("Advisory on use of version 3.3 of emSigner", "This is an advance information"),
        default_type=DocumentType.PRESS_RELEASE,
    )
    assert (detection.doc_type, detection.confidence) == (
        DocumentType.PRESS_RELEASE,
        TypeConfidence.DEFAULT,
    )
    assert "taken as its source's: press release" in detection.reasons[0]


def test_another_type_than_its_source_publishes_is_a_conflict() -> None:
    detection = detect(
        doc(
            "Circular No. 256/02/2026-GST",
            "Subject: Clarification on Notification No. 12/2024 - Central Tax",
        ),
        default_type=DocumentType.NOTIFICATION,
    )
    assert (detection.doc_type, detection.confidence) == (
        DocumentType.CIRCULAR,
        TypeConfidence.CONFLICT,
    )
    assert detection.reasons[0] == (
        "its opening names it a circular, but its source publishes the type notification"
    )


def test_the_council_a_notification_quotes_does_not_make_it_a_press_release() -> None:
    detection = detect(
        doc(
            "Notification No. 9/2025 - Central Tax (Rate)",
            "In exercise of the powers conferred by section 9, the Central Government, on the "
            "recommendations of the Council, hereby notifies",
        )
    )
    assert (detection.doc_type, detection.confidence) == (
        DocumentType.NOTIFICATION,
        TypeConfidence.CERTAIN,
    )
    press = detect(
        doc("Press release", "Recommendations of the 56th meeting of the GST Council"),
        default_type=DocumentType.NOTIFICATION,
    )
    assert (press.doc_type, press.confidence) == (
        DocumentType.PRESS_RELEASE,
        TypeConfidence.CONFLICT,
    )


def test_the_first_type_the_opening_names_wins() -> None:
    circular = detect(
        doc("Circular No. 123/42/2019-GST", "as amended by notification No. 14/2022"),
        default_type=DocumentType.CIRCULAR,
    )
    assert (circular.doc_type, circular.confidence) == (
        DocumentType.CIRCULAR,
        TypeConfidence.CERTAIN,
    )


def test_a_title_the_first_clause_starts_with_is_read_once() -> None:
    heading = "[To be published in the Gazette of India] Government of India " * 3
    first = f"{heading}Ministry of Finance Notification No. 01/2026 - Central Tax"
    gazette = ParsedDocument(
        DocumentId(UUID(int=7)),
        DocumentType.NOTIFICATION,
        heading[:150],
        (Clause("en.p1", first), Clause("en.p2", "In exercise of the powers")),
    )
    assert opening_of(gazette).count("Gazette of India") == 3
    assert detect(gazette).confidence is TypeConfidence.CERTAIN


def test_a_type_a_person_gave_or_a_statute_source_is_certain_whatever_the_text_names() -> None:
    uploaded = detect(
        doc("Notification No. 3/2017 - Central Tax", "the Central Goods and Services Tax Rules"),
        given_type=DocumentType.STATUTE,
    )
    assert (uploaded.doc_type, uploaded.confidence, uploaded.relevance) == (
        DocumentType.STATUTE,
        TypeConfidence.CERTAIN,
        Relevance.RELEVANT,
    )
    assert uploaded.reasons == (
        "a person gave its type: statute",
        "a person placed it as a statute",
    )
    rules = detect(
        doc("Rule 61. Form and manner of furnishing of return", "substituted vide notification"),
        default_type=DocumentType.STATUTE,
    )
    assert (rules.doc_type, rules.confidence, rules.relevance) == (
        DocumentType.STATUTE,
        TypeConfidence.CERTAIN,
        Relevance.RELEVANT,
    )


def test_the_listed_title_decides_the_relevance_but_never_the_type() -> None:
    manual = detect(
        doc("Login to the portal and open the returns dashboard", "Example text."),
        listed_title="User Manual for filing FORM GSTR-1 on the portal",
    )
    assert (manual.relevance, manual.is_user_manual) == (Relevance.IRRELEVANT, True)
    circular = detect(
        doc("Circular No. 5/2026-GST", "Subject: Example clarification for the tests."),
        default_type=DocumentType.CIRCULAR,
        listed_title="Clarification on the applicability of notification No. 12/2017-Central Tax",
    )
    assert (circular.doc_type, circular.confidence, circular.relevance) == (
        DocumentType.CIRCULAR,
        TypeConfidence.CERTAIN,
        Relevance.RELEVANT,
    ), "the type is what the circular's own opening names, not the notification its listing names"


@pytest.mark.parametrize(
    ("title", "relevance"),
    [
        ("Reset Password User Manual", Relevance.IRRELEVANT),
        ("How to file an appeal on the portal", Relevance.IRRELEVANT),
        ("Step-by-step guide to the new invoice management system", Relevance.IRRELEVANT),
        ("FAQs on the decisions of the 56th GST Council", Relevance.RELEVANT),
        ("Notification No. 01/2026 - Central Tax", Relevance.RELEVANT),
    ],
)
def test_a_portal_manual_is_irrelevant_and_an_faq_is_not(title: str, relevance: Relevance) -> None:
    detection = detect(doc(title, "Step 1"))
    assert detection.relevance is relevance
    assert len(detection.reasons) == 2
    if relevance is Relevance.IRRELEVANT:
        assert "user manual or a how-to guide" in detection.reasons[1]
