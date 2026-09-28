import base64
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml

from domain_kernel.documents import (
    DiscoveredDocument,
    DocumentRef,
    DocumentType,
    RawDocument,
    document_id_for,
)
from pipeline.infrastructure.adapters import SOURCES
from pipeline.infrastructure.fakes import FakeSourceAdapter
from pipeline.infrastructure.parsers import PdfParser
from pipeline.label import (
    LabelError,
    check_case,
    load_case,
    load_cases,
    main,
    prepare_case,
    read_index,
    slug,
    write_index,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = Path(__file__).resolve().parents[4] / "evals" / "golden" / "extraction"


def cbic_pdf() -> RawDocument:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-01-2026.pdf.json").read_text())
    spec = SOURCES["cbic_notifications"]
    ref = DocumentRef(
        spec.source_id, "https://taxinformation.cbic.gov.in/x.pdf", "01/2026-Central Tax"
    )
    return RawDocument.from_bytes(ref, base64.b64decode(wrapper["data"]), "application/pdf")


def test_slug() -> None:
    assert slug("01/2026-Central Tax") == "01-2026-central-tax"


def test_write_index_lists_documents_as_draft(tmp_path: Path) -> None:
    path = tmp_path / "index.yaml"
    count = write_index(
        FakeSourceAdapter.with_sample(),
        source_key="fake",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        limit=5,
        path=path,
    )
    index = read_index(path)
    assert count == 1
    assert index["documents"][0]["label_status"] == "draft"
    assert index["documents"][0]["case"] is None


def test_prepare_case_writes_clauses_and_the_detector_prefill(tmp_path: Path) -> None:
    raw = cbic_pdf()
    discovered = DiscoveredDocument(
        raw.ref, title="Seeks to extend", published_at=date(2026, 4, 21)
    )
    path = prepare_case(
        raw,
        discovered,
        [PdfParser()],
        source_key="cbic_notifications",
        default_type=DocumentType.NOTIFICATION,
        cases_dir=tmp_path / "cases",
    )
    data = yaml.safe_load(path.read_text())
    assert path.name == "01-2026-central-tax.yaml"
    assert data["label_status"] == "draft"
    assert data["expected"] is None
    assert data["detector"]["change_kind"] == "extension"
    assert data["document"]["clauses"][0]["ref"] == "en.p1"
    case = load_case(path)
    assert not case.is_labelled
    assert check_case(case) == []
    assert str(case.document.document_id) == str(document_id_for(raw.sha256))


def test_the_committed_golden_cases_check_clean() -> None:
    cases = load_cases(GOLDEN)
    assert cases, "at least one golden case is committed"
    for case in cases:
        assert check_case(case) == [], case.path
    index = read_index(GOLDEN / "cbic_notifications" / "index.yaml")
    assert len(index["documents"]) == 50
    assert all(entry["label_status"] == "draft" for entry in index["documents"])


def test_check_reports_a_label_that_cites_a_missing_clause(tmp_path: Path) -> None:
    source = GOLDEN / "cbic_notifications" / "cases" / "01-2026-central-tax.yaml"
    data = yaml.safe_load(source.read_text())
    data["expected"]["citations"] = [{"clause_ref": "en.p99", "quote": "x"}]
    bad = tmp_path / "cases" / "bad.yaml"
    bad.parent.mkdir()
    bad.write_text(yaml.safe_dump(data))
    problems = check_case(load_case(bad))
    assert any("citation_missing_clause" in p for p in problems)
    assert main(["check", "--golden", str(tmp_path)]) == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"label_status": "done"}, "label_status"),
        ({"document": None}, "document and source"),
        ({"source": {"sha256": "short"}}, "sha256"),
        ({"expected": 3}, "expected must be"),
    ],
)
def test_load_case_rejects_bad_files(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    source = GOLDEN / "cbic_notifications" / "cases" / "01-2026-central-tax.yaml"
    data = yaml.safe_load(source.read_text())
    data.update(changes)
    path = tmp_path / "x.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(LabelError, match=message):
        load_case(path)


def test_check_command_on_the_repo_golden_set(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--golden", str(GOLDEN)]) == 0
    assert "50 indexed" in capsys.readouterr().out
