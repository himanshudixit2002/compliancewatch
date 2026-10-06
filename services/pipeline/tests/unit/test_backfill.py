"""The backfill command: its plan, the dry run over recorded CBIC listings (no fetch, no write),
the crawls of each row through a fake crawl starter and watcher, the report, and the legacy
fetch into a local raw store behind ``--legacy``. Nothing here reaches the network."""

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from domain_kernel.documents import DocumentType, document_id_for
from pipeline import backfill
from pipeline.application.backfill import (
    BACKFILL_ACTION,
    BackfillReport,
    BackfillRequest,
    PlanDryRun,
    RunBackfill,
    StartBackfill,
)
from pipeline.application.crawl import ChildOutcome, FinishCrawl, FinishRequest
from pipeline.application.extraction import RULE_PROMPT_REF
from pipeline.application.sources import SyncSources
from pipeline.backfill import (
    BackfillResult,
    PlanError,
    Wiring,
    ingest,
    load_plan,
    main,
    run,
)
from pipeline.domain.backfill import BackfillRow, first_limit, next_limit
from pipeline.domain.classification import Classification, Relevance, TypeConfidence
from pipeline.domain.crawl import CrawlStatus, CrawlTrigger, Outcome
from pipeline.domain.errors import CrawlDisabledError, CrawlRunningError, SourceNotListableError
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction, candidate_id_for
from pipeline.domain.ports import CrawlOutcome, CrawlStart
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.infrastructure.adapters import (
    SOURCES,
    RegistryAdapterTypes,
    StoreCatalog,
    build_adapter,
)
from pipeline.infrastructure.fakes import FakeSourceAdapter
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import parsers_for
from pipeline.infrastructure.raw_store import LocalRawStore, MemoryRawStore
from pipeline.testing import pipeline_settings, recorded_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PLAN = Path(__file__).resolve().parents[2] / "backfill-plan.yaml"
CONFIG = ClientConfig(min_delay_seconds=0, respect_robots=False)
NOW = datetime(2000, 1, 3, 6, 0, tzinfo=UTC)
CBIC_PDF = "https://taxinformation.cbic.gov.in/content/pdf/tax_repository/gst/notifications/"
REASON = "Example: fill the store with the recorded history"
TYPES = RegistryAdapterTypes()


def recorded_client() -> PoliteClient:
    return PoliteClient(CONFIG, transport=recorded_sources(FIXTURES), sleep=lambda _: None)


def synced() -> MemoryStore:
    store = MemoryStore()
    SyncSources(store, [spec.definition() for spec in SOURCES.values()]).run()
    return store


def stored_at(store: MemoryStore, url: str, content: bytes) -> RawDocumentRecord:
    digest = __import__("hashlib").sha256(content).hexdigest()
    record = RawDocumentRecord(
        document_id=document_id_for(digest),
        source_key="cbic_notifications",
        source_url=url,
        fetched_at=NOW,
        content_type="application/pdf",
        size=len(content),
        sha256=digest,
        storage_key=f"{digest[:2]}/{digest}",
    )
    with store() as unit:
        unit.documents.add(record)
    return record


def row(**values: Any) -> BackfillRow:
    defaults: dict[str, Any] = {"source_key": "cbic_notifications", "since": date(2025, 1, 1)}
    defaults.update(values)
    return BackfillRow(**defaults)


# ---------------------------------------------------------------- the plan


def test_the_committed_plan_loads_cited_rows_first() -> None:
    rows = load_plan(PLAN)
    assert all(r.source_key == "cbic_notifications" for r in rows)
    cited, recent = rows[:-1], rows[-1]
    assert all(r.refs and r.until is not None for r in cited), "the cited ones first, by name"
    assert (recent.refs, recent.max_documents) == ((), 200), "then about 200 recent ones"
    assert all(r.until is None or r.since <= r.until for r in rows)


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("rows: []", "non-empty list of rows"),
        ("rows: [1]", "not a mapping"),
        ("rows: [{source: x, since: 2000-01-01, colour: red}]", "unknown keys colour"),
        ("rows: [{source: cbic_notifications, since: never}]", "Invalid isoformat"),
        ("rows: [{source: cbic_notifications, since: 2000-01-02, until: 2000-01-01}]", "until"),
        ("rows: [{source: cbic_notifications, since: 2000-01-01, refs: oops}]", "list of refer"),
        ("rows: [{source: cbic_notifications, since: 2000-01-01, limit: 501}]", "at most 500"),
        (":", "expected <block end>"),
    ],
)
def test_a_plan_that_cannot_run_is_refused(tmp_path: Path, text: str, fragment: str) -> None:
    plan = tmp_path / "plan.yaml"
    plan.write_text(text, encoding="utf-8")
    with pytest.raises(PlanError, match=fragment):
        load_plan(plan)


