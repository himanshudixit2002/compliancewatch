"""Process configuration of the profile service: ``CW_*`` variables on top of py-common's."""

from pathlib import Path
from typing import Literal

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class ProfileSettings(Settings):
    """``profile_store`` picks the persistence: memory for tests and demos, postgres otherwise.
    ``profile_eval_cases_path`` is where not-applicable answers are appended as golden-case
    seeds (JSON lines); empty keeps them in the database review task only."""

    profile_store: Store = "postgres"
    profile_eval_cases_path: Path | None = None
