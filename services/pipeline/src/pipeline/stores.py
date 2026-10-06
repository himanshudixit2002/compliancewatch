"""The stores the settings pick: where the pipeline records what it fetched
(``CW_PIPELINE_STORE``) and where it keeps the files (``CW_PIPELINE_RAW_STORE``). Composition
code, beside ``worker`` and ``main``: the layers below take the domain's protocols."""

from collections.abc import Callable

from pipeline.domain.ports import RawStore
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import LocalRawStore, MemoryRawStore, S3RawStore
from pipeline.infrastructure.repository import PostgresUnitOfWorkFactory
from pipeline.infrastructure.s3 import S3Client, S3Credentials
from pipeline.settings import PipelineSettings


def unit_of_work_of(settings: PipelineSettings) -> UnitOfWorkFactory:
    """The ``pipeline`` schema at ``CW_DATABASE_URL``, or a store in this process's memory."""
    if settings.pipeline_store == "memory":
        return MemoryStore()
    return PostgresUnitOfWorkFactory.from_url(settings.database_url)


def ping_of(units: UnitOfWorkFactory) -> Callable[[], bool]:
    """The store's readiness probe: its ``ping``, or always ready for a store without one."""
    ping = getattr(units, "ping", None)
    if callable(ping):
        probe: Callable[[], bool] = ping
        return probe
    return lambda: True


def raw_store_of(settings: PipelineSettings) -> RawStore:
    """The raw store ``CW_PIPELINE_RAW_STORE`` names, built from its settings."""
    if settings.pipeline_raw_store == "memory":
        return MemoryRawStore()
    if settings.pipeline_raw_store == "local":
        return LocalRawStore(settings.pipeline_raw_dir)
    secret = settings.pipeline_raw_secret_access_key
    token = settings.pipeline_raw_session_token
    client = S3Client(
        bucket=str(settings.pipeline_raw_bucket),
        region=settings.pipeline_raw_region,
        endpoint_url=settings.pipeline_raw_endpoint_url,
        credentials=S3Credentials(
            access_key_id=str(settings.pipeline_raw_access_key_id),
            secret_access_key="" if secret is None else secret.get_secret_value(),
            session_token=None if token is None else token.get_secret_value() or None,
        ),
    )
    return S3RawStore(
        client,
        prefix=settings.pipeline_raw_prefix,
        encryption=settings.pipeline_raw_encryption,
        kms_key_id=settings.pipeline_raw_kms_key_id or None,
    )
