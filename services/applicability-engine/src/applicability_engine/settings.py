"""Process configuration of the applicability-engine service: ``CW_*`` variables on top of
py-common's."""

from typing import Literal

from pydantic import Field

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class ApplicabilityEngineSettings(Settings):
    """``applicability_engine_store`` picks the store: memory for tests and demos, postgres
    otherwise.

    ``profile_url`` and ``rulebook_url`` are the services a decision is computed from: the
    profile's snapshot and the rule version's specification. With py-common's
    ``CW_SERVICE_CLIENT_SECRET`` set, every call to them carries this service's own access token
    from the identity service; its client needs tenant:act to read a tenant's profile. Reads
    time out after ``applicability_engine_http_timeout_seconds``.
    """

    applicability_engine_store: Store = "postgres"
    profile_url: str = "http://localhost:8002"
    rulebook_url: str = "http://localhost:8003"
    applicability_engine_http_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
