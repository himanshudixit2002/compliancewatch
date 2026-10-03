"""Process configuration of the eval service: ``CW_*`` variables on top of py-common's."""

from pathlib import Path
from typing import Literal

from pydantic import Field

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class EvalSettings(Settings):
    """``eval_store`` picks the store: memory for tests and demos, postgres otherwise.

    The harness reads its golden sets from ``eval_golden_dir`` (relative to the working
    directory, the repo root under ``make run``) and, under the nightly profile, reaches a real
    model through the gateway at ``eval_gateway_url``. A run that takes longer than
    ``eval_harness_timeout_seconds`` is stopped and stores nothing.
    """

    eval_store: Store = "postgres"
    eval_golden_dir: Path = Path("evals/golden")
    eval_gateway_url: str = "http://localhost:8008"
    eval_harness_timeout_seconds: float = Field(default=1800.0, gt=0)
