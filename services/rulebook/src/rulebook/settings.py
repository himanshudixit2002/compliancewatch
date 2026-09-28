"""Process configuration of the rulebook service: ``CW_*`` variables on top of py-common's."""

from typing import Literal

from pydantic import SecretStr

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class RulebookSettings(Settings):
    """``rulebook_store`` picks the store: memory for tests and demos, postgres otherwise.

    ``rulebook_write_token`` is the shared secret the pipeline sends in ``x-cw-write-token`` to
    write regulator documents. Unset, every write is refused (503): the rulebook fails closed,
    because its tables are shared by every tenant.
    """

    rulebook_store: Store = "postgres"
    rulebook_write_token: SecretStr | None = None
