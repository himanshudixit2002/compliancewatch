"""Process configuration of the pipeline worker: ``CW_*`` variables on top of py-common's."""

from pathlib import Path

from pydantic import SecretStr

from py_common.settings import Settings


class PipelineSettings(Settings):
    """``pipeline_knowledge_enabled`` turns on handing parsed documents to the rulebook and
    embedding their clauses (``CW_PIPELINE_KNOWLEDGE_ENABLED``, default off; owner
    regulatory-intelligence; remove the flag once ADR-017 is accepted). Off, the worker makes no
    call to the rulebook or the gateway.

    ``rulebook_url`` and ``rulebook_write_token`` reach the rulebook's write API; the token is
    the rulebook's ``CW_RULEBOOK_WRITE_TOKEN``. ``llm_gateway_url`` is where the relation stage's
    model calls and the clause embeddings go (``CW_LLM_GATEWAY_URL``). ``pipeline_prompts_dir``
    is where the prompt files are when the package is installed away from the source tree (the
    image sets ``CW_PIPELINE_PROMPTS_DIR=/app/prompts``); the worker reads them only with the
    flag on.
    """

    pipeline_knowledge_enabled: bool = False
    rulebook_url: str = "http://localhost:8003"
    rulebook_write_token: SecretStr | None = None
    llm_gateway_url: str = "http://localhost:8008"
    pipeline_prompts_dir: Path | None = None
