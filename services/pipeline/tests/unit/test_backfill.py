from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain_kernel.documents import DocumentType
from pipeline import backfill
from pipeline.backfill import BackfillResult, ingest, main, parsers_for
from pipeline.infrastructure.adapters import build_adapter
from pipeline.infrastructure.fakes import FakeSourceAdapter
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.raw_store import LocalRawStore, MemoryRawStore
from pipeline.testing import recorded_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIG = ClientConfig(min_delay_seconds=0, respect_robots=False)


def recorded_client() -> PoliteClient:
    return PoliteClient(CONFIG, transport=recorded_sources(FIXTURES), sleep=lambda _: None)


def test_ingest_fetches_stores_parses_and_detects() -> None:
    client = recorded_client()
    store = MemoryRawStore()
    out: list[str] = []
    result = ingest(
        build_adapter("cbic_notifications", client),
        parsers_for(DocumentType.NOTIFICATION),
        store,
        source_key="cbic_notifications",
        since=datetime(2026, 4, 1, tzinfo=UTC),
        default_type=DocumentType.NOTIFICATION,
        out=out,
    )
    assert result == BackfillResult(listed=2, fetched=1, parsed=1, unparsed=0, failed=1)
    assert len(store.files) == 1
    assert any("fetch failed" in line for line in out)
    parsed_line = next(line for line in out if "\tnotification\t" in line)
    assert parsed_line.startswith("cbic_notifications\t2026-04-21\t")
    assert parsed_line.endswith(next(iter(store.files)))


def test_ingest_respects_limit_and_list_only() -> None:
    out: list[str] = []
    result = ingest(
        FakeSourceAdapter.with_sample(),
        [],
        MemoryRawStore(),
        source_key="fake",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        default_type=DocumentType.NOTIFICATION,
        limit=1,
        list_only=True,
        out=out,
    )
    assert result == BackfillResult(1, 0, 0, 0, 0)
    assert out == ["fake\tNone\t-\tNotification No. 17/2026 - Central Tax"]


def test_ingest_reports_a_document_no_parser_handles() -> None:
    result = ingest(
        FakeSourceAdapter.with_sample(),
        parsers_for(DocumentType.NOTIFICATION),
        MemoryRawStore(),
        source_key="fake",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        default_type=DocumentType.NOTIFICATION,
    )
    assert result == BackfillResult(1, 1, 0, 1, 0)


def test_main_runs_a_recorded_backfill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(backfill, "PoliteClient", lambda config: recorded_client())
    code = main(
        ["--source", "gstn_advisories", "--since", "2026-08-01", "--store", str(tmp_path / "raw")]
    )
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1] == "gstn_advisories: listed 3, fetched 3, parsed 3, unparsed 0, failed 0"
    stored = sorted((tmp_path / "raw").glob("*/*"))
    assert len(stored) == 3
    key = f"{stored[0].parent.name}/{stored[0].name}"
    assert LocalRawStore(tmp_path / "raw").get(key) == stored[0].read_bytes()
    assert any(line.endswith(stored[0].resolve().as_uri()) for line in lines)


def test_main_fails_when_nothing_could_be_fetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Broken:
        def list_documents(self, since: datetime):  # type: ignore[no-untyped-def]
            yield from FakeSourceAdapter.with_sample().list_documents(since)

        def fetch(self, ref):  # type: ignore[no-untyped-def]
            raise ConnectionError("down")

    monkeypatch.setattr(backfill, "PoliteClient", lambda config: recorded_client())
    monkeypatch.setattr(backfill, "build_adapter", lambda key, client: Broken())
    assert main(["--source", "gstn_advisories", "--store", str(tmp_path)]) == 1