def test_a_rows_limits_decide_its_crawls() -> None:
    capped = row(limit=100, max_documents=150)
    assert first_limit(capped) == 100
    assert next_limit(capped, rounds=1, stored=100, deferred=7, progressed=True, max_rounds=5) == 50
    assert (
        next_limit(capped, rounds=2, stored=150, deferred=7, progressed=True, max_rounds=5) is None
    )
    plain = row(limit=30)
    assert next_limit(plain, rounds=1, stored=30, deferred=1, progressed=True, max_rounds=5) == 30
    assert next_limit(plain, rounds=1, stored=30, deferred=0, progressed=True, max_rounds=5) is None
    assert next_limit(plain, rounds=1, stored=0, deferred=9, progressed=False, max_rounds=5) is None
    assert next_limit(plain, rounds=5, stored=30, deferred=9, progressed=True, max_rounds=5) is None
    assert first_limit(row(limit=100, max_documents=20)) == 20
    assert row(until=date(2025, 12, 31), refs=("1/2025",), max_documents=3).describe() == (
        "cbic_notifications since 2025-01-01, until 2025-12-31, 1 ref, at most 3 documents"
    )


# ---------------------------------------------------------------- the dry run


def test_a_dry_run_counts_what_each_window_lists_against_the_store() -> None:
    store = synced()
    stored_at(store, CBIC_PDF + "gst-ct-17-2025.pdf", b"%PDF example seventeen")
    rows = [
        row(until=date(2025, 12, 31), refs=("2/2025-Central Tax", "17/2025-Central Tax")),
        row(since=date(2025, 9, 1)),
        row(since=date(2024, 1, 1), refs=("12/2024-Central Tax",)),
    ]
    listings = PlanDryRun(store, StoreCatalog(store, recorded_client())).run(rows)
    named, recent, unrecorded = listings
    assert (named.listed, named.known, named.new, named.sample) == (
        2,
        1,
        1,
        ("02/2025-Central Tax",),
    )
    assert (recent.listed, recent.known, recent.new) == (10, 1, 9)
    assert recent.sample[0] == "02/2026-Central Tax", "newest first"
    assert unrecorded.error, "a page nobody recorded fails the listing, never the network"
    assert store.crawl_runs == {}, "a dry run records nothing"


class FakeCrawls:
    """A crawl starter and watcher: keeps each start, and answers each wait with the next
    scripted outcome after closing its run, as the crawl's last activity does."""

    def __init__(self, store: MemoryStore, outcomes: Sequence[CrawlOutcome]) -> None:
        self.store = store
        self.started: list[CrawlStart] = []
        self.outcomes = list(outcomes)

    def start(self, start: CrawlStart) -> bool:
        self.started.append(start)
        return True

    def wait(self, workflow_id: str) -> CrawlOutcome:
        start = next(s for s in self.started if s.workflow_id == workflow_id)
        outcome = replace(self.outcomes.pop(0), workflow_id=workflow_id)
        FinishCrawl(self.store, clock=lambda: NOW + timedelta(hours=1)).finish(
            FinishRequest(
                source_key=start.source_key,
                run_id=start.run_id.value,
                listed=outcome.listed,
                trigger=CrawlTrigger.BACKFILL,
                deferred=outcome.deferred,
                outcomes=[
                    ChildOutcome(url=f"https://example.invalid/{n}", outcome=Outcome.STORED)
                    for n in range(outcome.stored)
                ],
            )
        )
        return outcome


def done(stored: int, deferred: int, **values: Any) -> CrawlOutcome:
    return CrawlOutcome(
        workflow_id="",
        status="completed",
        listed=stored + deferred,
        stored=stored,
        deferred=deferred,
        **values,
    )


