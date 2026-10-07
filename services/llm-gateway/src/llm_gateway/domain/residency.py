"""Where a model call may send text: the residency policy (``CW_LLM_RESIDENCY``, ADR-020).

- ``global`` (the default): the masked text may reach a model outside India, through a provider
  asked for zero data retention. Every real call does today, since no routed model runs
  inference in India.
- ``india_only``: no text leaves India, so every call to a real model is refused with
  ``ResidencyUnavailableError`` (503 ``llm-residency-unavailable``) before it is made. A
  ``fake/...`` model, which the gateway serves in process, still answers.

Which of the two the product runs under is the maintainer's decision, taken with counsel
(ADR-020, Proposed).
"""

from enum import StrEnum


class ResidencyPolicy(StrEnum):
    GLOBAL = "global"
    INDIA_ONLY = "india_only"

    @property
    def real_models_allowed(self) -> bool:
        """Whether a call may reach a real model; every routed one runs outside India today."""
        return self is ResidencyPolicy.GLOBAL
