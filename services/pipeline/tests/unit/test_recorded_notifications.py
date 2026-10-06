"""The recorded CBIC notifications replay through the adapter and the PDF parser.

What is asserted here is what the parser and the detector make of the recorded text, not a
reading of the law: the numbers each notification names come from its own title and first
clauses. The fixtures are the site's answers as recorded with ``pipeline-label prepare
--record`` on 2026-09-28.
"""

import re
from pathlib import Path

import pytest

from domain_kernel.documents import DocumentRef, DocumentType, clause_id_for, document_id_for
from domain_kernel.protocols import SourceAdapter
from pipeline.application.detector import ChangeKind, detect
from pipeline.domain.classification import Relevance, TypeConfidence
from pipeline.infrastructure.adapters import SOURCES, build_adapter
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.parsers import PdfParser
from pipeline.testing import CBIC_PDF, RECORDED_NOTIFICATIONS, recorded_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CLAUSE_REF = r"^(?:[a-z]{2,3}\.)?p[1-9][0-9]{0,3}$"

DETECTED = {
    "01/2026-Central Tax": (ChangeKind.EXTENSION, ()),
    "17/2025-Central Tax": (ChangeKind.EXTENSION, ()),
    "15/2025-Central Tax": (ChangeKind.NONE, ()),
    "10/2025-Central Tax": (ChangeKind.AMENDMENT, ("02/2017-central tax",)),
    "13/2024-Central Tax": (ChangeKind.WITHDRAWAL, ("27/2022-central tax",)),
}


@pytest.fixture(scope="module")
def adapter() -> SourceAdapter:
    client = PoliteClient(
        ClientConfig(min_delay_seconds=0, respect_robots=False),
        transport=recorded_sources(FIXTURES),
        sleep=lambda _: None,
    )
    return build_adapter("cbic_notifications", client)


def test_five_notifications_are_recorded() -> None:
    assert len(RECORDED_NOTIFICATIONS) == 5
    assert set(DETECTED) == set(RECORDED_NOTIFICATIONS)


@pytest.mark.parametrize(("number", "file_name"), sorted(RECORDED_NOTIFICATIONS.items()))
def test_a_recorded_notification_replays_and_parses(
    adapter: SourceAdapter, number: str, file_name: str
) -> None:
    source_id = SOURCES["cbic_notifications"].source_id
    raw = adapter.fetch(DocumentRef(source_id, CBIC_PDF + file_name, external_ref=number))
    parsed = PdfParser().parse(raw)
    assert parsed.parser_version == "pdf@1"
    assert parsed.language == "en"
    assert parsed.doc_type is DocumentType.NOTIFICATION
    assert parsed.document_id == document_id_for(raw.sha256)
    refs = [clause.clause_ref for clause in parsed.clauses]
    assert all(re.fullmatch(CLAUSE_REF, ref) for ref in refs)
    assert len({clause_id_for(parsed.document_id, ref) for ref in refs}) == len(refs)
    own = number.split("-")[0]
    assert own in " ".join(clause.text for clause in parsed.clauses[:4])

    detection = detect(parsed, default_type=DocumentType.NOTIFICATION, own_ref=number)
    change_kind, references = DETECTED[number]
    assert detection.change_kind is change_kind
    assert detection.references == references
    assert (detection.doc_type, detection.confidence, detection.relevance) == (
        DocumentType.NOTIFICATION,
        TypeConfidence.CERTAIN,
        Relevance.RELEVANT,
    ), "each names itself a notification under its gazette heading"
