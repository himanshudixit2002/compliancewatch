"""Process configuration of the qa service: ``CW_*`` variables on top of py-common's."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from py_common.settings import Settings


class QaSettings(Settings):
    """``qa_kag_enabled`` turns on the planner and solver layer (ADR-017) between the structured
    layer and hybrid search (``CW_QA_KAG_ENABLED``, default off; owner ai-platform; remove the
    flag when ADR-017 is Accepted). With it on, ``qa_kag_tenants`` (``CW_QA_KAG_TENANTS``, a
    comma list of tenant UUIDs) names the tenants that get the layer; empty means every tenant.
    Off, or for a tenant not listed, no question costs a planner call.

    ``rulebook_url``, ``profile_url``, ``obligation_url`` and ``llm_gateway_url`` are the
    services the answers are built from; every model call goes through the gateway. Reads time
    out after ``qa_http_timeout_seconds``, model calls after ``qa_llm_timeout_seconds``.
    ``qa_prompts_dir`` is where the prompt files are when the package is installed away from
    the source tree (the image sets ``CW_QA_PROMPTS_DIR=/app/prompts``).
    """

    qa_kag_enabled: bool = False
    qa_kag_tenants: Annotated[frozenset[UUID], NoDecode] = frozenset()
    rulebook_url: str = "http://localhost:8003"
    profile_url: str = "http://localhost:8002"
    obligation_url: str = "http://localhost:8005"
    llm_gateway_url: str = "http://localhost:8008"
    qa_prompts_dir: Path | None = None
    qa_http_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    qa_llm_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    @field_validator("qa_kag_tenants", mode="before")
    @classmethod
    def _split_tenants(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(part.strip() for part in value.split(",") if part.strip())
        return value
