"""Process configuration of the obligation service: ``CW_*`` variables on top of py-common's.

``rulebook_url`` is where the worker reads the rule versions it materialises. The reminder sweep
runs in the worker only when ``obligation_sweep_enabled`` (``CW_OBLIGATION_SWEEP_ENABLED``) is
set, every ``obligation_sweep_interval_seconds`` (an hour by default).
"""

from typing import Literal

from pydantic import Field

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class ObligationSettings(Settings):
    """``obligation_store`` picks the store: memory for tests and demos, postgres otherwise."""

    obligation_store: Store = "postgres"
    rulebook_url: str = "http://localhost:8003"
    obligation_sweep_enabled: bool = False
    obligation_sweep_interval_seconds: float = Field(default=3600.0, gt=0)
