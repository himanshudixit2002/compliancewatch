import pytest
from pydantic import ValidationError

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


def settings(**values: object) -> PipelineSettings:
    return PipelineSettings(_env_file=None, service_name="pipeline-worker", **values)  # type: ignore[arg-type]


S3 = {
    "pipeline_raw_store": "s3",
    "pipeline_raw_bucket": "cw-raw-staging",
    "pipeline_raw_access_key_id": "raw-key-id",
    "pipeline_raw_secret_access_key": "raw-secret",
}


def test_documents_are_recorded_in_postgres_and_files_kept_on_disk_by_default() -> None:
    defaults = settings()
    assert (defaults.pipeline_store, defaults.pipeline_raw_store) == ("postgres", "local")
    assert str(defaults.pipeline_raw_dir) == "var/raw"
    assert (defaults.pipeline_raw_prefix, defaults.pipeline_raw_region) == ("raw/", "ap-south-1")
    assert defaults.pipeline_raw_encryption == "AES256"


def test_the_s3_store_needs_its_bucket_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(
        ValidationError, match="CW_PIPELINE_RAW_STORE=s3 needs CW_PIPELINE_RAW_BUCKET"
    ):
        settings(pipeline_raw_store="s3")
    monkeypatch.setenv("CW_PIPELINE_RAW_STORE", "s3")
    monkeypatch.setenv("CW_PIPELINE_RAW_BUCKET", "cw-raw-dev")
    monkeypatch.setenv("CW_PIPELINE_RAW_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setenv("CW_PIPELINE_RAW_ACCESS_KEY_ID", "minio-user")
    monkeypatch.setenv("CW_PIPELINE_RAW_SECRET_ACCESS_KEY", "minio-secret")
    from_environment = settings()
    assert from_environment.pipeline_raw_endpoint_url == "http://localhost:9000"
    assert "minio-secret" not in repr(from_environment)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"pipeline_raw_bucket": "Has.Dots"}, "CW_PIPELINE_RAW_BUCKET must be"),
        ({"pipeline_raw_prefix": "/raw"}, "CW_PIPELINE_RAW_PREFIX must be"),
        ({"pipeline_raw_prefix": "raw"}, "CW_PIPELINE_RAW_PREFIX must be"),
        ({"pipeline_raw_region": "Mumbai"}, "CW_PIPELINE_RAW_REGION must be"),
        ({"pipeline_raw_endpoint_url": "minio:9000"}, "CW_PIPELINE_RAW_ENDPOINT_URL must be"),
        ({"pipeline_raw_kms_key_id": "alias/raw"}, "needs CW_PIPELINE_RAW_ENCRYPTION=aws:kms"),
    ],
)
def test_a_malformed_s3_location_is_refused(values: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(**{**S3, **values})


def test_unencrypted_files_are_for_a_local_minio_only() -> None:
    assert settings(**S3, pipeline_raw_encryption="none").pipeline_raw_encryption == "none"
    for env in ("staging", "prod"):
        with pytest.raises(ValidationError, match=f"CW_ENV={env} needs AES256 or aws:kms"):
            settings(**S3, pipeline_raw_encryption="none", env=env, auth_mode="token")
    kms = settings(**S3, pipeline_raw_encryption="aws:kms", pipeline_raw_kms_key_id="alias/raw")
    assert kms.pipeline_raw_kms_key_id == "alias/raw"