def test_a_row_is_crawled_again_while_new_documents_are_left() -> None:
    store = synced()
    crawls = FakeCrawls(store, [done(100, 60), done(60, 0)])
    start = StartBackfill(
        store,
        crawls,
        types=TYPES,
        enabled=True,
        clock=lambda: NOW,
        request_ids=iter(UUID(int=n) for n in range(1, 10)).__next__,
    )
    request = BackfillRequest(actor=backfill.AuditActor.system("pipeline-backfill"), reason=REASON)
    (ran,) = RunBackfill(start, crawls).run([row(limit=100)], request)
    assert (len(ran.rounds), ran.stored, ran.stopped) == (2, 160, "nothing new is left")
    first = crawls.started[0]
    assert first.workflow_id == f"pipeline-crawl-cbic_notifications-backfill-{UUID(int=1).hex}"
    assert (first.trigger, first.since, first.until, first.refs, first.limit) == (
        CrawlTrigger.BACKFILL,
        date(2025, 1, 1),
        None,
        (),
        100,
    )
    runs = sorted(store.crawl_runs.values(), key=lambda r: r.workflow_id)
    assert [(r.trigger, r.status) for r in runs] == [
        (CrawlTrigger.BACKFILL, CrawlStatus.COMPLETED),
        (CrawlTrigger.BACKFILL, CrawlStatus.COMPLETED),
    ]
    audited = [entry for entry in store.audit if entry.action == BACKFILL_ACTION]
    assert len(audited) == 2
    assert audited[0].after is not None
    assert (audited[0].after["since"], audited[0].after["limit"]) == ("2025-01-01", 100)
    assert audited[0].actor.label == "system:pipeline-backfill"


def test_a_row_stops_at_its_documents_its_rounds_or_when_nothing_is_kept() -> None:
    store = synced()
    request = BackfillRequest(actor=backfill.AuditActor.system("pipeline-backfill"), reason=REASON)

    def ran(outcomes: list[CrawlOutcome], wanted: BackfillRow, rounds: int = 20) -> Any:
        crawls = FakeCrawls(store, outcomes)
        start = StartBackfill(store, crawls, types=TYPES, enabled=True)
        (found,) = RunBackfill(start, crawls, max_rounds=rounds).run([wanted], request)
        return found, crawls

    capped, crawls = ran([done(100, 300), done(50, 250)], row(limit=100, max_documents=150))
    assert (capped.stored, capped.stopped) == (150, "it stored its 150 documents")
    assert [s.limit for s in crawls.started] == [100, 50]
    kept_nothing, _ = ran([done(0, 5, failed=5)], row())
    assert kept_nothing.stopped == "the last crawl kept nothing"
    bounded, _ = ran([done(10, 5), done(10, 5)], row(), rounds=2)
    assert bounded.stopped == "it ran 2 crawls"
    failed, _ = ran([CrawlOutcome("", "failed", error="Example: listing failed")], row())
    assert failed.stopped == "the crawl failed: Example: listing failed"


def test_a_backfill_is_refused_while_crawling_is_off_for_an_upload_only_source_or_a_busy_one() -> (
    None
):
    store = synced()
    request = BackfillRequest(actor=backfill.AuditActor.system("pipeline-backfill"), reason=REASON)
    off = StartBackfill(store, FakeCrawls(store, []), types=TYPES, enabled=False)
    with pytest.raises(CrawlDisabledError):
        off.run(row(), 10, request)
    on = StartBackfill(store, FakeCrawls(store, []), types=TYPES, enabled=True)
    with pytest.raises(SourceNotListableError):
        on.run(row(source_key="cgst_act"), 10, request)
    on.run(row(), 10, request)
    with pytest.raises(CrawlRunningError):
        on.run(row(), 10, request)
    (stopped,) = RunBackfill(on, FakeCrawls(store, [])).run([row()], request)
    assert (stopped.rounds, stopped.stopped.split(":")[0]) == ((), "CrawlRunningError")


# ---------------------------------------------------------------- the report


class Stats:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails

    def candidate_stats(self) -> dict[str, object]:
        if self.fails:
            raise ConnectionError("example rulebook away")
        return {
            "decided": 4,
            "approved": 3,
            "approved_without_edits": 2,
            "rejected": 1,
            "acceptance_rate": 0.5,
        }


