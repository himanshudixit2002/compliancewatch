"""Process configuration of the obligation service: ``CW_*`` variables on top of py-common's.

``rulebook_url`` is where the worker reads the rule versions it materialises, and
``profile_url`` where the public list of a business's obligations asks whether a business with no
obligation on the page is the tenant's at all. The reminder sweep
and the daily rolling window run in the worker only when ``obligation_sweep_enabled``
(``CW_OBLIGATION_SWEEP_ENABLED``, flag ``obligation.reminder_sweep``) is set, the sweep every
``obligation_sweep_interval_seconds`` (an hour by default). ``obligation_rule_events_enabled``
(``CW_OBLIGATION_RULE_EVENTS_ENABLED``, flag ``obligation.rule_events``, off by default) lets the
worker's consumer of the rule events act on them; off, it only keeps its offsets.
"""

from typing import Literal

from pydantic import Field

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class ObligationSettings(Settings):
    """``obligation_store`` picks the store: memory for tests and demos, postgres otherwise."""

    obligation_store: Store = "postgres"
    rulebook_url: str = "http://localhost:8003"
    profile_url: str = "http://localhost:8002"
    obligation_sweep_enabled: bool = False
    obligation_sweep_interval_seconds: float = Field(default=3600.0, gt=0)
    obligation_rule_events_enabled: bool = False
