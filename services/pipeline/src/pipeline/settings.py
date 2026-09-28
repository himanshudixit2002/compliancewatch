"""Process configuration of the pipeline worker: ``CW_*`` variables on top of py-common's."""

from pydantic import SecretStr

from py_common.settings import Settings


class PipelineSettings(Settings):
    """``pipeline_knowledge_enabled`` turns on handing parsed documents to the rulebook
    (``CW_PIPELINE_KNOWLEDGE_ENABLED``, default off; owner regulatory-intelligence; remove the
    flag once ADR-017 is accepted). Off, the worker makes no call to the rulebook.

    ``rulebook_url`` and ``rulebook_write_token`` reach the rulebook's write API; the token is
    the rulebook's ``CW_RULEBOOK_WRITE_TOKEN``.
    """

    pipeline_knowledge_enabled: bool = False
    rulebook_url: str = "http://localhost:8003"
    rulebook_write_token: SecretStr | None = None