def funnel_store() -> MemoryStore:
    store = synced()
    statuses = [
        DocumentStatus.FAILED,
        DocumentStatus.IRRELEVANT,
        DocumentStatus.CLASSIFIED,
        DocumentStatus.TRIAGE,
        DocumentStatus.REFERENCE,
        DocumentStatus.EXTRACTED,
        DocumentStatus.EXTRACTED,
    ]
    for index, status in enumerate(statuses):
        record = stored_at(store, f"https://example.invalid/{index}", f"%PDF {index}".encode())
        with store() as unit:
            if status is not DocumentStatus.FAILED:
                unit.documents.record_parse(record.document_id, "pdf@1")
            unit.documents.set_status(record.document_id, status)
            if status is DocumentStatus.EXTRACTED:
                unit.classifications.add(
                    Classification(
                        document_id=record.document_id,
                        doc_type=DocumentType.NOTIFICATION,
                        relevance=Relevance.RELEVANT,
                        confidence=TypeConfidence.CERTAIN,
                        reasons=("Example",),
                        classified_at=NOW,
                    )
                )
                unit.extractions.add(
                    RuleExtraction(
                        document_id=record.document_id,
                        prompt_version=RULE_PROMPT_REF,
                        candidate_id=candidate_id_for(record.document_id, RULE_PROMPT_REF),
                        outcome=ExtractionOutcome.EXTRACTED
                        if index == 5
                        else ExtractionOutcome.UNPARSEABLE,
                        model="fake/echo",
                        attempts=1,
                        source_key="cbic_notifications",
                        doc_type=DocumentType.NOTIFICATION,
                        regulator="CBIC",
                        issues=(),
                        citation_count=0,
                        confidence=0.0,
                        needs_review=True,
                        answer="",
                        ontology_version="1",
                        extracted_at=NOW,
                        fields=None if index != 5 else {"title": "Example"},
                    )
                )
    return store


def test_the_report_counts_where_each_document_got_to() -> None:
    funnel = BackfillReport(funnel_store(), Stats()).run(["gstn_advisories"])
    (cbic,) = [s for s in funnel.sources if s.source_key == "cbic_notifications"]
    assert (cbic.tally.stored, cbic.tally.parsed, cbic.at(DocumentStatus.FAILED)) == (7, 6, 1)
    assert (cbic.at(DocumentStatus.EXTRACTED), cbic.candidates, cbic.unparseable) == (2, 1, 1)
    assert [s.source_key for s in funnel.sources] == ["cbic_notifications", "gstn_advisories"]
    assert funnel.unparsed_share == pytest.approx(1 / 7)
    assert funnel.acceptance["acceptance_rate"] == 0.5
    away = BackfillReport(funnel_store(), Stats(fails=True)).run()
    assert away.acceptance == {}
    assert "example rulebook away" in away.acceptance_error
    assert BackfillReport(MemoryStore(), None).run().unparsed_share is None


# ---------------------------------------------------------------- the command


def wiring(store: MemoryStore, crawls: FakeCrawls | None = None, *, crawl: bool = True) -> Wiring:
    fake = crawls or FakeCrawls(store, [])
    return Wiring(
        settings=pipeline_settings(pipeline_crawl_enabled=crawl),
        units=store,
        types=TYPES,
        catalog=lambda: StoreCatalog(store, recorded_client()),
        starter=fake,
        watcher=fake,
        stats=Stats(),
    )


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    path = tmp_path / "plan.yaml"
    path.write_text(
        "rows:\n"
        "  - {source: cbic_notifications, since: 2025-09-01, until: 2025-12-31, limit: 5}\n"
        "  - {source: cbic_notifications, since: 2026-01-01, refs: [1/2026-Central Tax]}\n",
        encoding="utf-8",
    )
    return path


