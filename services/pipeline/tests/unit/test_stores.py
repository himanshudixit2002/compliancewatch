"""The stores the settings pick."""

from pathlib import Path

from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import LocalRawStore, MemoryRawStore, S3RawStore
from pipeline.infrastructure.repository import PostgresUnitOfWorkFactory
from pipeline.settings import PipelineSettings
from pipeline.stores import raw_store_of, unit_of_work_of


def settings(**values: object) -> PipelineSettings:
    return PipelineSettings(_env_file=None, service_name="pipeline-worker", **values)  # type: ignore[arg-type]


def test_the_store_setting_picks_postgres_or_memory() -> None:
    assert isinstance(unit_of_work_of(settings()), PostgresUnitOfWorkFactory)
    assert isinstance(unit_of_work_of(settings(pipeline_store="memory")), MemoryStore)


def test_the_raw_store_setting_picks_disk_memory_or_s3(tmp_path: Path) -> None:
    local = raw_store_of(settings(pipeline_raw_dir=tmp_path))
    assert isinstance(local, LocalRawStore)
    assert local.uri("ab/" + "ab" * 32).startswith(tmp_path.resolve().as_uri())
    assert isinstance(raw_store_of(settings(pipeline_raw_store="memory")), MemoryRawStore)
    s3 = raw_store_of(
        settings(
            pipeline_raw_store="s3",
            pipeline_raw_bucket="cw-raw-prod",
            pipeline_raw_access_key_id="raw-key-id",
            pipeline_raw_secret_access_key="raw-secret",
            pipeline_raw_session_token="",
        )
    )
    assert isinstance(s3, S3RawStore)
    assert s3.uri("raw/ab/x") == "s3://cw-raw-prod/raw/ab/x"
