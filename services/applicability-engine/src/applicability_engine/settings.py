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

    The worker's profile.updated consumer (``applicability_engine.worker``) records every node
    it hears of in the business directory; with ``applicability_recompute_enabled`` (flag
    ``applicability.recompute``, off by default) it also evaluates the node and the
    registrations under it against the rule versions in force today and, with
    ``applicability_engine_recompute_lookahead_days``, the ones taking effect within that many
    days. The rulebook's listing of a day is cached for
    ``applicability_engine_rules_cache_seconds`` (0 turns the cache off).

    With ``applicability_fanout_enabled`` (flag ``applicability.fanout``, off by default) the
    worker's consumer of rule.published starts a fan-out of the version over the business
    directory, a Temporal workflow on the ``applicability`` task queue, and the fan-out controls
    signal it there (``CW_TEMPORAL_*``). Off, a publication records a ``disabled`` run and nothing
    else, and the controls signal nothing.

    A dry run (``POST /v1/applicability-engine/dry-runs``) reads every profile of its scope while
    the request waits, so it evaluates at most ``applicability_dry_run_max`` businesses and
    refuses a wider scope.
    """

    applicability_engine_store: Store = "postgres"
    profile_url: str = "http://localhost:8002"
    rulebook_url: str = "http://localhost:8003"
    applicability_engine_http_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    applicability_recompute_enabled: bool = False
    applicability_engine_rules_cache_seconds: float = Field(default=60.0, ge=0, le=3600)
    applicability_engine_recompute_lookahead_days: int = Field(default=92, ge=0, le=366)
    applicability_fanout_enabled: bool = False
    applicability_dry_run_max: int = Field(default=2_000, ge=1, le=100_000)
