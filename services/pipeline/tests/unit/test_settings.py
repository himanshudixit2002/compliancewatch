import pytest

from pipeline.settings import PipelineSettings


def test_knowledge_handoff_is_off_by_default() -> None:
    settings = PipelineSettings(_env_file=None, service_name="pipeline-worker")
    assert settings.pipeline_knowledge_enabled is False
    assert settings.rulebook_url == "http://localhost:8003"
    assert settings.rulebook_write_token is None


def test_environment_turns_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_PIPELINE_KNOWLEDGE_ENABLED", "true")
    monkeypatch.setenv("CW_RULEBOOK_URL", "http://rulebook.internal:8003")
    monkeypatch.setenv("CW_RULEBOOK_WRITE_TOKEN", "s3cret")
    settings = PipelineSettings(_env_file=None, service_name="pipeline-worker")
    assert settings.pipeline_knowledge_enabled is True
    assert settings.rulebook_url == "http://rulebook.internal:8003"
    assert settings.rulebook_write_token is not None
    assert settings.rulebook_write_token.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)
