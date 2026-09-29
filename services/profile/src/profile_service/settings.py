"""Process configuration of the profile service: ``CW_*`` variables on top of py-common's."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator

from py_common.settings import Settings

Store = Literal["memory", "postgres"]
Lookup = Literal["manual", "static", "http"]


class ProfileSettings(Settings):
    """``profile_store`` picks the persistence: memory for tests and demos, postgres otherwise.
    ``profile_eval_cases_path`` is where not-applicable answers are appended as golden-case
    seeds (JSON lines); empty keeps them in the database review task only."""

    profile_store: Store = "postgres"
    profile_eval_cases_path: Path | None = None
    profile_gstin_lookup: Lookup = "manual"
    """``manual``: no provider, every registration gets a verify_registration task. ``static``:
    the demo table in ``infrastructure.lookup``. ``http``: the provider's taxpayer search at
    ``profile_gstin_lookup_url`` with ``profile_gstin_lookup_api_key``
    (``infrastructure.lookup_http``). The provider is an account the maintainer opens, and its
    field mapping is checked against the provider's sandbox before ``http`` is switched on. This
    is the flag ``profile.gstin_lookup`` (owner core-product): it becomes plain provider
    configuration once the provider contract is signed, and ``manual`` stays the fallback."""
    profile_gstin_lookup_url: str = ""
    profile_gstin_lookup_api_key: SecretStr | None = None
    profile_gstin_lookup_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    """How long one lookup may take; a slower provider counts as unavailable."""

    @model_validator(mode="after")
    def _require_lookup_connection(self) -> Self:
        if self.profile_gstin_lookup == "http" and (
            not self.profile_gstin_lookup_url or self.profile_gstin_lookup_api_key is None
        ):
            raise ValueError(
                "CW_PROFILE_GSTIN_LOOKUP=http needs CW_PROFILE_GSTIN_LOOKUP_URL and "
                "CW_PROFILE_GSTIN_LOOKUP_API_KEY"
            )
        return self
