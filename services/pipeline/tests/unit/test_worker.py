"""The worker's activity list: the relation prompt is read and the embedding stage built only
when knowledge is on; the crawl's activities, the source sync at start and, with crawling on,
the tick."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from pipeline import worker
from pipeline.application.crawl import ScheduleCrawls, ScheduleReport
from pipeline.application.knowledge_activities import (
    EmbedClauses,
    EmbedRequest,
    ProposeRelations,
)
from pipeline.infrastructure.adapters import SOURCES
from pipeline.infrastructure.memory import MemoryStore
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryCrawls, MemoryRulebook, ScriptedEmbedder
from pipeline.worker import SYNC_HOOK, TICK_JOB, TICK_SECONDS, WORKFLOWS, activities, components
from pipeline.workflows import (
    TASK_QUEUE,
    CrawlSourceWorkflow,
    ExtractKnowledgeWorkflow,
    IngestDocumentWorkflow,
)


def settings(**overrides: object) -> PipelineSettings:
    return PipelineSettings(_env_file=None, service_name="pipeline-worker", **overrides)  # type: ignore[arg-type]


def test_with_knowledge_off_no_prompt_is_read(tmp_path: Path) -> None:
    names = [a.name for a in activities(settings(pipeline_prompts_dir=tmp_path / "missing"))]
    assert "pipeline.propose_relations" in names
    assert "pipeline.embed_clauses" in names
    assert len(names) == len(set(names)) == 11
    assert "pipeline.fetch_and_store" in names
    assert names[-2:] == ["pipeline.list_new_documents", "pipeline.finish_crawl"]


def test_with_knowledge_on_the_prompt_must_be_there(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        activities(
            settings(pipeline_knowledge_enabled=True, pipeline_prompts_dir=tmp_path / "missing")
        )
    assert len(activities(settings(pipeline_knowledge_enabled=True))) == 11


def test_an_enabled_relation_activity_needs_its_stage() -> None:
    with pytest.raises(ValueError, match="needs its stage"):
        ProposeRelations(object(), None, enabled=True)  # type: ignore[arg-type]


async def test_the_embedding_activity_uses_the_embedder_it_is_given() -> None:
    embedder = ScriptedEmbedder()
    wired = activities(
        settings(pipeline_knowledge_enabled=True), sink=MemoryRulebook(), embedder=embedder
    )
    (embedding,) = [a for a in wired if isinstance(a, EmbedClauses)]
    report = await embedding.run(EmbedRequest(document_id=UUID(int=1)))
    assert (report.embedded, report.model) == (0, ScriptedEmbedder.MODEL)
    assert len(embedder.requests) == 1
    off = activities(settings(), sink=MemoryRulebook(), embedder=embedder)
    (skipping,) = [a for a in off if isinstance(a, EmbedClauses)]
    assert (await skipping.run(EmbedRequest(document_id=UUID(int=1)))).skipped is True
    assert len(embedder.requests) == 1


def test_the_worker_serves_every_workflow_and_activity_on_the_pipeline_queue() -> None:
    (temporal,) = components(settings()).temporal
    assert temporal.task_queue == TASK_QUEUE
    assert temporal.workflows == WORKFLOWS
    assert (IngestDocumentWorkflow, ExtractKnowledgeWorkflow, CrawlSourceWorkflow) == WORKFLOWS
    assert [a.name for a in temporal.activities] == [a.name for a in activities(settings())]
    assert not components(settings()).loops(), "crawling is off: no tick"


async def test_the_worker_adds_the_built_in_sources_when_it_starts() -> None:
    store = MemoryStore()
    (hook,) = components(settings(), units=store).startup
    assert hook.name == SYNC_HOOK
    await hook.run()
    assert sorted(store.sources) == sorted(SOURCES)
    assert store.sources["cbic_notifications"].name == "CBIC Central Tax notifications"


async def test_with_crawling_on_the_tick_starts_the_crawls_that_are_due() -> None:
    store, starter = MemoryStore(), MemoryCrawls()
    wired = components(settings(pipeline_crawl_enabled=True), units=store, starter=starter)
    (tick,) = wired.periodic
    assert (tick.name, tick.interval_seconds) == (TICK_JOB, TICK_SECONDS)
    assert wired.loops() == (tick,)
    await wired.startup[0].run()
    assert await tick.run_once()
    assert sorted(start.source_key for start in starter.started) == sorted(SOURCES)
    assert await tick.run_once()
    assert len(starter.started) == len(SOURCES), "a second tick starts nothing twice"
    assert all(run.status.value == "running" for run in store.crawl_runs.values())


def test_the_tick_job_runs_the_schedule_once_a_minute() -> None:
    ran: list[str] = []

    class Schedule(ScheduleCrawls):
        def run(self) -> ScheduleReport:
            ran.append("tick")
            return ScheduleReport()

    worker.tick_job(Schedule(MemoryStore(), MemoryCrawls(), enabled=True))()
    assert ran == ["tick"]
    assert timedelta(seconds=TICK_SECONDS) == timedelta(minutes=1)


def test_the_worker_needs_the_postgres_store() -> None:
    with pytest.raises(ValueError, match="CW_PIPELINE_STORE=postgres"):
        components(settings(pipeline_store="memory"))


def test_python_m_pipeline_worker_runs_the_components(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[tuple[object, object]] = []
    monkeypatch.setattr(worker, "run_worker_process", lambda s, c, *, version: ran.append((s, c)))
    worker.main()
    ((ran_settings, ran_components),) = ran
    assert isinstance(ran_settings, PipelineSettings)
    assert ran_settings.service_name == "pipeline-worker"
    assert ran_components is components
