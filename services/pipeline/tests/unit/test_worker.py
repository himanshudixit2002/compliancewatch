"""The worker's activity list: the relation prompt is read only when knowledge is on."""

from pathlib import Path

import pytest

from pipeline.application.knowledge_activities import ProposeRelations
from pipeline.settings import PipelineSettings
from pipeline.worker import activities


def settings(**overrides: object) -> PipelineSettings:
    return PipelineSettings(_env_file=None, service_name="pipeline-worker", **overrides)  # type: ignore[arg-type]


def test_with_knowledge_off_no_prompt_is_read(tmp_path: Path) -> None:
    names = [a.name for a in activities(settings(pipeline_prompts_dir=tmp_path / "missing"))]
    assert "pipeline.propose_relations" in names
    assert len(names) == 7


def test_with_knowledge_on_the_prompt_must_be_there(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        activities(
            settings(pipeline_knowledge_enabled=True, pipeline_prompts_dir=tmp_path / "missing")
        )
    assert len(activities(settings(pipeline_knowledge_enabled=True))) == 7


def test_an_enabled_relation_activity_needs_its_stage() -> None:
    with pytest.raises(ValueError, match="needs its stage"):
        ProposeRelations(object(), None, enabled=True)  # type: ignore[arg-type]
