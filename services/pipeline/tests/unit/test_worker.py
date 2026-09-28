"""The worker's activity list: the relation prompt is read and the embedding stage built only
when knowledge is on."""

from pathlib import Path
from uuid import UUID

import pytest

from pipeline.application.knowledge_activities import (
    EmbedClauses,
    EmbedRequest,
    ProposeRelations,
)
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryRulebook, ScriptedEmbedder
from pipeline.worker import activities


def settings(**overrides: object) -> PipelineSettings:
    return PipelineSettings(_env_file=None, service_name="pipeline-worker", **overrides)  # type: ignore[arg-type]


def test_with_knowledge_off_no_prompt_is_read(tmp_path: Path) -> None:
    names = [a.name for a in activities(settings(pipeline_prompts_dir=tmp_path / "missing"))]
    assert "pipeline.propose_relations" in names
    assert "pipeline.embed_clauses" in names
    assert len(names) == len(set(names)) == 8


def test_with_knowledge_on_the_prompt_must_be_there(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        activities(
            settings(pipeline_knowledge_enabled=True, pipeline_prompts_dir=tmp_path / "missing")
        )
    assert len(activities(settings(pipeline_knowledge_enabled=True))) == 8


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
