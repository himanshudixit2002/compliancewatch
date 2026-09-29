"""Process configuration of the rulebook service: ``CW_*`` variables on top of py-common's."""

from typing import Literal

from pydantic import SecretStr

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class RulebookSettings(Settings):
    """``rulebook_store`` picks the store: memory for tests and demos, postgres otherwise.

    ``rulebook_write_token`` is the shared secret the pipeline sends in ``x-cw-write-token`` to
    write regulator documents, mentions, relation candidates and clause embeddings. Unset, every
    such write is refused (503): the rulebook fails closed, because its tables are shared by every
    tenant.

    ``rulebook_review_token`` is the shared secret the analyst workbench sends in
    ``x-cw-review-token`` for review decisions, relation approvals, citations, the version
    lifecycle and the sweep. The write token does not open those routes; unset, they are refused
    (503). It is a shared secret, not an identity: the approver ids in the bodies are asserted by
    the caller until the identity service exists.

    ``rulebook_publish_enabled`` turns on publishing and withdrawing rule versions and the daily
    transition sweep (``CW_RULEBOOK_PUBLISH_ENABLED``, default off; owner
    regulatory-intelligence; remove the flag once the workbench publishes in production and the
    obligation consumer of the rule events is live). Off, those routes answer 503, the
    ``rulebook-transitions`` command stops without changing anything, and citing and review
    still work.
    """

    rulebook_store: Store = "postgres"
    rulebook_write_token: SecretStr | None = None
    rulebook_review_token: SecretStr | None = None
    rulebook_publish_enabled: bool = False