def test_the_command_dry_runs_a_plan(plan: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = synced()
    capsys.readouterr()
    assert run(["--plan", str(plan), "--dry-run"], lambda: wiring(store)) == 0
    out = capsys.readouterr().out
    assert "| 1 | cbic_notifications since 2025-09-01, until 2025-12-31 | 8 | 0 | 8 |" in out
    assert (
        "| 2 | cbic_notifications since 2026-01-01, 1 ref | 1 | 0 | 1 | 01/2026-Central Tax |"
        in out
    )
    assert "9 document(s) new to the store; nothing was fetched or written." in out
    assert (
        run(["--plan", str(plan), "--dry-run", "--json", "--row", "2"], lambda: wiring(store)) == 0
    )
    (answer,) = json.loads(capsys.readouterr().out)
    assert (answer["row"], answer["new"], answer["first_new"]) == (1, 1, ["01/2026-Central Tax"])


def test_the_command_crawls_a_plan_with_a_reason(
    plan: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = synced()
    crawls = FakeCrawls(store, [done(5, 3), done(3, 0), done(1, 0)])
    capsys.readouterr()
    args = ["--plan", str(plan), "--workflow", "--reason", REASON, "--actor-id", str(UUID(int=4))]
    assert run(args, lambda: wiring(store, crawls)) == 0
    out = capsys.readouterr().out
    assert out.count("crawl pipeline-crawl-cbic_notifications-backfill-") == 3
    window = "cbic_notifications since 2025-09-01, until 2025-12-31"
    assert f"| 1 | {window} | 2 | 8 | nothing new is left |" in out
    audited = [entry for entry in store.audit if entry.action == BACKFILL_ACTION]
    assert {entry.actor.id for entry in audited} == {str(UUID(int=4))}


def test_the_command_refuses_without_crawling_or_a_reason(
    plan: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = synced()
    assert (
        run(
            ["--plan", str(plan), "--workflow", "--reason", REASON],
            lambda: wiring(store, crawl=False),
        )
        == 2
    )
    assert "CW_PIPELINE_CRAWL_ENABLED is off" in capsys.readouterr().err
    assert run(["--plan", str(plan), "--workflow"], lambda: wiring(store)) == 2
    assert "needs --reason" in capsys.readouterr().err
    assert run(["--plan", str(plan), "--report", "--row", "3"], lambda: wiring(store)) == 2
    assert "the plan has rows 1 to 2" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run(["--plan", str(plan)], lambda: wiring(store))
    missing = plan.parent / "missing.yaml"
    assert run(["--plan", str(missing), "--report"], lambda: wiring(store)) == 2


def test_the_command_reports(plan: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = funnel_store()
    capsys.readouterr()
    assert run(["--plan", str(plan), "--report"], lambda: wiring(store)) == 0
    out = capsys.readouterr().out
    assert "| cbic_notifications | 7 | 6 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 1 |" in out
    assert "Unparsed: 1 of 7 stored (14.3%)" in out
    assert "Acceptance: 4 candidate(s) decided, 3 approved (2 without edits), 1 rejected" in out
    assert run(["--plan", str(plan), "--report", "--json"], lambda: wiring(store)) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["sources"][0]["unparsed"] == 1
    assert answer["acceptance"]["decided"] == 4


def test_a_failed_crawl_fails_the_command(plan: Path) -> None:
    store = synced()
    crawls = FakeCrawls(store, [CrawlOutcome("", "failed", error="Example: listing failed")] * 2)
    args = ["--plan", str(plan), "--workflow", "--reason", REASON]
    assert run(args, lambda: wiring(store, crawls)) == 1


# ---------------------------------------------------------------- the legacy backfill


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


def test_the_legacy_backfill_runs_on_a_recorded_site(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(backfill, "PoliteClient", lambda config: recorded_client())
    code = main(
        [
            "--legacy",
            "--source",
            "gstn_advisories",
            "--since",
            "2026-08-01",
            "--store",
            str(tmp_path / "raw"),
        ]
    )
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1] == "gstn_advisories: listed 3, fetched 3, parsed 3, unparsed 0, failed 0"
    stored = sorted((tmp_path / "raw").glob("*/*"))
    assert len(stored) == 3
    key = f"{stored[0].parent.name}/{stored[0].name}"
    assert LocalRawStore(tmp_path / "raw").get(key) == stored[0].read_bytes()
    assert any(line.endswith(stored[0].resolve().as_uri()) for line in lines)


def test_the_legacy_backfill_fails_when_nothing_could_be_fetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Broken:
        def list_documents(self, since: datetime):  # type: ignore[no-untyped-def]
            yield from FakeSourceAdapter.with_sample().list_documents(since)

        def fetch(self, ref):  # type: ignore[no-untyped-def]
            raise ConnectionError("down")

    monkeypatch.setattr(backfill, "PoliteClient", lambda config: recorded_client())
    monkeypatch.setattr(backfill, "build_adapter", lambda key, client: Broken())
    assert main(["--legacy", "--source", "gstn_advisories", "--store", str(tmp_path)]) == 1
    assert main(["--legacy"]) == 2
    assert "--legacy needs --source" in capsys.readouterr().err
