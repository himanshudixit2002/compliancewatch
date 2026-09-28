from uuid import UUID

import pytest

from domain_kernel.documents import Clause, DocumentType, ParsedDocument
from domain_kernel.ids import DocumentId
from pipeline.application.detector import ChangeKind, detect


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
    ],
)
def test_references_are_canonical_and_unique(text: str, expected: tuple[str, ...]) -> None:
    assert detect(doc("Notification", text)).references == expected
