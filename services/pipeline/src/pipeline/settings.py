"""Process configuration of the pipeline worker: ``CW_*`` variables on top of py-common's."""

import re
from pathlib import Path
from typing import Final, Literal, Self

from pydantic import Field, SecretStr, model_validator

from py_common.settings import Settings

Store = Literal["memory", "postgres"]
RawStoreKind = Literal["local", "memory", "s3"]
Encryption = Literal["AES256", "aws:kms", "none"]

BUCKET_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$"
PREFIX_PATTERN: Final = r"^([A-Za-z0-9!_.*'()-]+/)*$"
REGION_PATTERN: Final = r"^[a-z0-9-]{2,32}$"
DEPLOYED: Final = frozenset({"staging", "prod"})


class PipelineSettings(Settings):
    """``pipeline_store`` picks where sources, fetched documents and crawl runs are recorded
    (``CW_PIPELINE_STORE``): postgres, the ``pipeline`` schema, by default; memory for tests and
    demos, on which the worker does not start.

    ``pipeline_raw_store`` picks where the fetched files themselves go (``CW_PIPELINE_RAW_STORE``):

    - ``local`` (the default), the directory ``pipeline_raw_dir`` (``var/raw``);
    - ``memory``, for tests;
    - ``s3``, the bucket ``pipeline_raw_bucket`` under ``pipeline_raw_prefix`` (``raw/``) in
      ``pipeline_raw_region`` (``ap-south-1``), at ``pipeline_raw_endpoint_url`` when it is set
      (MinIO in dev, any S3-compatible store; path-style URLs) and on AWS otherwise, with the
      access key ``pipeline_raw_access_key_id`` and ``pipeline_raw_secret_access_key`` (and
      ``pipeline_raw_session_token`` for a temporary one). Every write is encrypted at rest as
      ``pipeline_raw_encryption`` says: ``AES256`` (SSE-S3, the default) or ``aws:kms`` with
      ``pipeline_raw_kms_key_id`` (the bucket's AWS-managed key when it is empty); ``none`` is
      for a local MinIO without a key service and is refused in staging and production.

    ``pipeline_crawl_enabled`` turns the crawl on (``CW_PIPELINE_CRAWL_ENABLED``, default off;
    owner regulatory-intelligence; remove the flag once the 30-day F1 detection run passes in
    staging and the crawl is on in production). On, the worker's tick starts a crawl of every
    enabled, unpaused source whose cadence has passed, an admin may start one by hand
    (``POST /v1/pipeline/sources/{key}/fetch``), and the app reports each source's freshness
    gauges. A crawl reads the live regulator sites: leave it off on a laptop, in ``make product``
    and in CI. Off, the tick starts nothing and the fetch route answers 503.

    ``pipeline_knowledge_enabled`` turns on handing parsed documents to the rulebook and
    embedding their clauses (``CW_PIPELINE_KNOWLEDGE_ENABLED``, default off; owner
    regulatory-intelligence; remove the flag once ADR-017 is accepted). Off, the worker makes no
    call to the rulebook or the gateway.

    ``rulebook_url`` and ``rulebook_write_token`` reach the rulebook's write API; the token is
    the rulebook's ``CW_RULEBOOK_WRITE_TOKEN``. ``llm_gateway_url`` is where the relation stage's
    model calls and the clause embeddings go (``CW_LLM_GATEWAY_URL``). With py-common's
    ``CW_SERVICE_CLIENT_SECRET`` set, both clients also carry the pipeline's own access token
    from the identity service; its client needs the rulebook:write and llm:call scopes.
    ``pipeline_prompts_dir`` is where the prompt files are when the package is installed away
    from the source tree (the image sets ``CW_PIPELINE_PROMPTS_DIR=/app/prompts``); the worker
    reads them only with the flag on.

    ``pipeline_upload_max_bytes`` is the largest file an analyst may upload
    (``CW_PIPELINE_UPLOAD_MAX_BYTES``, 25 MB by default, 100 MB at most); the upload route refuses
    a larger body before it reads it (413).
    """

    pipeline_store: Store = "postgres"
    pipeline_raw_store: RawStoreKind = "local"
    pipeline_raw_dir: Path = Path("var/raw")
    pipeline_raw_bucket: str | None = None
    pipeline_raw_prefix: str = "raw/"
    pipeline_raw_region: str = "ap-south-1"
    pipeline_raw_endpoint_url: str | None = None
    pipeline_raw_access_key_id: str | None = None
    pipeline_raw_secret_access_key: SecretStr | None = None
    pipeline_raw_session_token: SecretStr | None = None
    pipeline_raw_encryption: Encryption = "AES256"
    pipeline_raw_kms_key_id: str | None = None
    pipeline_knowledge_enabled: bool = False
    pipeline_crawl_enabled: bool = False
    rulebook_url: str = "http://localhost:8003"
    rulebook_write_token: SecretStr | None = None
    llm_gateway_url: str = "http://localhost:8008"
    pipeline_prompts_dir: Path | None = None
    pipeline_upload_max_bytes: int = Field(default=25_000_000, ge=1, le=100_000_000)

    @model_validator(mode="after")
    def _s3_needs_its_bucket_and_key(self) -> Self:
        if self.pipeline_raw_store != "s3":
            return self
        missing = [
            variable
            for variable, value in (
                ("CW_PIPELINE_RAW_BUCKET", self.pipeline_raw_bucket),
                ("CW_PIPELINE_RAW_ACCESS_KEY_ID", self.pipeline_raw_access_key_id),
                ("CW_PIPELINE_RAW_SECRET_ACCESS_KEY", _secret(self.pipeline_raw_secret_access_key)),
            )
            if not (value and value.strip())
        ]
        if missing:
            raise ValueError(f"CW_PIPELINE_RAW_STORE=s3 needs {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _well_formed_s3_location(self) -> Self:
        bucket = self.pipeline_raw_bucket
        if bucket and not re.fullmatch(BUCKET_PATTERN, bucket):
            raise ValueError(
                "CW_PIPELINE_RAW_BUCKET must be 3 to 63 lower-case letters, digits and hyphens "
                "(no dots, so a virtual-hosted URL keeps its certificate)"
            )
        if not re.fullmatch(PREFIX_PATTERN, self.pipeline_raw_prefix):
            raise ValueError(
                "CW_PIPELINE_RAW_PREFIX must be empty or segments that each end with '/', "
                "such as raw/"
            )
        if not re.fullmatch(REGION_PATTERN, self.pipeline_raw_region):
            raise ValueError("CW_PIPELINE_RAW_REGION must be a region name such as ap-south-1")
        endpoint = self.pipeline_raw_endpoint_url
        if endpoint and not endpoint.startswith(("http://", "https://")):
            raise ValueError("CW_PIPELINE_RAW_ENDPOINT_URL must be an http:// or https:// URL")
        return self

    @model_validator(mode="after")
    def _encrypted_where_it_counts(self) -> Self:
        if self.pipeline_raw_kms_key_id and self.pipeline_raw_encryption != "aws:kms":
            raise ValueError("CW_PIPELINE_RAW_KMS_KEY_ID needs CW_PIPELINE_RAW_ENCRYPTION=aws:kms")
        if self.pipeline_raw_encryption == "none" and self.env in DEPLOYED:
            raise ValueError(
                f"CW_PIPELINE_RAW_ENCRYPTION=none stores regulator files unencrypted; "
                f"CW_ENV={self.env} needs AES256 or aws:kms"
            )
        return self


def _secret(value: SecretStr | None) -> str | None:
    return None if value is None else value.get_secret_value()
