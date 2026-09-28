"""Process configuration of the obligation service: ``CW_*`` variables on top of py-common's."""

from typing import Literal

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class ObligationSettings(Settings):
    """``obligation_store`` picks the store: memory for tests and demos, postgres otherwise."""

    obligation_store: Store = "postgres"
