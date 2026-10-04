"""Process configuration of the rulebook service: ``CW_*`` variables on top of py-common's."""

from typing import Literal, Self

from pydantic import SecretStr, model_validator

from py_common.settings import Settings

Store = Literal["memory", "postgres"]
LOCAL_ENVIRONMENTS = frozenset({"local", "test"})
"""Where the local conveniences work: synthetic approvals and the seed loaded at start."""
SYNTHETIC_ENVIRONMENTS = LOCAL_ENVIRONMENTS
"""Where a synthetic approval is accepted."""


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
    the caller. With ``CW_AUTH_MODE`` dual or token, an access token opens the writes instead (the
    pipeline's with rulebook:write, an analyst's with the route's regulatory role) and a user's
    token names the actor; token mode refuses both shared secrets (``api.deps``).

    ``rulebook_publish_enabled`` turns on publishing and withdrawing rule versions and the daily
    transition sweep (``CW_RULEBOOK_PUBLISH_ENABLED``, default off; owner
    regulatory-intelligence; remove the flag once the workbench publishes in production and the
    obligation consumer of the rule events is live). Off, those routes answer 503, the
    ``rulebook-transitions`` command stops without changing anything, and citing and review
    still work.

    ``synthetic_approvals_allowed`` follows ``CW_ENV``: only local and test accept an approval
    marked synthetic, the one the local product's demo publication sends, which counts towards
    the review round but leaves the version needs_review.

    ``rulebook_seed_on_start`` (``CW_RULEBOOK_SEED_ON_START``, default off) loads the packaged
    seed calendar's draft versions into the memory store when the app is built, as
    ``make seed SERVICE=rulebook`` writes them into Postgres, so a rulebook without a database
    (the web app's ``make web-stack``) holds the drafts an analyst cites, submits and reviews.
    Every version it loads is a draft that needs review. It is configuration, not a rollout: it
    is refused unless ``CW_ENV`` is local or test, and with the Postgres store, which the seed
    command fills.
    """

    rulebook_store: Store = "postgres"
    rulebook_write_token: SecretStr | None = None
    rulebook_review_token: SecretStr | None = None
    rulebook_publish_enabled: bool = False
    rulebook_seed_on_start: bool = False

    @property
    def synthetic_approvals_allowed(self) -> bool:
        return self.env in SYNTHETIC_ENVIRONMENTS

    @model_validator(mode="after")
    def _seed_on_start_in_a_local_memory_store_only(self) -> Self:
        if not self.rulebook_seed_on_start:
            return self
        if self.env not in LOCAL_ENVIRONMENTS:
            raise ValueError(
                f"CW_RULEBOOK_SEED_ON_START is refused with CW_ENV={self.env}: it loads the seed "
                "calendar's drafts at start in local and test only; elsewhere make seed "
                "SERVICE=rulebook writes them into Postgres"
            )
        if self.rulebook_store != "memory":
            raise ValueError(
                "CW_RULEBOOK_SEED_ON_START fills the memory store (CW_RULEBOOK_STORE=memory); "
                "a Postgres rulebook gets the seed calendar from make seed SERVICE=rulebook"
            )
        return self
